"""HTTP API for projects, targets, their trees and their runs.

Thin layer over app/repo.py and app/authoring.py. Exceptions map to status
codes: NotFound -> 404, RunConflict -> 409 (a live run holds the target, for a
second run *or* for an operator write), a refused configuration or story ->
422, a delivery problem -> 400/502.

P3 collapsed apps and targets into one concept. There is no filesystem-backed
app list, no story list read off a directory and no snapshot-the-disk action:
a target is a row, its tree is a revision, and the portal is the only way a
story gets in.
"""

from __future__ import annotations

import json
import queue
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from . import apphub, authoring, delivery, repo, revisions, storage, target_config
from .auth import AuthDep
from .db import SessionLocal, get_session
from .domain.status import is_terminal
from .launcher import launch_run
from .models import Artifact
from .orchestrator.bus import DONE, bus
from .schemas import (
    ArtifactOut,
    DeliverBody,
    DeliveryOut,
    DeliveryStateOut,
    FileIndexOut,
    ProjectCreate,
    ProjectOut,
    PromptOut,
    ResetBody,
    RevisionOut,
    RunCreate,
    RunOut,
    StepOut,
    StoryBody,
    StoryContentOut,
    StoryOut,
    TargetConfigUpdate,
    TargetCreate,
    TargetCreatedOut,
    TargetOut,
    WriteOut,
)
from .storage import Storage

# Everything on this router requires a valid session cookie (tests override
# require_auth to a no-op). Health and /auth/* live off this router.
router = APIRouter(dependencies=[AuthDep])


def get_launcher() -> Callable[[int], None]:
    """The background run launcher. Overridden to a no-op in tests."""
    return launch_run


def get_storage() -> Storage:
    """The artifact blob store. Overridden with a fake in tests."""
    return storage.from_env()


def get_bootstrap_runner() -> Callable[[str], apphub.BootstrapOutcome]:
    """The optional "sync infra to the target repo" step. Overridden in tests
    (no git, no network)."""
    return apphub.run_bootstrap


def get_catalog(store: Storage = Depends(get_storage)) -> delivery.Catalog:
    """Just the database half of the delivery seam: no git, no GitHub, no PAT.

    "Is this delivered?" is a Postgres question (invariant 5), so answering it
    must not need a credential. Hanging it off `get_delivery_tools` meant an
    operator with no `GITHUB_PAT` configured got a 503 for an answer that never
    leaves the database -- found in a real browser, where the portal could not
    show the badge at all.
    """
    return delivery.DbCatalog(SessionLocal, store)


def get_delivery_tools() -> delivery.Tools:
    """git + GitHub + the PAT. Overridden in tests so no route touches the
    network; building it here (not at import) keeps a missing PAT from breaking
    unrelated endpoints.

    Dependencies resolve before the handler body runs, so a failure here would
    escape the routes' own exception handling as a bare 500. A missing `git` or
    a missing PAT is an environment problem, so it is reported as 503 with the
    reason rather than as an opaque server error.
    """
    try:
        return delivery.default_tools()
    except delivery.DeliveryError as exc:
        raise HTTPException(
            status_code=503, detail=f"delivery is unavailable: {exc}"
        ) from exc


# --- prompts + settings --------------------------------------------------

@router.get("/prompts", response_model=list[PromptOut])
def list_prompts():
    return apphub.read_prompts()


@router.get("/settings")
def get_settings():
    return apphub.settings()


@router.post("/projects", response_model=ProjectOut, status_code=201)
def create_project(body: ProjectCreate, session: Session = Depends(get_session)):
    return repo.create_project(session, name=body.name)


@router.get("/projects", response_model=list[ProjectOut])
def list_projects(session: Session = Depends(get_session)):
    return repo.list_projects(session)


