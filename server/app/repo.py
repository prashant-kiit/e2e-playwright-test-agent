"""Repository: all database reads/writes for the portal.

The one subtle piece is `start_run`, which enforces "at most one live run per
app" with a lease-backed lock (not a boolean): it takes the app's lock row
FOR UPDATE, reaps it if its lease has expired (a crashed run), then inserts the
new run and lock atomically. The app_locks PK is the ultimate guard against a
race between two starters.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta

from sqlalchemy import select
from sqlalchemy.orm import Session

from . import target_config
from .domain import lease
from .domain.status import LIVE, TERMINAL, RunStatus, assert_transition, is_live
from .domain.steps import Step
from .models import AppLock, Project, Run, RunStep, Target
from .sandbox.egress import Resolver
from .tenancy import current_tenant_id

VALID_MODES = ("changed", "full")


class RepoError(Exception):
    pass


class NotFound(RepoError):
    pass


class RunConflict(RepoError):
    """A live run already holds this target's lock.

    Raised by two different callers and answered as 409 by both: a second run
    for the same target, and an operator write while a run is live. The reason
    differs, so it is a parameter -- an operator told "already has a live run"
    when they tried to edit a story would not know what to do next.
    """

    def __init__(self, target_id: int, run_id: int, reason: str | None = None) -> None:
        super().__init__(
            reason or f"app (target {target_id}) already has a live run {run_id}"
        )
        self.target_id = target_id
        self.run_id = run_id


# --- projects / targets --------------------------------------------------

def create_project(session: Session, name: str) -> Project:
    project = Project(tenant_id=current_tenant_id(), name=name)
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


def create_target(
    session: Session,
    project_id: int,
    app: str,
    name: str,
    *,
    base_url: str,
    target_repo: str,
    target_branch: str | None = None,
    locators: str = "",
    agent_notes: list[str] | None = None,
    resolve: Resolver | None = None,
) -> Target:
    """Create a target with its configuration, validated before the insert.

    A target without a usable base URL and target repo is a target no run can
    hydrate and no delivery can push, so the configuration is required here
    rather than being filled in later (app/target_config.py says what "usable"
    means). Validating first means a refused write leaves no half-made target.

    The values travel as keywords through the API route, `authoring` and this
    function rather than as one bundled value, deliberately: `TargetConfig` is
    derived *from* a row and so cannot precede one, and the names have to stay
    visible for `clean_fields` to tell the operator which field they mistyped.
    Creating and editing then clean through the same map, which is the part that
    matters -- a sixth field cannot reach one path and miss the other.

    `resolve` is the injected DNS resolver the base-URL check uses (P4, §6).
    It is a parameter rather than a module default because the check is
    load-bearing and has to be testable without DNS; left unset, the real
    resolver is used.
    """
    get_project(session, project_id)  # ensure the project exists
    cleaned = target_config.clean_fields(
        {
            "name": name,
            "base_url": base_url,
            "target_repo": target_repo,
            "target_branch": target_branch,
            "locators": locators,
            "agent_notes": agent_notes,
        },
        resolve=resolve,
    )
    target = Target(
        tenant_id=current_tenant_id(),
        project_id=project_id,
        app=app,
        **cleaned,
    )
    session.add(target)
    session.commit()
    session.refresh(target)
    return target


def update_target_config(
    session: Session, target_id: int, *, resolve: Resolver | None = None, **fields
) -> Target:
    """Change a target's editable fields, validated the same way as a create.

    Only the fields named are touched, so the portal's form can send one changed
    value. `app` and the identity columns are not settable here: a target's slug
    is what its history, its blobs and its delivered branch names are keyed on.
    `name` is, because it is only ever a label.
    """
    target = get_target(session, target_id)
    cleaned = target_config.clean_fields(fields, resolve=resolve)
    for field, value in cleaned.items():
        setattr(target, field, value)
    session.commit()
    session.refresh(target)
    return target


def live_run_holding(session: Session, target_id: int, now: datetime | None = None) -> Run | None:
    """The run that genuinely holds this target, or None.

    "Is a run live?" must mean the same thing here as it does in `start_run`,
    which is why this mirrors that function's test rather than asking whether a
    lock row exists. Three ways a lock row is not a live run:

    - its run is gone or already terminal -- an orphaned row;
    - its lease has lapsed and the run is not paused: that is a **crashed** run,
      exactly the case `start_run` reaps in place. Treating it as live would let
      one crash block every story and config edit until the reaper came round,
      and the reaper is a 30-second loop that may not be running at all.

    A **paused** run is live even though its lease has lapsed: the pause holds
    the lock deliberately and `reap_expired` skips it. Its resume re-hydrates
    from the head, so an edit made now would survive -- but it still owns the
    target, and "refused while the target has a live run" is the contract the
    portal states.
    """
    lock = session.get(AppLock, target_id)
    if lock is None:
        return None
    run = session.get(Run, lock.run_id)
    if run is None or not is_live(run.status):
        return None  # an orphaned lock row; the next start_run deletes it
    if run.status is RunStatus.PAUSED:
        return run
    if lease.is_expired(lock.lease_expires_at, now=now or lease.utcnow()):
        return None  # crashed, and start_run would reap it
    return run


def assert_no_live_run(session: Session, target_id: int) -> None:
    """Refuse a write while the target has a live run.

    A live run hydrated from an older head; its next ingest would commit a tree
    that does not contain the write, silently reverting it. Resolving that would
    need merge logic, and there is no merge logic anywhere in this system
    (DESIGN.md invariant 2) -- so the write is refused, not queued.
    """
    run = live_run_holding(session, target_id)
    if run is None:
        return
    raise RunConflict(
        target_id,
        run.id,
        reason=(
            f"target {target_id} has a live run ({run.id}), which is working from "
            f"an older revision. Saving now would be reverted by that run's next "
            f"snapshot, and there is no merge. Wait for it to finish, or pause or "
            f"stop it, then save again."
        ),
    )


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
        tenant_id=current_tenant_id(),
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
        AppLock(
            tenant_id=current_tenant_id(),
            target_id=target_id,
            run_id=run.id,
            lease_expires_at=run.lease_expires_at,
        )
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


def record_run_cost(
    session: Session,
    run_id: int,
    *,
    spend_usd: float | None = None,
    sandbox_seconds: int | None = None,
) -> None:
    """What the run cost. Written once, at the end of the run (P4's limits).

    Separate from the status transitions deliberately: a cost that failed to
    record must never be able to stop a run from reaching a terminal state, and
    a terminal state that failed to record must not be retried for the sake of
    an accounting column.
    """
    run = get_run(session, run_id)
    if spend_usd is not None:
        run.spend_usd = spend_usd
    if sandbox_seconds is not None:
        run.sandbox_seconds = sandbox_seconds
    session.commit()


def fail_overdue_runs(
    session: Session, *, max_age_s: float, now: datetime | None = None
) -> list[int]:
    """Fail every live run older than the per-run wall clock. Returns run ids.

    The reaper's half of that limit (DESIGN.md §6): a run whose sandbox is gone
    has no one left to check its own deadline, and a run still being driven is
    stopped at its next step boundary by the runner's half
    (app/orchestrator/limits.py). Both end the run `failed` naming the timeout,
    with the lock freed and the last committed revision intact.

    **A paused run is skipped**, like the lease reaper skips it: a deliberately
    parked run is not a wedged agent, which is what this limit bounds.
    """
    now = now or lease.utcnow()
    cutoff = now - timedelta(seconds=max_age_s)
    overdue: list[int] = []
    runs = session.scalars(
        select(Run).where(Run.created_at <= cutoff, Run.status.in_(tuple(LIVE)))
    ).all()
    for run in runs:
        if run.status is RunStatus.PAUSED:
            continue
        _fail_and_release(
            session,
            run,
            f"run timed out after {max_age_s:.0f}s without finishing (reaped)",
        )
        overdue.append(run.id)
    session.commit()
    return overdue


def reap_expired(session: Session, now: datetime | None = None) -> list[int]:
    """Fail every run whose lease has expired and free its app. Returns run ids."""
    now = now or lease.utcnow()
    reaped: list[int] = []
    locks = session.scalars(
        select(AppLock).where(AppLock.lease_expires_at <= now).with_for_update()
    ).all()
    for lock in locks:
        run = session.get(Run, lock.run_id)
        if run is not None and run.status is RunStatus.PAUSED:
            continue  # a deliberate pause holds the lock; it is not a crash
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


# --- run execution (driven by the orchestrator) -------------------------

def begin_run(session: Session, run_id: int, now: datetime | None = None) -> Run:
    """Move a run into RUNNING (from PENDING on first start, or from PAUSED on
    resume) and refresh its lease."""
    now = now or lease.utcnow()
    run = get_run(session, run_id)
    assert_transition(run.status, RunStatus.RUNNING)
    run.status = RunStatus.RUNNING
    _touch_lease(session, run, now)
    session.commit()
    session.refresh(run)
    return run


def start_step(session: Session, run_id: int, step: Step, now: datetime | None = None) -> RunStep:
    """Mark a step as running (creating its row, or bumping attempt on a retry)."""
    now = now or lease.utcnow()
    rs = session.scalars(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.step == step)
    ).one_or_none()
    if rs is None:
        rs = RunStep(
            tenant_id=current_tenant_id(),
            run_id=run_id,
            step=step,
            status="running",
            attempt=1,
            started_at=now,
        )
        session.add(rs)
    else:
        rs.attempt += 1
        rs.status = "running"
        rs.started_at = now
        rs.finished_at = None
    run = get_run(session, run_id)
    run.current_step = step
    _touch_lease(session, run, now)
    session.commit()
    session.refresh(rs)
    return rs


def complete_step(
    session: Session, run_id: int, step: Step, now: datetime | None = None
) -> RunStep:
    """Mark a step completed and record it as the run's last completed step."""
    now = now or lease.utcnow()
    rs = session.scalars(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.step == step)
    ).one()
    rs.status = "completed"
    rs.finished_at = now
    run = get_run(session, run_id)
    run.last_completed_step = step
    _touch_lease(session, run, now)
    session.commit()
    session.refresh(rs)
    return rs


