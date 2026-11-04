"""Where a run's live log lines land, and how a reader catches up.

A log line is emitted by whatever is executing the run and read back by the
portal's SSE route. P4 moved the run out of the API process, so "whatever is
executing the run" is usually a container -- and an in-process dictionary is
then the wrong place for the lines to live. It was already the wrong place for
two other reasons: a restart erased the history of every run that had ever
streamed, and only the replica that started a run could stream it.

So `LogBus` is a protocol with three implementations and **one read model**:
append a line, read forward from a cursor.

    InMemoryLogBus   the tests and a single-process API. No durability.
    PostgresLogBus   the reader's side, and any writer holding a database.
    GatewayLogBus    what a run writes through after P5-05: it has no database,
                     so its lines go to the control plane over the internal API
                     and land in `run_log` there.

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
from ..control.gateway import RunGateway
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


class GatewayLogBus:
    """A run's lines, published through the control plane rather than to a table.

    What a sandbox writes through after P5-05. It holds no `DATABASE_URL`, so it
    cannot append to `run_log` itself; it hands batches to the internal API,
    which appends them through `PostgresLogBus` on the other side. The reader is
    unchanged -- it still reads `run_log` by cursor -- so this is a change of who
    holds the connection, not of where the lines live.

    **Batched, with a background flush.** The real runner emits one line per line
    of the agent's output (app/orchestrator/claude.py), so a request per line
    would be thousands of round trips per run and would make the log the
    dominant cost of running one. Lines are buffered and flushed when the buffer
    fills or when the interval lapses, whichever comes first -- the interval is
    what keeps a *live* log live, because a run that goes quiet mid-step must not
    leave its last lines sitting in a buffer where the portal cannot see them.

    **A log line may never fail a run.** The same rule `PostgresLogBus.publish`
    states, and for the same reason: the work matters more than the view of it.
    A flush that fails is logged and its lines are dropped. Dropping rather than
    retrying for ever is deliberate -- a sandbox that cannot reach the control
    plane has a run that is about to fail on its next real operation anyway, and
    a log buffer growing without bound inside a container is its own failure.
    """

    # Enough that a chatty step is a handful of requests rather than hundreds,
    # small enough that a batch is one modest insert.
    BATCH = 100
    # The longest a line waits before a reader can see it.
    INTERVAL_S = 1.0
    # How long `close` waits for a flush already in flight. One request, so the
    # ceiling is generous rather than tuned.
    JOIN_TIMEOUT_S = 30.0

    def __init__(
        self,
        gateway: RunGateway,
        *,
        batch: int = BATCH,
        interval_s: float = INTERVAL_S,
    ) -> None:
        self._gateway = gateway
        self._batch = batch
        self._interval_s = interval_s
        self._pending: list[str] = []
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._flusher = threading.Thread(
            target=self._run_flusher, name="log-flusher", daemon=True
        )
        self._flusher.start()

    def _check(self, run_id: int) -> None:
        """Refuse a run id that is not this bus's.

        Two authorities name the run here -- the argument and the gateway's
        scope -- and `run_pipeline` guards exactly this mismatch for exactly
        this reason. Without it a line handed to the wrong bus would be
        *silently reattributed* to the scope's run, because the scope is what
        the server trusts: the argument is not sent. A log line landing on
        another run is the kind of wrong that looks like a flaky test.
        """
        if run_id != self._gateway.scope.run_id:
            raise ValueError(
                f"this log bus belongs to run {self._gateway.scope.run_id}, "
                f"not {run_id}"
            )

    def publish(self, run_id: int, line: str) -> None:
        """Buffer a line. Flushes inline once the buffer is full."""
        self._check(run_id)
        with self._lock:
            self._pending.append(line)
            full = len(self._pending) >= self._batch
        if full:
            self.flush()

    def flush(self) -> None:
        """Send whatever is buffered. Never raises."""
        with self._lock:
            batch, self._pending = self._pending, []
        if not batch:
            return
        try:
            self._gateway.publish_log(batch)
        except Exception:  # pragma: no cover - never lose a run over its log
            log.warning(
                "could not publish %d log lines for run %s; they are dropped",
                len(batch),
                self._gateway.scope.run_id,
                exc_info=True,
            )

    def _run_flusher(self) -> None:
        while not self._stop.wait(self._interval_s):
            self.flush()

    def close(self, run_id: int) -> None:
        """Stop the background thread, wait for it, then flush what is left.

        The flush is the part that matters: this runs in `drive_run`'s `finally`,
        so it is the last chance for the lines of the step that ended the run --
        which are the ones an operator reads first.

        **The join is not tidiness.** Without it, `close` raced the flusher: the
        background thread would already have taken the pending lines and be
        waiting on its request, `close`'s own flush would find an empty buffer
        and return, and the process would exit -- killing a daemon thread
        mid-request and losing the batch. The symptom was precise and
        misleading: a container path where every log line appeared except the
        last one, `=== run <key> completed ===`, which is the line an operator
        looks for first. The same reasoning as `reaper.heartbeat_during`'s
        join: what is worth waiting for is one request already in flight.

        There is nothing to *mark*, for the reason `PostgresLogBus.close` gives:
        the run's terminal status is the end-of-stream marker, and it is the only
        one a reader in another process can see.
        """
        self._check(run_id)
        self._stop.set()
        self._flusher.join(timeout=self.JOIN_TIMEOUT_S)
        self.flush()

    def is_closed(self, run_id: int) -> bool:
        """Asked by readers, and a run is not one.

        A sandbox writes its own log and never reads it back, so this exists to
        satisfy the protocol rather than to be called. It answers from the run's
        status, the same question `PostgresLogBus` answers, so a caller that does
        reach it is not told something different.
        """
        self._check(run_id)
        return is_terminal(RunStatus(self._gateway.run_status()))

    def read_from(self, run_id: int, cursor: int) -> tuple[list[str], int]:
        """Not available to a run: there is no read route, by design.

        A sandbox has no business reading back the log of any run, its own
        included -- the portal is the reader, and it reads `run_log` directly.
        Raising rather than returning nothing, because a silent empty answer
        would make a misrouted reader look like a quiet run.
        """
        raise NotImplementedError(
            "a run writes its log and does not read it back; the portal reads "
            "run_log through PostgresLogBus"
        )

    def emitter(self, run_id: int) -> Emit:
        return lambda line: self.publish(run_id, line)


# The thread path's bus: one process, one shared instance. Imported directly by
# the launcher and reset between tests.
bus = InMemoryLogBus()


def bus_from_env() -> LogBus:
    """The bus this process should use, chosen the way the runner is chosen.

    One factory, read by both ends: the launcher publishes through it and the
    API's events route reads through it, so the writer and the reader cannot
    disagree about where a run's lines are.

    `gateway` is refused rather than served. A `GatewayLogBus` needs a run's
    gateway, which this function has no way to obtain and no business minting a
    token for; the one process that uses it builds it itself
    (app/sandbox/run.py). Returning the in-process bus instead would give a
    sandbox a log nobody can read, which is worse than a startup failure naming
    the reason.
    """
    kind = config.log_bus_kind()
    if kind == "postgres":
        return PostgresLogBus()
    if kind == "gateway":
        raise ValueError(
            "QA_LOG_BUS=gateway needs a run's gateway to publish through; the "
            "sandbox entrypoint builds that bus itself (app/sandbox/run.py)"
        )
    return bus