@router.post(
    "/projects/{project_id}/targets", response_model=TargetCreatedOut, status_code=201
)
def create_target(
    project_id: int,
    body: TargetCreate,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
    run_sync=Depends(get_bootstrap_runner),
):
    """Create a target, its configuration, and its revision 1.

    Revision 1 comes from the templates and the renderer, so a new target has a
    tree to hydrate and a history to show before its first run -- which is what
    let the baseline-from-disk hook go.

    A configuration the write path refuses is the operator's typo, not a server
    fault, so it answers 422 with the reason rather than 500. The optional infra
    sync is reported as an outcome rather than raised: the target exists either
    way, and the form shows the failure next to the target it did create.
    """
    try:
        target, revision = authoring.create_target(
            session,
            store,
            project_id=project_id,
            app=body.app,
            name=body.name,
            base_url=body.base_url,
            target_repo=body.target_repo,
            target_branch=body.target_branch,
            locators=body.locators,
            agent_notes=body.agent_notes,
        )
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except target_config.ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except IntegrityError as exc:
        session.rollback()
        raise HTTPException(
            status_code=409, detail=f"a target named {body.app!r} already exists"
        ) from exc

    return TargetCreatedOut(
        target=target,
        revision=_revision_out(revision, revisions.count_files(session, revision.id)),
        bootstrap=run_sync(target.app) if body.sync_infra else None,
    )


