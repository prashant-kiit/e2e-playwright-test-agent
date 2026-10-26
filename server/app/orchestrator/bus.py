"""Where a run's live log lines land, and how a reader catches up.

A log line is emitted by whatever is executing the run and read back by the
portal's SSE route. P4 moved the run out of the API process, so "whatever is
executing the run" is usually a container -- and an in-process dictionary is
then the wrong place for the lines to live. It was already the wrong place for
two other reasons: a restart erased the history of every run that had ever
streamed, and only the replica that started a run could stream it.

So `LogBus` is a protocol with two implementations and **one read model**: append
a line, read forward from a cursor.

    InMemoryLogBus   the thread path and the tests. One process, no durability.
    PostgresLogBus   anything out of process. `run_log`, read by cursor.

`Emit` does not change shape (see runner.py): the driver, the runners and the
step-boundary hook hand lines to a plain callable and know nothing about where
they go. That constraint is what made this a change of destination rather than a
change of the pipeline.

**One writer per run**, which is whatever is executing it. The API never
publishes on behalf of a run it does not execute, which is why the sequence
number can be counted in the writer rather than looked up per line.

The rows are the live view and its recent history, **not the archive**:
`session.jsonl` remains the durable per-run record (DESIGN.md §10), and the
reaper prunes `run_log` past a retention window (`prune_run_logs`) so a
convenience does not become unbounded growth.
"""

from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta
from typing import Protocol

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError

from .. import config
from ..db import SessionLocal
from ..domain import lease
from ..domain.status import RunStatus, is_terminal
from ..models import Run, RunLog
from ..tenancy import current_tenant_id
from .runner import Emit

log = logging.getLogger(__name__)

class LogBus(Protocol):
    """Append lines for a run; read them back from a cursor.

    A cursor is an opaque integer a reader carries between calls. It is only
    ever compared and never computed by the reader, so an implementation is free
    to make it a sequence number (both of these do).
    """

    def publish(self, run_id: int, line: str) -> None: ...

    def close(self, run_id: int) -> None:
        """Mark the run's stream finished, for a reader waiting on more."""

    def is_closed(self, run_id: int) -> bool:
        """Whether a reader may stop waiting: the stream will get no more lines."""

    def read_from(self, run_id: int, cursor: int) -> tuple[list[str], int]:
        """The lines after `cursor`, and the cursor to pass next time."""

    def emitter(self, run_id: int) -> Emit: ...


class InMemoryLogBus:
    """One process, no durability: the thread path and the tests.

    Kept deliberately. It is what lets the existing suite prove the pipeline did
    not move when P4 moved where it runs, and it keeps CI from needing a database
    for a log line. Its only legitimate differences from the Postgres-backed one
    are durability and reach.
    """

    def __init__(self, history: int = 1000) -> None:
        self._lines: dict[int, list[str]] = {}
        self._dropped: dict[int, int] = {}
        self._closed: set[int] = set()
        self._lock = threading.Lock()
        self._max = history

    def publish(self, run_id: int, line: str) -> None:
        with self._lock:
            lines = self._lines.setdefault(run_id, [])
            lines.append(line)
            # Evicting the oldest lines keeps a long-lived dev process bounded.
            # The count of what was dropped is kept, so a cursor stays monotonic
            # and a reader is never handed a line twice.
            if len(lines) > self._max:
                shed = len(lines) - self._max
                del lines[:shed]
                self._dropped[run_id] = self._dropped.get(run_id, 0) + shed

    def close(self, run_id: int) -> None:
        with self._lock:
            self._closed.add(run_id)

    def is_closed(self, run_id: int) -> bool:
        with self._lock:
            return run_id in self._closed

    def read_from(self, run_id: int, cursor: int) -> tuple[list[str], int]:
        with self._lock:
            lines = self._lines.get(run_id, [])
            dropped = self._dropped.get(run_id, 0)
            start = max(cursor - dropped, 0)
            return list(lines[start:]), dropped + len(lines)

    def emitter(self, run_id: int) -> Emit:
        return lambda line: self.publish(run_id, line)

    def reset(self) -> None:
        """Drop all history (used by tests)."""
        with self._lock:
            self._lines.clear()
            self._dropped.clear()
            self._closed.clear()


