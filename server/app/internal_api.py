"""The internal control-plane API: the only thing a sandbox can reach.

P5-05's one new seam. A sandbox no longer holds `DATABASE_URL` or the `S3_*`
credentials; it holds a run-scoped bearer token (app/run_token.py) and these
routes, and they are what hydrate, the pipeline, ingest, the artifact sweep and
the log stream now go through.

**Thin on purpose.** Every route is a bearer-token check, a `tenant_scope`, one
call into app/control/service.py, and a translation of that module's exceptions
into status codes. There is no logic here that is not about HTTP, because the
other transport (`LocalGateway`) does not speak HTTP and the two must not be
able to disagree about what an operation *does*. If a rule lived in a route, the
thread path would not have it.

**`/internal` and no cookie.** These routes take a bearer token and nothing
else: they are deliberately not on the router that `require_auth` guards, so an
operator's session cookie authorizes none of them and a run token authorizes
none of the portal (app/run_token.py's distinct salt is the other half of that).
The prefix exists so an ingress can refuse `/internal/*` from outside, which is
belt as well as braces -- the real boundary is that the sandbox network has no
route anywhere else.

**What this costs, and it is not nothing.** Putting the API on the sandbox
network to serve these routes makes the *whole* API reachable from a sandbox,
`/auth/login` included -- where before, the only things a run could reach were
Postgres and the object store. That is a smaller surface than a database
credential and a wider one than these routes alone, and the honest summary is:
a compromised agent can now reach the portal's login endpoint over the network,
with no credentials, no cookie that its token can produce
(`tests/test_internal_api.py` asserts a run token authorizes nothing there), and
no rate limiting in front of it. The clean fix is a second listener -- `/internal`
on its own port, and only that port on the sandbox network -- which is a
deployment change rather than a code one and is recorded as a follow-up in
VERIFICATION-P5.md rather than left to be noticed.

**Status codes, and what they are for.** The client is `HttpGateway`, in the same
package, so these are read by code rather than by a person:

    401   the token is missing, malformed, forged or past its signature's life
    403   the token is well-formed but does not authorize this: another run,
          another tenant, another target, a key outside its prefixes, or a run
          that is no longer live
    409   the operation is legitimate but the run's state refuses it (an illegal
          status transition), which is a race with an operator rather than an
          authorization failure
    422   the manifest or the body is malformed

401 and 403 are kept apart because the sandbox does different things with them:
a 403 on a live run means something is wrong with the deployment and the run
should fail loudly, while `RunNotLive` is the ordinary end of a run that was
stopped under it.

**One run's token answers only for `{run_id}` in the path.** The route reads the
run id from the URL *and* from the token and refuses a mismatch, rather than
ignoring the path and trusting the token. Both spellings exist because the URL is
what makes a request readable in a log and a trace; the refusal is what stops the
two from ever meaning different things.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from . import storage
from .control import service
from .control.model import TrackedBlob
from .db import get_session
from .domain.status import IllegalTransition
from .domain.steps import Step
from .run_token import RunScope, RunTokenError, verify
from .storage import Storage

internal_router = APIRouter(prefix="/internal")

# How much of an uploaded blob is held in memory before it goes to a temporary
# file on its way to the store. A trace or a video is routinely tens of
# megabytes and the API serves every live run at once, so the upload is spooled
# rather than read into a bytes object.
_SPOOL_MAX = 8 << 20


def get_storage() -> Storage:
    """The blob store these routes read and write on a run's behalf.

    Its own dependency rather than `api.get_storage`, so a test of the internal
    surface overrides the internal surface. The suite refuses the real client
    outright (tests/conftest.py), so a route test that forgets the override
    fails loudly rather than reaching SeaweedFS.
    """
    return storage.from_env()


def run_scope(
    run_id: int,
    authorization: str | None = Header(default=None),
) -> RunScope:
    """The scope a request's bearer token carries, for `{run_id}`.

    The signature, the payload and the age are checked here (app/run_token.py);
    whether the run is *live*, and whether this scope matches the row, is checked
    in the service, because it needs the database and because it must hold on the
    thread path too.
    """
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(401, "a run-scoped bearer token is required")
    try:
        scope = verify(authorization.split(" ", 1)[1].strip())
    except RunTokenError as exc:
        raise HTTPException(
            401, f"this token does not authorize anything: {exc}"
        ) from exc
    if scope.run_id != run_id:
        # The path and the token disagree. Refused rather than resolved in
        # either direction: a request whose URL says one run and whose authority
        # says another is not a request anything should guess the meaning of.
        raise HTTPException(
            403, f"this token is not for run {run_id}"
        )
    return scope


ScopeDep = Depends(run_scope)


def _translate(exc: Exception) -> HTTPException:
    """One place turning the service's exceptions into status codes."""
    if isinstance(exc, service.NotAuthorized):
        return HTTPException(403, str(exc))
    if isinstance(exc, IllegalTransition):
        return HTTPException(409, str(exc))
    if isinstance(exc, service.ControlPlaneError):
        return HTTPException(422, str(exc))
    raise exc


