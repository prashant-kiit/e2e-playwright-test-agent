"""Run status and the legal transitions between statuses.

A run moves through these statuses. Pause and stop are *requests* (booleans on
the run) that the orchestrator honours at a step boundary; the resulting status
change must be a legal transition here.

    PENDING --start--> RUNNING --all steps done--> COMPLETED (terminal)
    RUNNING <--resume-- PAUSED <--pause-- RUNNING
    RUNNING / PAUSED --stop--> STOPPED (terminal)
    PENDING / RUNNING / PAUSED --error or lease reaped--> FAILED (terminal)
"""

from __future__ import annotations

from enum import Enum


class RunStatus(str, Enum):
    PENDING = "pending"      # created, lock held, not yet started
    RUNNING = "running"      # orchestrator actively working a step
    PAUSED = "paused"        # halted at a step boundary, resumable
    COMPLETED = "completed"  # all steps finished (terminal)
    STOPPED = "stopped"      # stopped by the operator (terminal)
    FAILED = "failed"        # errored or reaped after a dead lease (terminal)


TERMINAL: frozenset[RunStatus] = frozenset(
    {RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}
)

# A live run holds its app lock; terminal runs release it.
LIVE: frozenset[RunStatus] = frozenset(
    {RunStatus.PENDING, RunStatus.RUNNING, RunStatus.PAUSED}
)

_ALLOWED: dict[RunStatus, frozenset[RunStatus]] = {
    RunStatus.PENDING: frozenset({RunStatus.RUNNING, RunStatus.FAILED, RunStatus.STOPPED}),
    RunStatus.RUNNING: frozenset(
        {RunStatus.PAUSED, RunStatus.COMPLETED, RunStatus.STOPPED, RunStatus.FAILED}
    ),
    RunStatus.PAUSED: frozenset({RunStatus.RUNNING, RunStatus.STOPPED, RunStatus.FAILED}),
    RunStatus.COMPLETED: frozenset(),
    RunStatus.STOPPED: frozenset(),
    RunStatus.FAILED: frozenset(),
}


def is_terminal(status: RunStatus) -> bool:
    return status in TERMINAL


def is_live(status: RunStatus) -> bool:
    return status in LIVE


def can_transition(frm: RunStatus, to: RunStatus) -> bool:
    return to in _ALLOWED[frm]


class IllegalTransition(ValueError):
    def __init__(self, frm: RunStatus, to: RunStatus) -> None:
        super().__init__(f"illegal run status transition: {frm.value} -> {to.value}")
        self.frm = frm
        self.to = to


def assert_transition(frm: RunStatus, to: RunStatus) -> None:
    """Raise IllegalTransition unless frm -> to is allowed."""
    if not can_transition(frm, to):
        raise IllegalTransition(frm, to)
