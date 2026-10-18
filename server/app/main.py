"""FastAPI entrypoint for the QA admin portal backend.

Mounts the projects/targets/runs API (M1) on top of the M0 health endpoint.
Tables are created on startup for this single-operator dev stack; a later
milestone can introduce Alembic migrations if the schema starts churning.
"""

from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI

from . import models  # noqa: F401  (register ORM tables on Base.metadata)
from .api import router
from .db import Base, engine


@asynccontextmanager
async def lifespan(app: FastAPI):
    Base.metadata.create_all(engine)
    yield


app = FastAPI(title="QA Portal", version="0.1.0", lifespan=lifespan)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by docker-compose and the portal."""
    return {"status": "ok", "service": "qa-portal"}
