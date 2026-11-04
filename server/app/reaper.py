"""Background lease maintenance: the heartbeat and the reaper.

app/repo.py has had `heartbeat()` and `reap_expired()` since M1, both tested,
but nothing ever called them: the only reaping happened opportunistically inside
`start_run`. With a 60 s TTL and the lease refreshed only at step boundaries,
any step longer than a minute ran with an expired lease -- so a healthy run
looked dead to the next starter, and a genuinely dead run held its app until
someone tried to start another.

Two pieces fix that:
  - `heartbeat_during()` keeps a live run's lease fresh while a step runs;
  - `reaper_loop()` frees apps held by runs that really did die.

A PAUSED run deliberately holds its lock with no lease, and repo.reap_expired
already skips it; nothing here changes that.

P4 hung two more pieces of maintenance on the same loop, both sweeps *beside*
the reap rather than inside it -- a failed sweep must never stop a dead run's
lock from being freed:

  - the live log is a Postgres table now (DESIGN.md §10) and its rows are pruned
    past a retention window;
  - a run past the per-run wall clock is failed with that reason (§6). That is
    the reaper's half of the limit: a run whose sandbox is gone has nobody left
    to check its own deadline, and `app/orchestrator/limits.py` is the half that
    stops a run still being driven from starting another step;
  - a **paused or finished** run that still names a sandbox has it destroyed
    and the column cleared. For a paused run this is a net: pause reaps
    immediately, with no grace window (§5), so a handle still on a paused row
    means that did not happen -- an API that died mid-pause, or a pause that
    raced a dispatch. For a *finished* run it is the only mechanism there is.
    The run container carries `AutoRemove` and vanishes on its own, but the
    run's **egress proxy** is long-running and exits on nobody's schedule, and
    the process that finished the run is inside the sandbox, has no Docker
    socket by design, and needs that proxy alive until its last step. Without
    this sweep every completed run leaves an idle proxy behind for ever.

`reap_sandbox` is how a reaped run's container stops costing money. It is a
callback rather than an import because the dispatch seam imports the launcher
and the launcher imports this module; main.py passes
`sandbox.dispatch.destroy_sandbox`.
"""

from __future__ import annotations

import asyncio
import contextlib
import contextvars
import logging
import threading
from collections.abc import Callable, Iterator

from sqlalchemy.orm import Session

from . import config, repo
from .control.service import ControlPlaneError
from .db import SessionLocal
from .domain import lease
from .orchestrator.bus import prune_run_logs
from .tenancy import tenant_scope

log = logging.getLogger(__name__)

# One maintenance sweep, run inside a tenant's scope: it is handed a session
# and returns the run ids it acted on.
Sweep = Callable[[Session], list[int]]

REAP_INTERVAL_S = 30.0
JOIN_TIMEOUT_S = 10.0


