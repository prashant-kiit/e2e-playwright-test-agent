"""The Runner abstraction: how one pipeline step gets executed.

A Runner knows how to run a single step for a run and emit log lines as it goes.
The driver owns ordering, checkpointing, lease heartbeats and status; a Runner
owns only "do this one step." This split is what makes the orchestrator testable
without Claude Code (see FakeRunner).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Protocol

from ..domain.steps import Step

# A sink for a single log line (already newline-free).
Emit = Callable[[str], None]


@dataclass(frozen=True)
class StepContext:
    run_id: int
    run_key: str
    app: str            # apps/<app> folder name
    story_id: str       # e.g. SCRUM-201
    mode: str           # "changed" | "full"
    step: Step
    run_dir: Path       # per-run working dir (logs + Playwright output)
    prev_session_id: str | None  # Claude Code session to --resume, if any


@dataclass(frozen=True)
class StepResult:
    ok: bool
    session_id: str | None = None  # the Claude Code session id to carry forward
    error: str | None = None


class Runner(Protocol):
    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult: ...