@router.patch("/targets/{target_id}/config", response_model=WriteOut)
def update_target_config(
    target_id: int,
    body: TargetConfigUpdate,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Edit a target's configuration. A changed base URL commits a revision.

    `base_url` re-renders the generated Playwright config, which is a tree diff,
    which is a revision -- a configuration change as reviewable as a code
    change. `locators` and `agent_notes` reach the agent through its prompt, so
    they change the row and commit nothing.
    """
    target = _target_or_404(session, target_id)
    try:
        _target, revision = authoring.update_config(
            session, store, target, **body.model_dump(exclude_none=True)
        )
    except target_config.ConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _write_out(session, store, target, revision)


# --- story authoring: the only way a story gets in -----------------------

def _write_out(session: Session, store: Storage, target, revision) -> WriteOut:
    return WriteOut(
        revision=(
            _revision_out(revision, revisions.count_files(session, revision.id))
            if revision is not None
            else None
        ),
        stories=authoring.list_stories(session, store, target),
    )


@router.get("/targets/{target_id}/stories", response_model=list[StoryOut])
def list_stories(
    target_id: int,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """A target's stories, from the head revision's file_index."""
    target = _target_or_404(session, target_id)
    return authoring.list_stories(session, store, target)


@router.get("/targets/{target_id}/stories/{story_id}", response_model=StoryContentOut)
def read_story(
    target_id: int,
    story_id: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    target = _target_or_404(session, target_id)
    try:
        return authoring.read_story(session, store, target, story_id)
    except authoring.NoSuchStory as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.put("/targets/{target_id}/stories/{story_id}", response_model=WriteOut)
def write_story(
    target_id: int,
    story_id: str,
    body: StoryBody,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Create or replace one story, committing one operator-authored revision."""
    target = _target_or_404(session, target_id)
    if body.story_id != story_id:
        raise HTTPException(
            status_code=422,
            detail=f"story id in the path ({story_id}) and body ({body.story_id}) differ",
        )
    try:
        revision = authoring.write_story(
            session,
            store,
            target,
            story_id=body.story_id,
            slug=body.slug,
            content=body.content,
        )
    except authoring.InvalidStory as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except IntegrityError as exc:
        # unique(target_id, rev): a concurrent writer got there first. Losing is
        # the designed outcome -- there is no merge (DESIGN.md invariant 2).
        session.rollback()
        raise HTTPException(
            status_code=409,
            detail="another write committed a revision first; reload and try again",
        ) from exc
    return _write_out(session, store, target, revision)


@router.delete("/targets/{target_id}/stories/{story_id}", response_model=WriteOut)
def delete_story(
    target_id: int,
    story_id: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Remove one story. Its plan and suite are left alone."""
    target = _target_or_404(session, target_id)
    try:
        revision = authoring.delete_story(session, store, target, story_id=story_id)
    except authoring.NoSuchStory as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    return _write_out(session, store, target, revision)


@router.get("/targets", response_model=list[TargetOut])
def list_targets(project_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_targets(session, project_id=project_id)


# --- delivery: bootstrap-check / deliver / reset (P1) --------------------

@router.get("/targets/{target_id}/delivery", response_model=DeliveryStateOut)
def target_delivery_state(
    target_id: int,
    session: Session = Depends(get_session),
    catalog: delivery.Catalog = Depends(get_catalog),
):
    """Delivered, or N revisions ahead. One Postgres query, no network call.

    It depends on the catalog rather than the whole delivery seam, because it
    needs no credential: the answer is in the database, and requiring a PAT to
    read it would be requiring the network by another name.
    """
    target = _target_or_404(session, target_id)
    try:
        ref = delivery.target_ref(catalog.config(target.app))
        state = catalog.state(target.app)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryStateOut(
        app=ref.app,
        repo=ref.repo,
        branch=ref.branch,
        bootstrapped=state.bootstrapped,
        delivered=state.delivered,
        rev=state.rev,
        delivered_sha=state.delivered_sha,
        revisions_ahead=state.revisions_ahead,
        summary=state.describe(),
    )


@router.post("/targets/{target_id}/deliver", response_model=DeliveryOut)
def deliver_story(
    target_id: int,
    body: DeliverBody,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    """Deliver one story's artifacts as a PR.

    Bootstrap is folded in under the same action (DESIGN.md decision 16), so an
    operator approving a delivery is approving "set the repo up and deliver".
    """
    target = _target_or_404(session, target_id)
    try:
        if not body.dry_run:
            delivery.ensure_bootstrapped(target.app, tools=tools)
        result = delivery.push_artifacts(
            target.app,
            body.story_id,
            run_id=body.run_id,
            dry_run=body.dry_run,
            tools=tools,
        )
    except delivery.CredentialError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryOut(
        ok=True,
        message=result.message,
        pr_url=result.pr_url,
        pr_number=result.pr_number,
        detail={
            "branch": result.branch,
            "committed": result.committed,
            "delivered_sha": result.delivered_sha,
        },
    )


@router.post("/targets/{target_id}/reset", response_model=DeliveryOut)
def reset_target_repo(
    target_id: int,
    body: ResetBody,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    """DESTRUCTIVE: wipe the target repo. Requires the repo name echoed back."""
    target = _target_or_404(session, target_id)
    try:
        result = delivery.reset_target(
            target.app,
            confirm_repo=body.confirm_repo,
            dry_run=body.dry_run,
            tools=tools,
        )
    except delivery.ConfirmationMismatch as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except delivery.CredentialError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryOut(
        ok=True,
        message=result.message,
        detail={
            "deleted_branches": list(result.deleted_branches),
            "failed_branches": list(result.failed_branches),
            "already_empty": result.already_empty,
        },
    )


def _target_or_404(session: Session, target_id: int):
    try:
        return repo.get_target(session, target_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


# --- revisions / file_index ----------------------------------------------
#
# Read-only: the revisions panel is the operator's window into a target's tree,
# and the only writers of a revision are ingest (at a run's step boundaries) and
# the operator writes above. There is no snapshot-the-disk action, because there
# is no authoritative disk left to snapshot, and no parity route, because there
# is no second copy of the truth to compare against.
#
# Every route resolves through a row and filters by the request's tenant, so a
# blob is never served by key alone (DESIGN.md §9). The tenant is always 1
# today; filtering anyway is the structural half of P5.

# Tracked files are displayed as source, so they stream as text whatever their
# extension implies. See revision_file_content.
TRACKED_FILE_MEDIA_TYPE = "text/plain; charset=utf-8"


def _revision_out(rev, file_count: int) -> RevisionOut:
    return RevisionOut(
        id=rev.id,
        rev=rev.rev,
        parent_rev=rev.parent_rev,
        tree_hash=rev.tree_hash,
        produced_by_run_id=rev.produced_by_run_id,
        author=rev.author,
        created_at=rev.created_at,
        file_count=file_count,
    )


@router.get("/targets/{target_id}/revisions", response_model=list[RevisionOut])
def list_target_revisions(target_id: int, session: Session = Depends(get_session)):
    _target_or_404(session, target_id)
    return [
        _revision_out(rev, count)
        for rev, count in revisions.list_revisions_with_file_counts(session, target_id)
    ]


def _revision_or_404(session: Session, revision_id: int):
    rev = revisions.get_revision(session, revision_id)
    if rev is None:
        raise HTTPException(status_code=404, detail=f"no revision {revision_id}")
    return rev


@router.get("/revisions/{revision_id}/files", response_model=list[FileIndexOut])
def list_revision_files(revision_id: int, session: Session = Depends(get_session)):
    _revision_or_404(session, revision_id)
    return revisions.list_files(session, revision_id)


@router.get("/revisions/{revision_id}/file")
def revision_file_content(
    revision_id: int,
    path: str,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Stream one tracked file's bytes out of blob storage.

    `path` is a query parameter rather than a wildcard path segment so tracked
    paths with slashes need no escaping scheme.

    The row is found first and its tenant checked, and only then is the blob it
    names read: knowing a blob key is not enough to read bytes.
    """
    _revision_or_404(session, revision_id)
    row = revisions.get_file(session, revision_id, path)
    if row is None:
        raise HTTPException(
            status_code=404, detail=f"revision {revision_id} has no file {path!r}"
        )
    try:
        chunks, _ = store.get_stream(row.blob_key)
    except Exception as exc:  # object missing / store down
        raise HTTPException(status_code=502, detail=f"storage error: {exc}") from exc
    # A tracked file is source text to read, never a document to re-encode, so
    # it is always served as text rather than under the type its extension
    # guesses. Two reasons, both found by review: `application/json` makes a
    # browser parse package.json and re-serialise it, which is no longer the
    # bytes that were stored (ticket 04 asks for byte-identical); and
    # mimetypes guesses `video/mp2t` for .ts, which is the bulk of a suite.
    return StreamingResponse(chunks, media_type=TRACKED_FILE_MEDIA_TYPE)


@router.post("/targets/{target_id}/runs", response_model=RunOut, status_code=201)
def start_run(
    target_id: int,
    body: RunCreate,
    session: Session = Depends(get_session),
    launcher: Callable[[int], None] = Depends(get_launcher),
):
    try:
        run = repo.start_run(
            session, target_id=target_id, story_id=body.story_id, mode=body.mode
        )
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    launcher(run.id)  # kick off the orchestrator in the background
    return run


@router.get("/runs", response_model=list[RunOut])
def list_runs(target_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_runs(session, target_id=target_id)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    try:
        return repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/pause", response_model=RunOut)
def pause_run(run_id: int, session: Session = Depends(get_session)):
    try:
        return repo.request_pause(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/stop", response_model=RunOut)
def stop_run(run_id: int, session: Session = Depends(get_session)):
    try:
        return repo.request_stop(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/runs/{run_id}/resume", response_model=RunOut)
def resume_run(
    run_id: int,
    session: Session = Depends(get_session),
    launcher: Callable[[int], None] = Depends(get_launcher),
):
    try:
        run = repo.resume_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RepoError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    launcher(run.id)  # a fresh orchestrator re-begins from the last checkpoint
    return run


@router.get("/runs/{run_id}/steps", response_model=list[StepOut])
def get_run_steps(run_id: int, session: Session = Depends(get_session)):
    try:
        run = repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sorted(run.steps, key=lambda s: s.id)


@router.get("/runs/{run_id}/artifacts", response_model=list[ArtifactOut])
def list_artifacts(run_id: int, session: Session = Depends(get_session)):
    try:
        repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return list(
        session.scalars(
            select(Artifact).where(Artifact.run_id == run_id).order_by(Artifact.id)
        )
    )


@router.get("/artifacts/{artifact_id}/content")
def artifact_content(
    artifact_id: int,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Stream an artifact's bytes through the API (avoids presigned-URL host
    mismatch between the container and the browser in local dev)."""
    art = session.get(Artifact, artifact_id)
    if art is None:
        raise HTTPException(status_code=404, detail=f"no artifact {artifact_id}")
    try:
        chunks, content_type = store.get_stream(art.s3_key)
    except Exception as exc:  # object missing / store down
        raise HTTPException(status_code=502, detail=f"storage error: {exc}") from exc
    return StreamingResponse(chunks, media_type=content_type)


@router.get("/runs/{run_id}/events")
def run_events(run_id: int, session: Session = Depends(get_session)):
    """Server-sent events of the run's live log. A finished run replays its
    recorded history and closes; a live run streams until it ends."""
    try:
        run = repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    terminal = is_terminal(run.status)

    def _event(line: str) -> str:
        return f"data: {json.dumps(line)}\n\n"

    def gen():
        q, history = bus.subscribe(run_id)
        try:
            for line in history:
                yield _event(line)
            if terminal:
                yield "event: end\ndata: \"\"\n\n"
                return
            while True:
                try:
                    item = q.get(timeout=15)
                except queue.Empty:
                    yield ": keepalive\n\n"
                    continue
                if item is DONE:
                    yield "event: end\ndata: \"\"\n\n"
                    return
                yield _event(item)
        finally:
            bus.unsubscribe(run_id, q)

    return StreamingResponse(gen(), media_type="text/event-stream")
