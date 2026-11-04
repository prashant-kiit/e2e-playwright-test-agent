"""FastAPI entrypoint for the QA admin portal backend.

Mounts the projects/targets/runs API on top of the health endpoint, plus the
internal control-plane API a sandbox talks to (app/internal_api.py). The two are
separate routers because they are separate authorities: a portal session cookie
authorizes nothing under `/internal`, and a run-scoped token authorizes nothing
outside it.

The schema is owned by Alembic: the container entrypoint runs
`alembic upgrade head` before uvicorn, and nothing here creates tables. The
tests build their schema the same way, by running the migrations from zero --
never `Base.metadata.create_all`, which would hide a revision that forgot a
column (see tests/conftest.py).
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from . import (
    config,
    models,  # noqa: F401  (register ORM tables on Base.metadata)
)
from .api import router
from .auth_api import auth_router
from .envelope import verify_credential_config
from .internal_api import internal_router
from .reaper import reaper_loop
from .sandbox.dispatch import destroy_sandbox

logger = logging.getLogger(__name__)


def check_credential_config() -> None:
    """Refuse to start without a credential key, and say which one is in use.

    Named for the refusal, because that is the half that matters: an earlier
    name said only `log_...`, which hid a function whose first job is to stop
    the process.

    Two jobs, both of which have to happen before anything is served.

    It **refuses to come up** if no key is configured (`app/envelope.py`
    raises). `wrapper_from_env` is otherwise called lazily, at the moment a
    customer saves a PAT or a delivery decrypts one -- so a deployment with
    neither `QA_KMS_KEY_ID` nor `QA_ENVELOPE_KEY` would start cleanly, serve,
    and fail that one route, which is an operator reading a 500 instead of a
    process that would not boot.

    And it says which wrapper was built, so a deployment storing every
    customer's PAT under a key in its own process does not look identical to
    one using a KMS. **At `WARNING` when that is what a deployment is doing**,
    because this process installs no logging configuration -- uvicorn
    configures its own loggers and the root logger has no handler -- so an
    `app.*` record below `WARNING` never reaches a terminal. An `INFO` line
    here was checked against a real uvicorn boot and printed nothing at all.
    A development stack is *meant* to be on that key, so there it stays `INFO`:
    a warning on every `make up` is a warning nobody reads when it matters.
    """
    wrapper = verify_credential_config()
    message = "stored credentials are protected by: %s"
    if wrapper.production or config.is_dev_deployment():
        logger.info(message, wrapper.describe)
    else:
        logger.warning(message, wrapper.describe)


def _reaper_enabled() -> bool:
    """On by default; QA_REAPER=0 turns it off for tests and one-off processes."""
    return os.environ.get("QA_REAPER", "1") != "0"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # The credential key arrangement, before anything is served.
    check_credential_config()

    # Schema is managed by Alembic (the container entrypoint runs
    # `alembic upgrade head` before uvicorn), in the app and in the tests alike.
    # `reap_sandbox` is passed rather than imported by the reaper: a reaped run
    # whose container is still running is still costing money, and the dispatch
    # seam cannot be imported from app/reaper.py without a cycle.
    task = (
        asyncio.create_task(reaper_loop(reap_sandbox=destroy_sandbox))
        if _reaper_enabled()
        else None
    )
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
# The run-facing control plane (P5-05). Mounted beside the portal's router
# rather than on it: these routes take a run-scoped bearer token and no cookie,
# so `require_auth` -- which guards every route on `router` -- must not apply.
app.include_router(internal_router)


@app.get("/health")
def health() -> dict[str, str]:
    """Liveness probe used by docker-compose and the portal."""
    return {"status": "ok", "service": "qa-portal"}