class _Translating:
    """`with _translating(): ...` around every service call in this module.

    A context manager rather than a decorator per route: the routes differ in
    their parameters and their response shapes but not in how they fail, and
    this keeps the mapping in `_translate` as the single answer to "what does a
    sandbox see when it asks for something it may not have?".
    """

    def __enter__(self) -> None:
        return None

    def __exit__(self, _t, exc, _tb) -> bool:
        if exc is None:
            return False
        raise _translate(exc) from exc


_translating = _Translating


# --- reads ---------------------------------------------------------------

@internal_router.get("/runs/{run_id}/facts")
def read_facts(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        return service.run_facts(session, scope).as_dict()


@internal_router.get("/runs/{run_id}/state")
def read_state(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        return service.run_state(session, scope).as_dict()


@internal_router.get("/runs/{run_id}/status")
def read_status(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        return {"status": service.run_status(session, scope)}


@internal_router.get("/runs/{run_id}/head-revision")
def read_head_revision(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    """The head revision, or `{"revision": null}` for a target with none.

    A 200 with a null body rather than a 404: "this target has no revision" is
    an answer, and the sandbox turns it into hydrate's `NoHeadRevision` with its
    own message. A 404 would be indistinguishable from a routing mistake.
    """
    with service.acting_as(scope), _translating():
        head = service.head_revision(session, scope)
    return {"revision": None if head is None else head.as_dict()}


@internal_router.get("/runs/{run_id}/artifacts")
def read_artifacts(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        rows = service.list_artifacts(session, scope)
    return {"artifacts": [row.as_dict() for row in rows]}


# --- blobs ---------------------------------------------------------------

@internal_router.get("/runs/{run_id}/blobs/{key:path}")
def read_blob(
    run_id: int,
    key: str,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
) -> StreamingResponse:
    """Stream one blob or artifact back.

    Streamed rather than buffered: hydrate materializes every file of a
    revision through here and the artifact the session archive fetches is a
    tarball, so the API must not hold either in memory per live run.
    """
    with service.acting_as(scope), _translating():
        chunks, content_type = service.read_blob(session, scope, store, key)
    return StreamingResponse(chunks, media_type=content_type)


@internal_router.head("/runs/{run_id}/blobs/{key:path}")
def blob_exists(
    run_id: int,
    key: str,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
) -> dict:
    """Ingest's dedup check, as the HTTP verb that means it.

    A `HEAD` rather than a `GET` returning a boolean, because the question is
    "is this content already stored?" and the answer must not cost the bytes.
    A key outside the token's prefixes is a 403 here exactly as it is on the
    `GET`: existence is precisely the side channel `authorize_blob_key` exists
    to close, so this route must not be the cheap way round it.
    """
    with service.acting_as(scope), _translating():
        if not service.blob_exists(session, scope, store, key):
            raise HTTPException(404, "no such blob")
    return {}


@internal_router.put("/runs/{run_id}/blobs/{key:path}")
async def write_blob(
    run_id: int,
    key: str,
    request: Request,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
) -> dict:
    """Upload one blob or artifact.

    Spooled to a temporary file rather than read into memory: the `Storage`
    protocol takes a path (it streams the file into S3), and a trace or a video
    is routinely tens of megabytes with every live run uploading at once.
    """
    content_type = request.headers.get("content-type")
    with tempfile.NamedTemporaryFile(prefix="qa-upload-", delete=True) as spool:
        async for chunk in request.stream():
            spool.write(chunk)
        spool.flush()
        with service.acting_as(scope), _translating():
            service.write_blob(
                session, scope, store, key, Path(spool.name), content_type
            )
    return {}


# --- writes --------------------------------------------------------------

@internal_router.post("/runs/{run_id}/begin")
def begin_run(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.begin_run(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/complete")
def complete_run(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.complete_run(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/fail")
def fail_run(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.fail_run(session, scope, str(body.get("reason", "")))
    return {}


@internal_router.post("/runs/{run_id}/pause")
def pause_run(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.pause_run(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/stop")
def stop_run(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.stop_run(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/steps/{step}/{transition}")
def step_transition(
    run_id: int,
    step: str,
    transition: str,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    """`start`, `complete` or `fail` one step.

    One route for the three because they take the same parameters and differ
    only in which `repo` function runs -- and because the step is the same
    path segment in all three, which is what makes a run's step transitions one
    readable sequence in a request log.
    """
    try:
        parsed = Step(step)
    except ValueError as exc:
        raise HTTPException(422, f"not a step: {step!r}") from exc
    fn = {
        "start": service.start_step,
        "complete": service.complete_step,
        "fail": service.fail_step,
    }.get(transition)
    if fn is None:
        raise HTTPException(422, f"not a step transition: {transition!r}")
    with service.acting_as(scope), _translating():
        fn(session, scope, parsed)
    return {}


@internal_router.put("/runs/{run_id}/session-id")
def set_session_id(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    """Record or clear the agent's session id.

    A null `session_id` clears it, rather than a separate DELETE route: "the
    recorded session is gone" is one fact with two spellings, and the caller
    that clears it does so because a restore failed -- which is the same moment
    it would otherwise set one.
    """
    with service.acting_as(scope), _translating():
        value = body.get("session_id")
        if value:
            service.set_session_id(session, scope, str(value))
        else:
            service.clear_session_id(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/heartbeat")
def heartbeat(
    run_id: int,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.heartbeat(session, scope)
    return {}


@internal_router.post("/runs/{run_id}/cost")
def record_cost(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    with service.acting_as(scope), _translating():
        service.record_cost(
            session,
            scope,
            spend_usd=float(body.get("spend_usd", 0.0)),
            sandbox_seconds=int(body.get("sandbox_seconds", 0)),
        )
    return {}


@internal_router.post("/runs/{run_id}/revisions")
def commit_revision(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
) -> dict:
    """Commit revision N+1 from a manifest. `{"rev": null}` if unchanged.

    The manifest is paths, content hashes and sizes; the blobs went up through
    the blob route first. The service recomputes the tree hash from the manifest
    and confirms every blob is present before it writes a row, so neither a
    claimed hash nor a dropped upload can produce a revision that does not
    describe real bytes.
    """
    try:
        files = [TrackedBlob.from_dict(raw) for raw in body["files"]]
        author = str(body["author"])
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, f"malformed revision manifest: {exc}") from exc
    with service.acting_as(scope), _translating():
        rev = service.commit_revision(session, scope, store, files, author=author)
    return {"rev": rev}


@internal_router.post("/runs/{run_id}/artifacts")
def index_artifact(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    """Record one already-uploaded artifact. Returns its version."""
    try:
        key = str(body["key"])
        sha256 = str(body["sha256"])
        kind = str(body["kind"])
        raw_step = body.get("step")
    except (KeyError, TypeError) as exc:
        raise HTTPException(422, f"malformed artifact: {exc}") from exc
    try:
        step = Step(raw_step) if raw_step else None
    except ValueError as exc:
        raise HTTPException(422, f"not a step: {raw_step!r}") from exc
    with service.acting_as(scope), _translating():
        version = service.index_artifact(
            session, scope, key=key, sha256=sha256, kind=kind, step=step
        )
    return {"version": version}


@internal_router.post("/runs/{run_id}/logs")
def publish_log(
    run_id: int,
    body: dict,
    scope: RunScope = ScopeDep,
    session: Session = Depends(get_session),
) -> dict:
    """Append a batch of log lines.

    Batched because this is the one operation a run performs in volume, and one
    request per line was the container path's worst round-trip cost.

    There is no close route: a Postgres-backed stream ends when the run's status
    does (`PostgresLogBus.close` is a no-op and says why), so a close here would
    be a route that does nothing -- which is a route somebody later makes do
    something.
    """
    lines = body.get("lines") or []
    if not isinstance(lines, list):
        raise HTTPException(422, "lines must be a list")
    with service.acting_as(scope), _translating():
        if lines:
            service.publish_log(session, scope, [str(line) for line in lines])
    return {}
