"""Database engine/session wiring.

DATABASE_URL defaults to the dockerized Postgres published on localhost, so the
API (in the container) and the tests (on the host) both work without extra
config. Models live in app/models.py; the repository in app/repo.py.
"""

from __future__ import annotations

import os
from collections.abc import Callable

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

DEFAULT_URL = "postgresql+psycopg://qa:qa@localhost:5432/qa"


def database_url() -> str:
    return os.environ.get("DATABASE_URL", DEFAULT_URL)


class Base(DeclarativeBase):
    pass


def make_engine(url: str | None = None):
    return create_engine(url or database_url(), pool_pre_ping=True, future=True)


# Default app engine/session factory (lazily usable by the API).
engine = make_engine()
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)

# "Something that opens a session", for the modules that take one as a
# parameter so a test can substitute the fixture's. It lives here because this
# module owns the session, which is the same rule the tracked tree follows
# (README: defined once, in render.py, so hydrate, ingest and delivery cannot
# disagree). It was in app/orchestrator/driver.py until P5-05 -- the driver was
# the first thing to need the alias -- and that stopped making sense the moment
# the driver no longer took one: `app/control/local.py` would have been
# importing a session-factory type from the pipeline driver.
SessionFactory = Callable[[], "Session"]


def get_session():
    """FastAPI dependency: yield a session, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
