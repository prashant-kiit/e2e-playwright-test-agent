"""Repository: all database reads/writes for the portal.

The one subtle piece is `start_run`, which enforces "at most one live run per
app" with a lease-backed lock (not a boolean): it takes the app's lock row
FOR UPDATE, reaps it if its lease has expired (a crashed run), then inserts the
new run and lock atomically. The app_locks PK is the ultimate guard against a
race between two starters.
"""

from __future__ import annotations

import uuid
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain import lease
from .domain.status import RunStatus, assert_transition, is_live
from .domain.steps import Step
from .models import AppLock, Artifact, Project, Run, RunStep, Target

VALID_MODES = ("changed", "full")


class RepoError(Exception):
    pass


class NotFound(RepoError):
    pass


class RunConflict(RepoError):
    """A live run already holds this app's lock."""

    def __init__(self, target_id: int, run_id: int) -> None:
        super().__init__(f"app (target {target_id}) already has a live run {run_id}")
        self.target_id = target_id
        self.run_id = run_id


# --- projects / targets --------------------------------------------------

def create_project(session: Session, name: str) -> Project:
    project = Project(name=name)
    session.add(project)
    session.commit()
    session.refresh(project)
    return project


def list_projects(session: Session) -> list[Project]:
    return list(session.scalars(select(Project).order_by(Project.id)))


def get_project(session: Session, project_id: int) -> Project:
    project = session.get(Project, project_id)
    if project is None:
        raise NotFound(f"no project {project_id}")
    return project


def create_target(session: Session, project_id: int, app: str, name: str) -> Target:
    get_project(session, project_id)  # ensure the project exists
    target = Target(project_id=project_id, app=app, name=name)
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def list_targets(session: Session, project_id: int | None = None) -> list[Target]:
    stmt = select(Target).order_by(Target.id)
    if project_id is not None:
        stmt = stmt.where(Target.project_id == project_id)
    return list(session.scalars(stmt))


def get_target(session: Session, target_id: int) -> Target:
    target = session.get(Target, target_id)
    if target is None:
        raise NotFound(f"no target {target_id}")
    return target


# --- runs + the lease lock ----------------------------------------------

def _new_run_key(app: str, now: datetime) -> str:
    return f"{now.strftime('%Y%m%d-%H%M%S')}-{app}-{uuid.uuid4().hex[:6]}"


def _fail_and_release(session: Session, run: Run, reason: str) -> None:
    """Mark a run FAILED and drop its app lock (used by reaper and start_run)."""
    if is_live(run.status):
        assert_transition(run.status, RunStatus.FAILED)
        run.status = RunStatus.FAILED
        run.error = reason
    lock = session.get(AppLock, run.target_id)
    if lock is not None and lock.run_id == run.id:
        session.delete(lock)


def start_run(
    session: Session,
    target_id: int,
    story_id: str,
    mode: str,
    now: datetime | None = None,
) -> Run:
    if mode not in VALID_MODES:
        raise ValueError(f"mode must be one of {VALID_MODES}, got {mode!r}")
    now = now or lease.utcnow()
    target = get_target(session, target_id)

    # Take the app's lock row FOR UPDATE so two concurrent starts serialise here.
    existing = session.scalars(
        select(AppLock).where(AppLock.target_id == target_id).with_for_update()
    ).one_or_none()

    if existing is not None:
        if not lease.is_expired(existing.lease_expires_at, now=now):
            raise RunConflict(target_id, existing.run_id)
        # Stale lock from a crashed run: reap it, then reuse the app.
        dead = session.get(Run, existing.run_id)
        if dead is not None:
            _fail_and_release(session, dead, "lease expired (reaped at start of a new run)")
        else:
            session.delete(existing)
        session.flush()

    run = Run(
        run_key=_new_run_key(target.app, now),
        target_id=target_id,
        story_id=story_id,
        mode=mode,
        status=RunStatus.PENDING,
        lease_expires_at=lease.new_expiry(now=now),
    )
    session.add(run)
    session.flush()  # assign run.id
    session.add(
        AppLock(target_id=target_id, run_id=run.id, lease_expires_at=run.lease_expires_at)
    )
    session.commit()
    session.refresh(run)
    return run


def heartbeat(session: Session, run_id: int, now: datetime | None = None) -> Run:
    """Extend the lease for a live run (called periodically by the orchestrator)."""
    now = now or lease.utcnow()
    run = get_run(session, run_id)
    if not is_live(run.status):
        raise RepoError(f"run {run_id} is not live ({run.status.value}); cannot heartbeat")
    new_exp = lease.new_expiry(now=now)
    run.lease_expires_at = new_exp
    lock = session.get(AppLock, run.target_id)
    if lock is not None and lock.run_id == run_id:
        lock.lease_expires_at = new_exp
    session.commit()
    session.refresh(run)
    return run


def reap_expired(session: Session, now: datetime | None = None) -> list[int]:
    """Fail every run whose lease has expired and free its app. Returns run ids."""
    now = now or lease.utcnow()
    reaped: list[int] = []
    locks = session.scalars(
        select(AppLock).where(AppLock.lease_expires_at <= now).with_for_update()
    ).all()
    for lock in locks:
        run = session.get(Run, lock.run_id)
        if run is not None and is_live(run.status):
            _fail_and_release(session, run, "lease expired (reaped)")
            reaped.append(run.id)
        else:
            session.delete(lock)
    session.commit()
    return reaped


def get_run(session: Session, run_id: int) -> Run:
    run = session.get(Run, run_id)
    if run is None:
        raise NotFound(f"no run {run_id}")
    return run


def list_runs(session: Session, target_id: int | None = None) -> list[Run]:
    stmt = select(Run).order_by(Run.id.desc())
    if target_id is not None:
        stmt = stmt.where(Run.target_id == target_id)
    return list(session.scalars(stmt))