@contextlib.contextmanager
def heartbeat_during(
    run_id: int,
    beat: Callable[[], None],
    *,
    interval_s: float | None = None,
) -> Iterator[None]:
    """Call `beat` every interval_s for the duration of the block.

    Stops quietly once the run is no longer live -- a completed, paused or
    stopped run has no lease to keep, and that is not an error.

    **P5-05 made the beat a callable rather than a session factory.** The thing
    doing the work may be a sandbox with no database, so what refreshes the
    lease is one of its gateway's operations (`control.heartbeat`); on the thread
    path that is the same `repo.heartbeat` as before, reached through the same
    gateway. `run_id` stays a parameter because every log line in here names it,
    and a heartbeat thread that cannot say which run it failed for is the one
    that caused the outage this function's comments are about.

    `ControlPlaneError` is what "no longer live" arrives as now -- the gateway's
    translation of the service's refusal -- and `repo.RepoError` is what it was.
    Both are treated as "nothing to keep alive", because on the thread path a
    `LocalGateway` raises the first wrapping the second.
    """
    # DEFAULT_HEARTBEAT is a timedelta (the lease module is time arithmetic);
    # Event.wait takes seconds. Passing the timedelta straight through raised
    # TypeError from `done.wait(period)` -- *outside* the loop's try -- so this
    # daemon thread died on its first iteration without a sound, the lease was
    # never refreshed, and every step longer than the 60 s TTL got its healthy
    # run reaped. Which is every step of a real agent run.
    period = (
        interval_s if interval_s is not None else lease.DEFAULT_HEARTBEAT.total_seconds()
    )
    done = threading.Event()

    def _beat() -> None:
        # The whole loop is guarded, the wait included: a heartbeat thread that
        # dies costs a healthy run its lease, so it must never do so quietly.
        try:
            while not done.wait(period):
                try:
                    beat()
                except (repo.RepoError, ControlPlaneError):
                    return  # no longer live: nothing to keep alive
                except Exception:  # pragma: no cover - never kill a run over a heartbeat
                    log.warning("heartbeat failed for run %s", run_id, exc_info=True)
        except Exception:
            log.error(
                "heartbeat thread for run %s died; its lease will now expire and the "
                "run will be reaped while still healthy",
                run_id,
                exc_info=True,
            )

    # The thread beats inside *this* caller's context, which is what carries
    # the tenant scope across the thread boundary (P5-11). `threading.Thread`
    # does not: a bare thread starts with an empty context, so the beat
    # resolved the tenant with nothing bound. That was invisible while the
    # resolver answered the seeded default and wrong in the worst way -- every
    # run heartbeated as tenant 1, so for any other tenant `repo.heartbeat`
    # read its run through the tenant filter, found nothing, and the loop read
    # that `NotFound` as "no longer live" and returned. The lease then expired
    # under a perfectly healthy run and the reaper reaped it. `copy_context()`
    # is the thread-boundary equivalent of what `asyncio.to_thread` already
    # does for the sweeps above.
    context = contextvars.copy_context()
    thread = threading.Thread(
        target=lambda: context.run(_beat), name=f"heartbeat-{run_id}", daemon=True
    )
    thread.start()
    try:
        yield
    finally:
        done.set()
        # Wait for an in-flight beat to finish, not just for the interval: the
        # thread checks `done` as soon as its wait returns, so the only thing
        # worth waiting on is one database round-trip. Returning while it still
        # holds a session leaves a connection idle-in-transaction, which blocks
        # anything that needs a table lock.
        thread.join(timeout=JOIN_TIMEOUT_S)