def fail_step(session: Session, run_id: int, step: Step, now: datetime | None = None) -> None:
    """Mark a step failed (the run itself is failed separately via fail_run)."""
    now = now or lease.utcnow()
    rs = session.scalars(
        select(RunStep).where(RunStep.run_id == run_id, RunStep.step == step)
    ).one_or_none()
    if rs is not None:
        rs.status = "failed"
        rs.finished_at = now
    session.commit()


def set_sandbox_handle(session: Session, run_id: int, handle: str | None) -> None:
    """Record which sandbox is executing this run (P4's dispatch seam).

    Written by the launcher that dispatched it, cleared once that sandbox is
    gone, and never interpreted here: what a handle means is the scheduler's
    business.
    """
    run = get_run(session, run_id)
    run.sandbox_handle = handle
    session.commit()


def set_session_id(session: Session, run_id: int, session_id: str) -> None:
    """Persist the Claude Code session id so later steps can --resume it."""
    run = get_run(session, run_id)
    run.claude_session_id = session_id
    session.commit()


# The statuses whose sandbox nobody is using any more. It lives here rather than
# in domain/status.py because "idle" is a sandbox word, not a run-status one: the
# domain knows nothing about containers, and this is the one query that asks.
IDLE_SANDBOX = TERMINAL | {RunStatus.PAUSED}


