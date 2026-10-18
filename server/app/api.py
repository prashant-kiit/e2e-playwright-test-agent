"""HTTP API for projects, targets and runs (M1).

Thin layer over app/repo.py. Repo exceptions map to HTTP status codes:
NotFound -> 404, RunConflict -> 409 (an app already has a live run), bad input
-> 422 (handled by Pydantic / explicit ValueError).
"""

from __future__ import annotations

import json
import queue
from typing import Callable

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from sqlalchemy.orm import Session

from . import repo
from .db import get_session
from .domain.status import is_terminal
from .launcher import launch_run
from .orchestrator.bus import DONE, bus
from .schemas import (
    ProjectCreate,
    ProjectOut,
    RunCreate,
    RunOut,
    StepOut,
    TargetCreate,
    TargetOut,
)

router = APIRouter()


def get_launcher() -> Callable[[int], None]:
    """The background run launcher. Overridden to a no-op in tests."""
    return launch_run


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


@router.get("/runs/{run_id}/steps", response_model=list[StepOut])
def get_run_steps(run_id: int, session: Session = Depends(get_session)):
    try:
        run = repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return sorted(run.steps, key=lambda s: s.id)


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
