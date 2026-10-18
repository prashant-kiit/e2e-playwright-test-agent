"""Database engine/session wiring.

DATABASE_URL defaults to the dockerized Postgres published on localhost, so the
API (in the container) and the tests (on the host) both work without extra
config. Models live in app/models.py; the repository in app/repo.py.
"""

from __future__ import annotations

import os

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

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


def get_session():
    """FastAPI dependency: yield a session, always closed."""
    session = SessionLocal()
    try:
        yield session
    finally:
        session.close()
