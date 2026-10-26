"""Pytest fixtures for DB-backed tests.

These connect to the dockerized Postgres (published on localhost) using a
dedicated `qa_test` database, created on demand. If Postgres is unreachable the
DB-backed tests skip, so the pure-domain tests still run offline.

The schema is built by **running the Alembic migrations**, not by
`Base.metadata.create_all`. Those two can disagree -- a revision that forgets a
column, an index or a server default still passes a create_all-backed suite --
and the migration chain is what actually runs in production. Testing the
migrations is the only way a drift bug fails here rather than on deploy.
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (register the ORM tables on Base.metadata)
from app.db import Base, database_url
from app.tenancy import DEFAULT_TENANT_ID

TEST_DB = "qa_test"
SERVER_DIR = Path(__file__).resolve().parents[1]


def _base_url():
    return make_url(database_url())


def db_unavailable(reason: str):
    """Skip the DB-backed tests -- unless QA_REQUIRE_DB says a database was
    promised, in which case fail loudly.

    CI sets QA_REQUIRE_DB=1 because it stands Postgres up as a service: there, an
    unreachable database is a broken job, not a reason to run a third of the
    suite and report success. Locally the variable is unset and the skip stands,
    so the pure-domain tests still run offline.
    """
    if os.environ.get("QA_REQUIRE_DB", "").strip() not in ("", "0", "false"):
        pytest.fail(f"QA_REQUIRE_DB is set but Postgres is unreachable: {reason}")
    pytest.skip(reason)


def _alembic_upgrade(url) -> None:
    """`alembic upgrade head` against `url`, in-process."""
    from alembic.config import Config

    from alembic import command

    cfg = Config(str(SERVER_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(SERVER_DIR / "alembic"))
    cfg.set_main_option("sqlalchemy.url", url.render_as_string(hide_password=False))
    command.upgrade(cfg, "head")


@pytest.fixture(scope="session")
def pg_engine():
    base = _base_url()
    # Recreate the test database from the maintenance DB. Dropping it first is
    # deliberate: the migration chain is then exercised from zero on every run,
    # and a qa_test left over from the old create_all fixture (which has no
    # alembic_version row) cannot wedge the upgrade.
    maint = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True)
    try:
        with maint.connect() as conn:
            conn.execute(text(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)'))
            conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
    except OperationalError as exc:
        db_unavailable(f"Postgres not reachable ({exc.__class__.__name__}); skipping DB tests")
    except ProgrammingError as exc:  # pragma: no cover - surfaced, never swallowed
        db_unavailable(f"could not create {TEST_DB}: {exc}")
    finally:
        maint.dispose()

    test_url = base.set(database=TEST_DB)
    _alembic_upgrade(test_url)

    engine = create_engine(test_url, future=True)
    yield engine
    engine.dispose()


@pytest.fixture(autouse=True)
def _clear_bus():
    """Keep the in-memory log bus isolated between tests (run ids reset on
    truncate, so history could otherwise leak across tests)."""
    from app.orchestrator.bus import bus

    bus.reset()
    yield
    bus.reset()


@pytest.fixture(autouse=True)
def _no_real_blob_storage(monkeypatch):
    """No test may reach a live S3 endpoint.

    `storage.from_env()` defaults to the dev stack's SeaweedFS on localhost, so
    a test that forgets to override the `get_storage` dependency passes on a
    developer machine with the stack up and fails in CI, which stands up
    Postgres but no object store. That is exactly how one got in: a route test
    built its own TestClient, overrode four dependencies, and committed its
    target's revision 1 against real S3.

    Blocking the seam here turns that into an immediate, self-explaining failure
    on the machine that wrote the test. The sibling of QA_REQUIRE_DB: the suite
    is designed to run against the in-memory fake, so reaching for the real
    client is always the bug, never the environment.
    """

    def refuse(*args, **kwargs):
        raise AssertionError(
            "a test reached real blob storage via storage.from_env(); override "
            "the app.api.get_storage dependency (or pass store=) with "
            "tests.storage_helpers.FakeStorage"
        )

    monkeypatch.setattr("app.storage.from_env", refuse)


@pytest.fixture(autouse=True)
def _no_real_dns(monkeypatch):
    """No test may resolve a name against real DNS.

    P4's write path refuses a base URL that does not resolve to a public address
    (DESIGN.md §6). The resolver is injected for exactly that reason, so a test
    that reaches the real one has forgotten to pass it -- and would then pass or
    fail depending on what `demo.example.com` happens to resolve to from the
    machine running it, which for a check this load-bearing is worse than
    useless. The sibling of `_no_real_blob_storage`.
    """

    def refuse(host, *args, **kwargs):
        raise AssertionError(
            f"a test resolved {host!r} against real DNS; pass resolve= (see "
            f"tests.target_helpers.public_resolver) or override the "
            f"app.api.get_resolver dependency"
        )

    monkeypatch.setattr("app.sandbox.egress.system_resolver", refuse)


# `tenants` is deliberately not truncated: its single row is seeded by the
# migration, so it is schema-level reference data rather than test state. Wiping
# it would leave every tenant_id FK dangling and make the fixture describe a
# database production never has. Any *extra* tenant a test adds (to prove the
# tenant filter does real work) is still cleaned up, so the next test starts
# from exactly the state the migration left.
_PRESERVED_TABLES = frozenset({"tenants"})


def _truncate_all(engine):
    tables = ", ".join(
        f'"{t.name}"'
        for t in reversed(Base.metadata.sorted_tables)
        if t.name not in _PRESERVED_TABLES
    )
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        conn.execute(
            text("DELETE FROM tenants WHERE id <> :seeded").bindparams(
                seeded=DEFAULT_TENANT_ID
            )
        )


@pytest.fixture()
def session(pg_engine):
    """A clean session per test: truncate all tables afterwards."""
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    sess = Session()
    try:
        yield sess
    finally:
        sess.rollback()
        sess.close()
        _truncate_all(pg_engine)


@pytest.fixture()
def session_factory(pg_engine):
    """A sessionmaker for code (like the orchestrator driver) that opens its own
    short-lived sessions. Truncates all tables afterwards."""
    Session = sessionmaker(bind=pg_engine, expire_on_commit=False, future=True)
    try:
        yield Session
    finally:
        _truncate_all(pg_engine)
