"""HTTP API for projects, targets and runs (M1).

Thin layer over app/repo.py. Repo exceptions map to HTTP status codes:
NotFound -> 404, RunConflict -> 409 (an app already has a live run), bad input
-> 422 (handled by Pydantic / explicit ValueError).
"""

from __future__ import annotations

import json
import queue
from collections.abc import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from . import apphub, delivery, repo, storage
from .auth import AuthDep
from .db import get_session
from .domain.status import is_terminal
from .launcher import launch_run
from .models import Artifact
from .orchestrator.bus import DONE, bus
from .schemas import (
    AppOut,
    ArtifactOut,
    BootstrapBody,
    BootstrappedOut,
    DeliverBody,
    DeliveryOut,
    ProjectCreate,
    ProjectOut,
    PromptOut,
    ResetBody,
    RunCreate,
    RunOut,
    StepOut,
    StoryOut,
    TargetCreate,
    TargetOut,
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


def get_bootstrap_runner() -> Callable[[str], dict]:
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


@router.post("/apps/bootstrap", status_code=201)
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
    try:
        return repo.create_target(session, project_id=project_id, app=body.app, name=body.name)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/targets", response_model=list[TargetOut])
def list_targets(project_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_targets(session, project_id=project_id)


# --- delivery: bootstrap-check / deliver / reset (P1) --------------------

@router.get("/targets/{target_id}/bootstrapped", response_model=BootstrappedOut)
def target_bootstrapped(
    target_id: int,
    session: Session = Depends(get_session),
    tools: delivery.Tools = Depends(get_delivery_tools),
):
    target = _target_or_404(session, target_id)
    try:
        ready, ref = delivery.is_bootstrapped(target.app, tools=tools)
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return BootstrappedOut(
        app=ref.app, repo=ref.repo, branch=ref.branch, bootstrapped=ready
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
    except delivery.NotBootstrapped as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except delivery.CredentialError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except delivery.DeliveryError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return DeliveryOut(
        ok=True,
        message=result.message,
        pr_url=result.pr_url,
        pr_number=result.pr_number,
        detail={"branch": result.branch, "committed": result.committed},
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