async def reaper_loop(
    *,
    interval_s: float = REAP_INTERVAL_S,
    session_factory=SessionLocal,
    on_reap: Callable[[list[int]], None] | None = None,
    reap_sandbox: Callable[[int], object] | None = None,
) -> None:
    """Fail runs whose lease has expired or whose wall clock ran out, forever."""
    while True:
        try:
            await asyncio.sleep(interval_s)
            reaped = await asyncio.to_thread(_reap_once, session_factory)
            if reaped:
                log.warning("reaped %d run(s) with expired leases: %s", len(reaped), reaped)
                if on_reap is not None:
                    on_reap(reaped)
            # Beside the reap, never inside it: housekeeping must not be able to
            # keep a dead run's app locked.
            try:
                overdue = await asyncio.to_thread(_sweep_overdue, session_factory)
            except Exception:  # pragma: no cover - a failed sweep is not an outage
                log.warning("sweeping overdue runs failed; continuing", exc_info=True)
                overdue = []
            if reap_sandbox is not None:
                # A container still burning minutes for a run that has failed or
                # been parked is the cost these limits exist to stop.
                idle = await asyncio.to_thread(_idle_sandboxes, session_factory)
                for run_id in list(reaped) + overdue + idle:
                    try:
                        # Both steps run as the run's own tenant: each reads the
                        # run row, and a filtered read outside its tenant finds
                        # nothing (see `_tenant_of`). The scope is a ContextVar
                        # and `asyncio.to_thread` copies the context, so binding
                        # it here reaches the worker thread.
                        tenant_id = await asyncio.to_thread(
                            _tenant_of, session_factory, run_id
                        )
                        with tenant_scope(tenant_id):
                            await asyncio.to_thread(reap_sandbox, run_id)
                            if run_id in idle:
                                # A paused or finished run has no sandbox once
                                # this has run, and the row should say so: the
                                # stop path reads that column, and a handle left
                                # on the row would make the next sweep do this
                                # all over again.
                                await asyncio.to_thread(
                                    _forget_sandbox, session_factory, run_id
                                )
                    except Exception:  # pragma: no cover - best effort by design
                        log.warning("reaping the sandbox of run %s failed", run_id)
                        continue
            try:
                await asyncio.to_thread(_prune_once, session_factory)
            except Exception:  # pragma: no cover - a failed prune is not an outage
                log.warning("pruning the run log failed; continuing", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a dead reaper must not kill the API
            log.exception("reaper pass failed; continuing")


def _for_each_tenant(session_factory, sweep: Sweep) -> list[int]:
    """Run one sweep once per tenant, each inside that tenant's scope.

    The shape every maintenance pass takes once reads are filtered by tenant
    (P5-02). The reaper has no request and no run behind it, so
    `current_tenant_id()` answers the seeded default: a sweep that just queried
    would maintain tenant 1 and silently leave every other customer's crashed
    runs holding their apps, reporting a clean pass each time round.

    Binding each tenant in turn is deliberately preferred to reading across
    tenants once. These sweeps are not single queries -- `reap_expired` reads
    locks, then each lock's run, then frees it -- so an unfiltered outer query
    would need every nested read opted out too, and the opt-out would then be
    the normal case in the one module whose job is to touch every tenant's
    rows. Here each pass is ordinary scoped work, and the only thing that knows
    about tenants is this loop.

    **One tenant's failure does not stop the others.** The reaper is what frees
    an app lock, so a single tenant with a wedged row must not be able to park
    every other tenant's apps indefinitely -- a noisy neighbour holding a
    control, not just a resource. Each tenant is logged and skipped on its own.
    """
    with session_factory() as session:
        tenant_ids = repo.list_tenant_ids(session)
    swept: list[int] = []
    for tenant_id in tenant_ids:
        try:
            with tenant_scope(tenant_id), session_factory() as session:
                swept.extend(sweep(session))
        except Exception:
            # Not `pragma: no cover` -- unlike the best-effort handlers below,
            # this branch is the point of the surrounding docstring and
            # test_reaper.py drives it.
            log.warning(
                "a maintenance sweep failed for tenant %s; continuing with the "
                "remaining tenants",
                tenant_id,
                exc_info=True,
            )
    return swept


def _reap_once(session_factory=SessionLocal) -> list[int]:
    return _for_each_tenant(session_factory, repo.reap_expired)


def _sweep_overdue(session_factory=SessionLocal) -> list[int]:
    overdue = _for_each_tenant(
        session_factory,
        lambda session: repo.fail_overdue_runs(
            session, max_age_s=config.run_timeout_s()
        ),
    )
    if overdue:
        log.warning("failed %d run(s) past the run wall clock: %s", len(overdue), overdue)
    return overdue


def _idle_sandboxes(session_factory=SessionLocal) -> list[int]:
    return _for_each_tenant(session_factory, repo.idle_sandbox_runs)


def _tenant_of(session_factory, run_id: int) -> int:
    """Which tenant owns this run. The reaper's single cross-tenant read.

    The sweeps above collect run ids across every tenant, and what is done with
    them afterwards -- destroying a sandbox, clearing its handle -- reads the
    run row again, through code that is right to be filtered
    (`dispatch.destroy_sandbox` calls `repo.get_run`). Outside a scope those
    reads would find nothing for any run but tenant 1's, so a reaped run
    elsewhere would keep its container and its handle: money burning on a
    container nobody will look for again, which is the one thing P4's limits
    exist to stop.

    A plain function rather than a context manager wrapping the scope, so the
    **query** can go through `asyncio.to_thread` like every other database call
    in `reaper_loop` while the caller holds the scope. A context manager would
    have had to open its session on the event loop, which is the one thing this
    loop is careful never to do.
    """
    with session_factory() as session:
        return repo.get_run_across_tenants(session, run_id).tenant_id


def _forget_sandbox(session_factory, run_id: int) -> None:
    """A run has no sandbox once its container is gone; the row says so.

    Both arguments required: a default `run_id` here would be a sentinel that
    silently cleared nothing, and the other helpers' `session_factory` default
    exists only because the loop may be called without one.
    """
    with session_factory() as session:
        repo.set_sandbox_handle(session, run_id, None)


def _prune_once(session_factory=SessionLocal) -> int:
    with session_factory() as session:
        pruned = prune_run_logs(session)
    if pruned:
        log.info("pruned %d run_log row(s) past the retention window", pruned)
    return pruned