def idle_sandbox_runs(session: Session) -> list[int]:
    """Runs that still name a sandbox nothing is using any more (P4).

    Paused **and** terminal, because the two leave the same thing behind for
    different reasons:

    * A *paused* run reaps immediately, with no grace window (DESIGN.md §5): the
      route that pauses a run destroys the container and clears this column
      itself. A handle still on a paused row means that did not finish -- an API
      that died mid-pause, or a pause that raced a dispatch.
    * A *terminal* run always leaves one. The run container carries `AutoRemove`
      and vanishes when the pipeline ends, but its **egress proxy** is a
      long-running container that exits on nobody's schedule, and the process
      that could ask for its removal is the one inside the sandbox -- which has
      no Docker socket, by design, and needs the proxy alive until its last
      step. So the reaper is not a net here; it is the only thing that removes
      a finished run's proxy, and without it every completed run leaks one.

    Live runs are excluded, and that is the load-bearing half: sweeping a
    RUNNING run would destroy the container doing the work, and a PENDING one is
    a dispatch that has not begun yet.
    """
    runs = session.scalars(
        select(Run).where(
            Run.status.in_(IDLE_SANDBOX), Run.sandbox_handle.is_not(None)
        )
    ).all()
    return [run.id for run in runs]


def clear_session_id(session: Session, run_id: int) -> None:
    """Forget the agent session this run was carrying.

    Written when a resumed run's session archive could not be restored (P4): the
    session genuinely is gone, and a run that still named it would tell the CLI
    to `--resume` something that does not exist -- a failed step instead of a
    forgotten exploration.
    """
    run = get_run(session, run_id)
    run.claude_session_id = None
    session.commit()


