"""HTTP API for projects, targets and runs (M1).

Thin layer over app/repo.py. Repo exceptions map to HTTP status codes:
NotFound -> 404, RunConflict -> 409 (an app already has a live run), bad input
-> 422 (handled by Pydantic / explicit ValueError).
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from . import repo
from .db import get_session
from .schemas import (
    ProjectCreate,
    ProjectOut,
    RunCreate,
    RunOut,
    TargetCreate,
    TargetOut,
)

router = APIRouter()


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
def start_run(target_id: int, body: RunCreate, session: Session = Depends(get_session)):
    try:
        return repo.start_run(
            session, target_id=target_id, story_id=body.story_id, mode=body.mode
        )
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except repo.RunConflict as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.get("/runs", response_model=list[RunOut])
def list_runs(target_id: int | None = None, session: Session = Depends(get_session)):
    return repo.list_runs(session, target_id=target_id)


@router.get("/runs/{run_id}", response_model=RunOut)
def get_run(run_id: int, session: Session = Depends(get_session)):
    try:
        return repo.get_run(session, run_id)
    except repo.NotFound as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
