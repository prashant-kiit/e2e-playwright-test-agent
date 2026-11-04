"""Where a run's gateway comes from, on each of the two paths.

Two call sites build one, and the asymmetry between them is the whole of P5-05:

- **the control plane mints**, because minting needs the signing key and the
  run's row, and it is the only thing that has either. `mint_for_run` is called
  by whatever is about to start a run working -- the thread launcher, or the
  Docker scheduler putting the token into a container's environment.
- **the sandbox consumes**, because that is all it can do: `from_env` builds an
  `HttpGateway` out of the two variables its container was given and there is
  nothing else in there to build one from. No `DATABASE_URL`, no `S3_*`.

**Minting happens inside the acting tenant's scope, so it needs no cross-tenant
read.** Both call sites run on a request thread, under `require_auth`, acting as
the user whose run this is -- so the ordinary tenant-filtered `repo.get_run` finds
it. That is why `app/launcher.py` no longer appears in the bypass allowlist in
tests/test_tenant_isolation_repo.py: the read that used to need a bypass
(resolving a run's tenant in order to open its scope) is not performed any more.
The token carries the tenant instead, and the gateway binds it per operation.

The consequence worth naming: `launch_run` must mint **before** it starts its
thread, because the thread has no request and therefore no acting tenant. It
does, and a test says so.
"""

from __future__ import annotations

import os

from .. import repo, run_token, storage
from ..db import SessionFactory, SessionLocal
from ..run_token import RunScope
from ..storage import Storage
from .http import HttpGateway
from .local import LocalGateway

# Where a sandbox finds the control plane, and the token it presents to it.
# Named here rather than in app/sandbox/env.py because this is the side that
# reads them; the environment builder imports these so the two cannot disagree
# about the spelling.
CONTROL_PLANE_URL = "QA_CONTROL_PLANE_URL"
RUN_TOKEN = "QA_RUN_TOKEN"


class NotASandbox(RuntimeError):
    """`from_env` was called somewhere that is not a sandbox.

    Raised rather than falling back to a local gateway, for the reason
    `dispatch.make_launcher` raises on an unknown `QA_SANDBOX`: a fallback would
    quietly give a process the control plane's own authority on a missing
    variable, which is the one thing this phase exists to make impossible.
    """


def mint_for_run(run_id: int, *, session_factory: SessionFactory = SessionLocal) -> str:
    """A token scoped to `run_id`'s run, target and tenant.

    Must be called while the run's tenant is the acting tenant -- which is the
    case at both call sites, both of which are on a request thread. A run of
    another tenant is simply not found.
    """
    with session_factory() as session:
        run = repo.get_run(session, run_id)
        return run_token.mint(
            RunScope(
                run_id=run.id, target_id=run.target_id, tenant_id=run.tenant_id
            )
        )


def local_for_run(
    run_id: int,
    *,
    session_factory: SessionFactory = SessionLocal,
    store: Storage | None = None,
) -> LocalGateway:
    """The thread path's gateway: a real token, the service in this process."""
    return LocalGateway(
        mint_for_run(run_id, session_factory=session_factory),
        session_factory=session_factory,
        store=store or storage.from_env(),
    )


def from_env() -> HttpGateway:
    """The sandbox's gateway, built from the only two things it was given."""
    base_url = os.environ.get(CONTROL_PLANE_URL, "").strip()
    token = os.environ.get(RUN_TOKEN, "").strip()
    if not base_url or not token:
        raise NotASandbox(
            f"{CONTROL_PLANE_URL} and {RUN_TOKEN} must both be set; a sandbox "
            f"has no other way to reach the control plane and no credentials to "
            f"fall back on"
        )
    return HttpGateway(base_url, token)