def complete_run(session: Session, run_id: int) -> Run:
    """Finish a run successfully and release its app lock."""
    run = get_run(session, run_id)
    assert_transition(run.status, RunStatus.COMPLETED)
    run.status = RunStatus.COMPLETED
    run.current_step = None
    _release_lock(session, run)
    session.commit()
    session.refresh(run)
    return run


def fail_run(session: Session, run_id: int, reason: str) -> Run:
    """Fail a run (e.g. a step errored) and release its app lock."""
    run = get_run(session, run_id)
    _fail_and_release(session, run, reason)
    session.commit()
    session.refresh(run)
    return run


def request_pause(session: Session, run_id: int) -> Run:
    """Ask a running run to pause at its next step boundary (no-op otherwise)."""
    run = get_run(session, run_id)
    if run.status is RunStatus.RUNNING:
        run.pause_requested = True
        session.commit()
        session.refresh(run)
    return run


def request_stop(session: Session, run_id: int) -> Run:
    """Ask a run to stop. A RUNNING run stops at its next boundary (flag only);
    a PENDING or PAUSED run has no live thread, so it stops immediately."""
    run = get_run(session, run_id)
    run.stop_requested = True
    if run.status in (RunStatus.PENDING, RunStatus.PAUSED):
        _stop(session, run)
    session.commit()
    session.refresh(run)
    return run


def pause_run(session: Session, run_id: int) -> Run:
    """Driver-side: transition RUNNING -> PAUSED at a boundary. The app lock is
    kept (the run still owns the app) but the lease is cleared, and the reaper
    skips PAUSED runs, so a deliberate pause is never mistaken for a crash."""
    run = get_run(session, run_id)
    assert_transition(run.status, RunStatus.PAUSED)
    run.status = RunStatus.PAUSED
    run.pause_requested = False
    run.lease_expires_at = None
    run.current_step = None
    session.commit()
    session.refresh(run)
    return run


def stop_run(session: Session, run_id: int) -> Run:
    """Driver-side: transition a live run -> STOPPED and release its app lock."""
    run = get_run(session, run_id)
    _stop(session, run)
    session.commit()
    session.refresh(run)
    return run


def resume_run(session: Session, run_id: int) -> Run:
    """Clear a paused run's flags so a fresh orchestrator can re-begin it.
    The actual PAUSED -> RUNNING transition happens in begin_run."""
    run = get_run(session, run_id)
    if run.status is not RunStatus.PAUSED:
        raise RepoError(f"run {run_id} is {run.status.value}, not paused; cannot resume")
    run.pause_requested = False
    run.stop_requested = False
    session.commit()
    session.refresh(run)
    return run


def _stop(session: Session, run: Run) -> None:
    assert_transition(run.status, RunStatus.STOPPED)
    run.status = RunStatus.STOPPED
    run.stop_requested = False
    run.current_step = None
    run.lease_expires_at = None
    _release_lock(session, run)


def _touch_lease(session: Session, run: Run, now: datetime) -> None:
    new_exp = lease.new_expiry(now=now)
    run.lease_expires_at = new_exp
    lock = session.get(AppLock, run.target_id)
    if lock is not None and lock.run_id == run.id:
        lock.lease_expires_at = new_exp


def _release_lock(session: Session, run: Run) -> None:
    lock = session.get(AppLock, run.target_id)
    if lock is not None and lock.run_id == run.id:
        session.delete(lock)
