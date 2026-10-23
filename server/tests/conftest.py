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

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

import app.models  # noqa: F401  (register the ORM tables on Base.metadata)
from app.db import Base, database_url

TEST_DB = "qa_test"
SERVER_DIR = Path(__file__).resolve().parents[1]


def _base_url():
    return make_url(database_url())


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
        pytest.skip(f"Postgres not reachable ({exc.__class__.__name__}); skipping DB tests")
    except ProgrammingError as exc:  # pragma: no cover - surfaced, never swallowed
        pytest.skip(f"could not create {TEST_DB}: {exc}")
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


def _truncate_all(engine):
    tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
    with engine.begin() as conn:
        conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))


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
