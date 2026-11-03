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

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from . import target_config
from .domain import lease, quotas
from .domain.status import LIVE, TERMINAL, RunStatus, assert_transition, is_live
from .domain.steps import Step
from .models import AppLock, Project, Run, RunStep, Target, Tenant, User
from .sandbox.egress import Resolver
from .tenancy import ACROSS_TENANTS_OPTION, across_tenants, current_tenant_id

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


class QuotaExceeded(RepoError):
    """This tenant's plan will not fit another run right now (P5-04).

    Deliberately **not** a `RunConflict` and deliberately not a failed run.
    Three different things an operator can be told, with three different
    remedies, and collapsing any two of them loses the remedy:

    * `RunConflict` -- *this app* is busy. Wait for that run, or use another app.
    * `QuotaExceeded` -- *this tenant* is over an allowance. Wait, stop a run,
      or buy more -- depending on which cap, which `kind` carries.
    * a `failed` run -- the work was accepted, started, and went wrong. A breach
      must never look like this: nothing was dispatched and no run row exists,
      so a `failed` row would be a report of work that never happened, and it
      would consume monthly quota on the way.

    `limit` and `used` travel with it because the portal has to say "3 of 3"
    rather than "too many", and the route has no second chance to count.
    """

    def __init__(self, kind: quotas.QuotaKind, limit: int, used: int, reason: str) -> None:
        super().__init__(reason)
        self.kind = kind
        self.limit = limit
        self.used = used


class ConcurrencyLimitReached(QuotaExceeded):
    """The tenant's live runs are at its concurrent-run cap. Self-clearing: a
    running run will finish, and then the next start succeeds."""

    def __init__(self, limit: int, used: int) -> None:
        super().__init__(
            quotas.QuotaKind.CONCURRENCY,
            limit,
            used,
            f"this tenant already has {used} of {limit} runs going at once; "
            f"wait for one to finish or stop one, then start this again",
        )


class MonthlyQuotaExhausted(QuotaExceeded):
    """The tenant has started its month's allowance of runs. Not self-clearing:
    nothing the customer does to their running work frees any."""

    def __init__(self, limit: int, used: int) -> None:
        super().__init__(
            quotas.QuotaKind.MONTHLY,
            limit,
            used,
            f"this tenant has started {used} of its {limit} runs for this "
            f"calendar month; the quota resets at the start of next month",
        )


_BREACHES: dict[quotas.QuotaKind, type[QuotaExceeded]] = {
    quotas.QuotaKind.CONCURRENCY: ConcurrencyLimitReached,
    quotas.QuotaKind.MONTHLY: MonthlyQuotaExhausted,
}


# --- users ----------------------------------------------------------------

def get_user_for_login(session: Session, tenant_slug: str, email: str) -> User | None:
    """The user this email names *within the tenant this slug names*.

    The one read that cannot filter on `current_tenant_id()`, because it runs
    before there is a current tenant: establishing which tenant is acting is its
    whole job. So it is scoped the only other way it can be -- by the slug the
    caller supplied -- and the join is what keeps it a single-row lookup now
    that `users.email` is unique only per tenant (`uq_users_tenant_id_email`).

    None covers both an unknown slug and an unknown email, deliberately: the
    caller turns either into the same 401 a wrong password gets, so a probe
    cannot map out which tenants exist any more than which users do.

    **The one read in `repo` that opts out of the enforced tenant filter**
    (P5-02). It has to: the guard filters on `current_tenant_id()`, which
    outside a session answers the seeded default, so without the opt-out this
    query could only ever find users in tenant 1 -- every other tenant locked
    out of their own portal, and the symptom a bare 401 indistinguishable from
    a wrong password. The slug in the `where` is what replaces the filter, and
    it is a *tighter* scope than the guard's, not a looser one: one named
    tenant rather than whichever one happens to be current.
    """
    return session.scalars(
        across_tenants(
            select(User)
            .join(Tenant, Tenant.id == User.tenant_id)
            .where(Tenant.slug == tenant_slug, User.email == email)
        )
    ).one_or_none()


# Creating and removing users is the tenant-admin surface, which is its own P5
# ticket; this phase adds only what it uses, so there is no create_user here
# yet. The seeded admin comes from the migration.


# --- tenants --------------------------------------------------------------

def list_tenant_ids(session: Session) -> list[int]:
    """Every tenant's id, oldest first. What the background sweeps iterate.

    No tenant filter and no opt-out needed: `tenants` is the one table that
    does not carry `tenant_id` -- its own id *is* the tenant -- so it is not a
    `TenantOwned` entity and the read guard never applied to it.

    This is what lets the reaper stay inside the enforced read path rather than
    around it (P5-02): a sweep binds each tenant in turn and does its ordinary,
    filtered work, instead of issuing one unfiltered query whose nested reads
    would each need an opt-out of their own.
    """
    return list(session.scalars(select(Tenant.id).order_by(Tenant.id)))


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


class _Unset:
    """The "you did not mention this cap" marker for `set_tenant_caps`.

    A sentinel is needed because `None` is already a *value* on these columns --
    it means unmetered -- so it cannot double as the "not specified" default.
    Its own class rather than `object()` so a repr in a traceback says what it
    is.
    """

    def __repr__(self) -> str:  # pragma: no cover - diagnostics only
        return "<unset>"


UNSET = _Unset()


