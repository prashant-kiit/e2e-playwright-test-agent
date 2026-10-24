"""HTTP API for projects, targets and runs (M1).

Thin layer over app/repo.py. Repo exceptions map to HTTP status codes:
NotFound -> 404, RunConflict -> 409 (an app already has a live run), bad input
-> 422 (handled by Pydantic / explicit ValueError).
"""

from __future__ import annotations

import json
import queue
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException, Response
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import apphub, delivery, monorepo, repo, revisions, storage, target_config
from .auth import AuthDep
from .db import get_session
from .domain.status import is_terminal
from .launcher import launch_run
from .models import Artifact
from .orchestrator.bus import DONE, bus
from .schemas import (
    AppOut,
    ArtifactOut,
    BootstrapAppOut,
    BootstrapBody,
    DeliverBody,
    DeliveryOut,
    DeliveryStateOut,
    FileIndexOut,
    ParityOut,
    ProjectCreate,
    ProjectOut,
    PromptOut,
    ResetBody,
    RevisionOut,
    RunCreate,
    RunOut,
    SnapshotOut,
    StepOut,
    StoryOut,
    TargetCreate,
    TargetOut,
)
from .storage import Storage
from .target_config import config_of

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
    """The target-repo step of bootstrapping. Overridden in tests (no git/network)."""
    return apphub.run_bootstrap


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


# --- repo introspection + bootstrap (M6) --------------------------------

@router.get("/apps", response_model=list[AppOut])
def list_apps():
    return apphub.list_apps()


@router.get("/apps/{app}/stories", response_model=list[StoryOut])
def list_stories(app: str):
    return apphub.list_stories(app)


@router.post("/apps/bootstrap", status_code=201, response_model=BootstrapAppOut)
def bootstrap_app(
    body: BootstrapBody,
    run=Depends(get_bootstrap_runner),
):
    try:
        return apphub.bootstrap_app(body.model_dump(), run=run, do_bootstrap=body.do_bootstrap)
    except apphub.BootstrapError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


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


@router.post("/projects/{project_id}/targets", response_model=TargetOut, status_code=201)
def create_target(
    project_id: int, body: TargetCreate, session: Session = Depends(get_session)
):
    """Create a target and its configuration.

    A configuration the write path refuses is the operator's typo, not a server
    fault, so it answers 422 with the reason rather than 500.
    """
    try:
        return repo.create_target(
            session,
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


@router.get("/targets", response_model=list[TargetOut])
def list_targets(project_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_targets(session, project_id=project_id)


# --- delivery: bootstrap-check / deliver / reset (P1) --------------------

@router.get("/targets/{target_id}/delivery", response_model=DeliveryStateOut)
def target_delivery_state(
    target_id: int,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    """Delivered, or N revisions ahead. One Postgres query, no network call."""
    target = _target_or_404(session, target_id)
    try:
        ref = delivery.target_ref(tools.catalog.config(target.app))
        state = tools.state(target.app)
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


# --- revisions / file_index / parity (P2) --------------------------------
#
# Read-only, except the snapshot action. Nothing here reads the revision tables
# to make a decision -- `apps/` is still authoritative for the whole of P2, and
# a route that started deciding from these rows would remove the safety net the
# phase exists to keep (DESIGN.md §13).
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


@router.post("/targets/{target_id}/revisions/snapshot", response_model=SnapshotOut)
def snapshot_target_tree(
    target_id: int,
    response: Response,
    session: Session = Depends(get_session),
    store: Storage = Depends(get_storage),
):
    """Snapshot a target's tracked tree right now, outside any run.

    **P2-only scaffolding.** It exists so an operator can give a never-run
    target a head revision to compare parity against. In P3 the filesystem is
    not authoritative and "snapshot the disk" stops meaning anything, so this
    route goes away with the mount it reads.

    An unchanged tree commits nothing and answers 200 with the existing head;
    a new revision answers 201.
    """
    target = _target_or_404(session, target_id)
    try:
        with monorepo.staged_tree(target.app, config_of(target)) as root:
            committed = revisions.commit_revision(
                session, target, store, root, author="operator"
            )
    except Exception as exc:  # the blob store is down, or the tree is unreadable
        raise HTTPException(status_code=502, detail=f"snapshot failed: {exc}") from exc

    if committed is None:
        head = revisions.head_revision(session, target_id)
        if head is None:  # an empty tracked tree hashes to a new revision, so
            raise HTTPException(  # this is unreachable in practice
                status_code=500, detail="snapshot committed nothing and there is no head"
            )
        response.status_code = 200
        return SnapshotOut(
            created=False,
            revision=_revision_out(head, revisions.count_files(session, head.id)),
        )

    response.status_code = 201
    return SnapshotOut(
        created=True,
        revision=_revision_out(committed, revisions.count_files(session, committed.id)),
    )


@router.get("/targets/{target_id}/revisions", response_model=list[RevisionOut])
def list_target_revisions(target_id: int, session: Session = Depends(get_session)):
    _target_or_404(session, target_id)
    return [
        _revision_out(rev, count)
        for rev, count in revisions.list_revisions_with_file_counts(session, target_id)
    ]


@router.get("/targets/{target_id}/parity", response_model=ParityOut)
def target_parity(target_id: int, session: Session = Depends(get_session)):
    """Whether the head revision agrees with the files on disk.

    The phase's evidence, and strictly read-only: parity never repairs or
    re-snapshots, because a self-healing check would hide the drift it exists
    to surface.
    """
    target = _target_or_404(session, target_id)
    with monorepo.staged_tree(target.app, config_of(target)) as root:
        parity = revisions.target_parity(session, target, root)
    return ParityOut(
        has_revision=parity.has_revision,
        in_sync=parity.in_sync,
        rev=parity.rev,
        tree_hash=parity.tree_hash,
        only_in_db=list(parity.diff.only_in_db),
        only_on_disk=list(parity.diff.only_on_disk),
        modified=list(parity.diff.modified),
    )


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
