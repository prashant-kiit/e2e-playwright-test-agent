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

P4 hung one more piece of maintenance on the same loop: the live log is a
Postgres table now (DESIGN.md §10), and its rows are pruned past a retention
window here. It is a sweep beside the reap, not inside it -- a failed prune must
never stop a dead run's lock from being freed.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import threading
from collections.abc import Callable, Iterator

from . import repo
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
) -> None:
    """Fail runs whose lease has expired and free their apps, forever."""
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


def _prune_once(session_factory=SessionLocal) -> int:
    with session_factory() as session:
        pruned = prune_run_logs(session)
    if pruned:
        log.info("pruned %d run_log row(s) past the retention window", pruned)
    return pruned