def set_tenant_caps(
    session: Session,
    *,
    max_concurrent_runs: int | None | _Unset = UNSET,
    monthly_run_quota: int | None | _Unset = UNSET,
) -> Tenant:
    """Set the current tenant's plan limits. Only the caps you pass are changed.

    `None` means **no cap**, and is therefore a value you can pass on purpose;
    a cap you leave out is left exactly as it was. Those have to be two
    different things: when `None` was both the default and the way to say
    "unmetered", raising a concurrency cap silently deleted the monthly quota,
    which the only caller this docstring names -- a console operator -- would
    have no reason to expect (found in review).

    The write half of P5-04, and for now the *only* way a cap gets set: there
    is still no tenant-admin surface (`VERIFICATION-P5.md` follow-up 6), so
    this is reached from the tests and from a console rather than from a route.
    Deliberately not exposed as an API endpoint by this ticket -- a tenant that
    could raise its own caps would not have caps.
    """
    tenant = session.get(Tenant, current_tenant_id())
    if tenant is None:  # pragma: no cover - a session always has its tenant
        raise NotFound(f"no such tenant {current_tenant_id()}")
    for name, value in (
        ("max_concurrent_runs", max_concurrent_runs),
        ("monthly_run_quota", monthly_run_quota),
    ):
        if isinstance(value, _Unset):
            continue
        if value is not None and value < 0:
            raise ValueError(f"{name} cannot be negative, got {value}")
        setattr(tenant, name, value)
    session.commit()
    session.refresh(tenant)
    return tenant


def tenant_usage(session: Session, *, now: datetime | None = None) -> quotas.Usage:
    """What the current tenant has spent: live runs, and runs started this month.

    Both counts are the tenant's across every one of its apps, and both are
    ordinary ORM selects, so `tenancy.install_read_guard` adds the `tenant_id`
    filter -- the same mechanism as every other read. A quota that counted
    another tenant's runs would be worse than no quota at all, so
    `test_quotas.py` proves the scoping rather than trusting it.

    `created_at` is the month boundary, not `updated_at`: the question is how
    many runs this tenant *started*, and a run that failed still spent a
    sandbox. A quota that only counted successes would make "retry until it
    works" free.

    **"Live" here means what `live_run_holding` means, not `status IN LIVE`**,
    and the difference is a regression this nearly shipped with. A run whose
    lease has lapsed and that is not paused is *crashed*: `start_run`'s own lock
    trio reaps it in place, a few lines below the quota check. Counting it would
    let a tenant at its cap with one dead run be refused by the check above the
    trio that was about to free it -- so the restart that worked before this
    slice would stop working until the reaper came round, and that is a
    30-second loop which may not be running at all. A **paused** run is the
    other way: it cleared its lease deliberately, `reap_expired` skips it, and
    it still owns its target, so it is live and it counts.
    """
    now = now or lease.utcnow()
    month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    live = session.scalar(
        select(func.count())
        .select_from(Run)
        .where(
            Run.status.in_(LIVE),
            or_(
                # Paused: lease cleared on purpose, still holding the target.
                Run.status == RunStatus.PAUSED,
                # No lease recorded: not reapable, so not provably crashed.
                Run.lease_expires_at.is_(None),
                # `lease.is_expired` is `now >= expires_at`, so "still live"
                # is strictly greater -- the same boundary, stated once.
                Run.lease_expires_at > now,
            ),
        )
    )
    this_month = session.scalar(
        select(func.count()).select_from(Run).where(Run.created_at >= month_start)
    )
    return quotas.Usage(live_runs=live or 0, runs_this_month=this_month or 0)


def tenant_caps(session: Session) -> quotas.Caps:
    """The current tenant's plan limits. `None` on either is no cap."""
    tenant = session.get(Tenant, current_tenant_id())
    if tenant is None:  # pragma: no cover - a session always has its tenant
        raise NotFound(f"no such tenant {current_tenant_id()}")
    return quotas.Caps(
        max_concurrent_runs=tenant.max_concurrent_runs,
        monthly_run_quota=tenant.monthly_run_quota,
    )


def _enforce_tenant_quotas(session: Session, *, now: datetime) -> None:
    """Refuse the enqueue if the tenant is at either cap.

    Counting is skipped entirely for an unmetered tenant: two aggregate queries
    per run start are not free, and a tenant with no caps has no answer they
    could change.
    """
    caps = tenant_caps(session)
    if caps.unmetered:
        return
    breach = quotas.breach(caps, tenant_usage(session, now=now))
    if breach is None:
        return
    raise _BREACHES[breach.kind](breach.limit, breach.used)


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

    # The tenant's allowance, checked *above* the lock trio and before any row
    # is written. Above, because the trio answers "is this app busy?" and this
    # answers "is this tenant over its plan?" -- different questions, and
    # DESIGN.md §5 is explicit that a scheduler goes above the trio rather than
    # inside it. Before any write, because a refusal must leave nothing behind:
    # a run row created and then rolled back would still have burned a
    # `run_key` and, worse, would have counted against the monthly quota it
    # was refused for.
    _enforce_tenant_quotas(session, now=now)

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


def get_run_across_tenants(session: Session, run_id: int) -> Run:
    """One run by id, **without** the tenant filter. Two callers, both correct.

    `launcher._run_tenant_scope` reads a run in order to open its tenant scope,
    so it cannot already be inside one; `reaper`'s sweeps run on a timer with
    no tenant acting and must see every tenant's runs or they would maintain
    tenant 1 alone. Both are in the allowlist in
    tests/test_tenant_isolation_repo.py.

    It is deliberately *not* a flag on `get_run`: an `across_tenants=False`
    parameter would make the unscoped read reachable from every existing call
    site by typo, and would not show up in a grep for the bypass. A separate,
    awkwardly-named function is one a reviewer notices.
    """
    run = session.get(Run, run_id, execution_options=ACROSS_TENANTS_OPTION)
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
