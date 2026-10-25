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
  - a **paused** run that still names a sandbox has it destroyed and the column
    cleared. Pause reaps immediately, with no grace window (§5), so a paused
    run's container exits at the boundary that paused it -- this is what makes
    "no sandbox is left running for a paused run" true rather than intended.

`reap_sandbox` is how a reaped run's container stops costing money. It is a
callback rather than an import because the dispatch seam imports the launcher
and the launcher imports this module; main.py passes
`sandbox.dispatch.destroy_sandbox`.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Iterator

from . import config, repo
from .db import SessionLocal
from .domain import lease
from .orchestrator.bus import prune_run_logs

log = logging.getLogger(__name__)

REAP_INTERVAL_S = 30.0
JOIN_TIMEOUT_S = 10.0


@contextlib.contextmanager
def heartbeat_during(
    run_id: int, *, interval_s: float | None = None, session_factory=SessionLocal
) -> Iterator[None]:
    """Refresh run_id's lease every interval_s for the duration of the block.

    Stops quietly once the run is no longer live -- a completed, paused or
    stopped run has no lease to keep, and that is not an error.
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
                    with session_factory() as session:
                        repo.heartbeat(session, run_id)
                except repo.RepoError:
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

    thread = threading.Thread(target=_beat, name=f"heartbeat-{run_id}", daemon=True)
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
                        await asyncio.to_thread(reap_sandbox, run_id)
                    except Exception:  # pragma: no cover - best effort by design
                        log.warning("reaping the sandbox of run %s failed", run_id)
                        continue
                    if run_id in idle:
                        # A paused run has no sandbox once this has run, and the
                        # row should say so: the stop path reads that column.
                        await asyncio.to_thread(_forget_sandbox, session_factory, run_id)
            try:
                await asyncio.to_thread(_prune_once, session_factory)
            except Exception:  # pragma: no cover - a failed prune is not an outage
                log.warning("pruning the run log failed; continuing", exc_info=True)
        except asyncio.CancelledError:
            raise
        except Exception:  # pragma: no cover - a dead reaper must not kill the API
            log.exception("reaper pass failed; continuing")


def _reap_once(session_factory=SessionLocal) -> list[int]:
    with session_factory() as session:
        return repo.reap_expired(session)


def _sweep_overdue(session_factory=SessionLocal) -> list[int]:
    with session_factory() as session:
        overdue = repo.fail_overdue_runs(session, max_age_s=config.run_timeout_s())
    if overdue:
        log.warning("failed %d run(s) past the run wall clock: %s", len(overdue), overdue)
    return overdue


def _idle_sandboxes(session_factory=SessionLocal) -> list[int]:
    with session_factory() as session:
        return repo.idle_sandbox_runs(session)


def _forget_sandbox(session_factory=SessionLocal, run_id: int = 0) -> None:
    with session_factory() as session:
        repo.set_sandbox_handle(session, run_id, None)


def _prune_once(session_factory=SessionLocal) -> int:
    with session_factory() as session:
        pruned = prune_run_logs(session)
    if pruned:
        log.info("pruned %d run_log row(s) past the retention window", pruned)
    return pruned
