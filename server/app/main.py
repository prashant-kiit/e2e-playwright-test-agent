"""FastAPI entrypoint for the QA admin portal backend.

Mounts the projects/targets/runs API (M1) on top of the M0 health endpoint.
Tables are created on startup for this single-operator dev stack; a later
milestone can introduce Alembic migrations if the schema starts churning.
"""

from __future__ import annotations

import asyncio
import contextlib
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import models  # noqa: F401  (register ORM tables on Base.metadata)
from .api import router
from .auth_api import auth_router
from .reaper import reaper_loop


def _reaper_enabled() -> bool:
    """On by default; QA_REAPER=0 turns it off for tests and one-off processes."""
    return os.environ.get("QA_REAPER", "1") != "0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Schema is managed by Alembic (the container entrypoint runs
    # `alembic upgrade head` before uvicorn); tests create tables from metadata.
    task = asyncio.create_task(reaper_loop()) if _reaper_enabled() else None
    try:
        yield
    finally:
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task


app = FastAPI(title="QA Portal", version="0.1.0", lifespan=lifespan)

# CORS for the Vite dev server (same-origin in the dockerized nginx setup).
_origins = os.environ.get("QA_CORS_ORIGINS", "http://localhost:5173").split(",")
app.add_middleware(
    CORSMiddleware,
    allow_origins=[o.strip() for o in _origins if o.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(auth_router)
app.include_router(router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by docker-compose and the portal."""
    return {"status": "ok", "service": "qa-portal"}
