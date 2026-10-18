"""An in-memory pub/sub for live run log lines.

The driver publishes lines as steps run; SSE subscribers (the portal) receive
them. A small per-run history lets a late subscriber catch up on what already
scrolled past. This is live-streaming only; the durable log is the run dir on
disk (and, later, the stored artifacts). A single-process dev backend, so an
in-memory bus is enough.
"""

from __future__ import annotations

import queue
import threading
from collections import defaultdict

# Sentinel put on a subscriber queue when a run's stream is finished.
DONE = None


class LogBus:
    def __init__(self, history: int = 1000) -> None:
        self._subs: dict[int, set[queue.Queue]] = defaultdict(set)
        self._history: dict[int, list[str]] = defaultdict(list)
        self._lock = threading.Lock()
        self._max = history

    def publish(self, run_id: int, line: str) -> None:
        with self._lock:
            h = self._history[run_id]
            h.append(line)
            if len(h) > self._max:
                del h[: len(h) - self._max]
            subs = list(self._subs[run_id])
        for q in subs:
            q.put(line)

    def close(self, run_id: int) -> None:
        """Signal end-of-stream to current subscribers."""
        with self._lock:
            subs = list(self._subs[run_id])
        for q in subs:
            q.put(DONE)

    def subscribe(self, run_id: int) -> tuple[queue.Queue, list[str]]:
        """Return a live queue plus a snapshot of history to replay first."""
        q: queue.Queue = queue.Queue()
        with self._lock:
            history = list(self._history[run_id])
            self._subs[run_id].add(q)
        return q, history

    def unsubscribe(self, run_id: int, q: queue.Queue) -> None:
        with self._lock:
            self._subs[run_id].discard(q)

    def emitter(self, run_id: int):
        """A plain Emit callable bound to a run (what the driver is given)."""
        return lambda line: self.publish(run_id, line)

    def reset(self) -> None:
        """Drop all subscribers and history (used by tests)."""
        with self._lock:
            self._subs.clear()
            self._history.clear()


# Single process -> one shared bus.
bus = LogBus()