class PostgresLogBus:
    """`run_log`, appended as lines are emitted and read back by cursor.

    What the table buys: a late subscriber gets the run's real history rather
    than one process's snapshot, that history survives a restart, and any
    replica can stream any run.

    The sequence number is counted in this object rather than read per line,
    because there is one writer per run. A second writer would lose the insert on
    the primary key, which is the right outcome -- and the retry below exists for
    the one legitimate case, a resumed run whose predecessor is still exiting.
    """

    def __init__(self, *, session_factory=SessionLocal) -> None:
        self._session_factory = session_factory
        self._next: dict[int, int] = {}
        self._lock = threading.Lock()

    def publish(self, run_id: int, line: str) -> None:
        # A log line must never fail a run: the work matters more than the view
        # of it, exactly as a missed heartbeat must not kill a healthy run.
        try:
            self._append(run_id, line)
        except Exception:  # pragma: no cover - never kill a run over a log line
            log.warning("could not append a log line for run %s", run_id, exc_info=True)

    def _append(self, run_id: int, line: str) -> None:
        for attempt in (1, 2):
            seq = self._claim_seq(run_id)
            try:
                with self._session_factory() as session:
                    session.add(
                        RunLog(
                            tenant_id=current_tenant_id(),
                            run_id=run_id,
                            seq=seq,
                            line=line,
                        )
                    )
                    session.commit()
                return
            except IntegrityError:
                # Somebody else holds that seq. Re-read the real tail and retry
                # once; a second collision is a second writer, which is a bug
                # worth seeing rather than looping over.
                with self._lock:
                    self._next.pop(run_id, None)
                if attempt == 2:
                    raise

    def _claim_seq(self, run_id: int) -> int:
        with self._lock:
            seq = self._next.get(run_id)
            if seq is None:
                seq = self._tail(run_id) + 1
            self._next[run_id] = seq + 1
            return seq

    def _tail(self, run_id: int) -> int:
        with self._session_factory() as session:
            return (
                session.scalar(
                    select(func.max(RunLog.seq)).where(
                        RunLog.run_id == run_id,
                        RunLog.tenant_id == current_tenant_id(),
                    )
                )
                or 0
            )

    def close(self, run_id: int) -> None:
        """Nothing to write. A Postgres-backed stream ends when the run does.

        The run's terminal status is the end-of-stream marker, and it is the only
        one that works for a reader in another process -- a sentinel row would be
        a second way to say the same thing, readable only after the row that
        already says it.
        """

    def is_closed(self, run_id: int) -> bool:
        with self._session_factory() as session:
            run = session.get(Run, run_id)
        if run is None:
            return True  # nothing left to wait for
        return is_terminal(run.status) or run.status is RunStatus.PAUSED

    def read_from(self, run_id: int, cursor: int) -> tuple[list[str], int]:
        with self._session_factory() as session:
            rows = list(
                session.execute(
                    select(RunLog.seq, RunLog.line)
                    .where(
                        RunLog.run_id == run_id,
                        RunLog.seq > cursor,
                        RunLog.tenant_id == current_tenant_id(),
                    )
                    .order_by(RunLog.seq)
                )
            )
        if not rows:
            return [], cursor
        return [line for _seq, line in rows], rows[-1][0]

    def emitter(self, run_id: int) -> Emit:
        return lambda line: self.publish(run_id, line)


def prune_run_logs(session, *, days: int | None = None, now: datetime | None = None) -> int:
    """Delete log lines older than the retention window. Returns the row count.

    Called by the reaper loop. The live view's convenience is not an archive, and
    an append-only table nobody prunes is the slowest kind of outage.
    """
    window = timedelta(days=config.log_retention_days() if days is None else days)
    cutoff = (now or lease.utcnow()) - window
    result = session.execute(delete(RunLog).where(RunLog.at < cutoff))
    session.commit()
    return result.rowcount or 0


# The thread path's bus: one process, one shared instance. Imported directly by
# the launcher and reset between tests.
bus = InMemoryLogBus()


def bus_from_env() -> LogBus:
    """The bus this process should use, chosen the way the runner is chosen.

    One factory, read by both ends: the launcher publishes through it and the
    API's events route reads through it, so the writer and the reader cannot
    disagree about where a run's lines are.
    """
    if config.log_bus_kind() == "postgres":
        return PostgresLogBus()
    return bus
