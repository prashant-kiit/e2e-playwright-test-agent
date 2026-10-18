"""Pytest fixtures for DB-backed tests.

These connect to the dockerized Postgres (published on localhost) using a
dedicated `qa_test` database, created on demand. If Postgres is unreachable the
DB-backed tests skip, so the pure-domain tests still run offline.
"""

from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import OperationalError, ProgrammingError
from sqlalchemy.orm import sessionmaker

from app.db import Base, database_url
import app.models  # noqa: F401  (register the ORM tables on Base.metadata)

TEST_DB = "qa_test"


def _base_url():
    return make_url(database_url())


@pytest.fixture(scope="session")
def pg_engine():
    base = _base_url()
    # Create the test database from the maintenance DB, if needed.
    maint = create_engine(base.set(database="postgres"), isolation_level="AUTOCOMMIT", future=True)
    try:
        with maint.connect() as conn:
            try:
                conn.execute(text(f'CREATE DATABASE "{TEST_DB}"'))
            except ProgrammingError:
                pass  # already exists
    except OperationalError as exc:
        pytest.skip(f"Postgres not reachable ({exc.__class__.__name__}); skipping DB tests")
    finally:
        maint.dispose()

    engine = create_engine(base.set(database=TEST_DB), future=True)
    Base.metadata.create_all(engine)
    yield engine
    engine.dispose()


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
        tables = ", ".join(f'"{t.name}"' for t in reversed(Base.metadata.sorted_tables))
        with pg_engine.begin() as conn:
            conn.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
