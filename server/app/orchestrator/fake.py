"""A synthetic Runner for tests, CI and token-free portal demos.

It emits a few log lines per step and writes a small placeholder artifact into
the run dir, so the whole run lifecycle (progress, checkpoints, SSE, pause/stop)
can be exercised end-to-end without spawning Claude Code. Set QA_RUNNER=fake to
use it in a live stack.

With `QA_FAKE_TREE_WRITES=1` it also writes one tracked file per step into the
worktree. Off by default, because most tests want a runner that changes nothing
-- a step that changes no tracked file commits no revision, and that is correct
behaviour worth keeping asserted. On, it makes the fake able to exercise the
*other* half of a step boundary: P4's container-path test has to prove that a
sandboxed run commits revisions, and a fake that can never produce one cannot
stand in for a run that does.
"""

from __future__ import annotations

import time

from ..domain.steps import Step
from .runner import Emit, StepContext, StepResult


class FakeRunner:
    def __init__(
        self,
        fail_on: Step | None = None,
        lines_per_step: int = 3,
        delay: float = 0.0,
        writes_tree: bool = False,
    ) -> None:
        self.fail_on = fail_on
        self.lines_per_step = lines_per_step
        self.delay = delay
        self.writes_tree = writes_tree

    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult:
        ctx.run_dir.mkdir(parents=True, exist_ok=True)
        if self.writes_tree:
            # A tracked path, so the step boundary has a tree change to commit.
            path = ctx.worktree / "tests" / "fake" / f"{ctx.step.value}.spec.ts"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(f"// fake suite for {ctx.run_key} step {ctx.step.value}\n")
        for i in range(self.lines_per_step):
            emit(f"[{ctx.step.value}] working {i + 1}/{self.lines_per_step}")
            if self.delay:
                time.sleep(self.delay)

        # Drop a placeholder artifact so later milestones have something to index.
        (ctx.run_dir / f"{ctx.step.value}.txt").write_text(
            f"fake output for {ctx.run_key} step {ctx.step.value}\n"
        )

        if self.fail_on is not None and ctx.step == self.fail_on:
            emit(f"[{ctx.step.value}] simulated failure")
            return StepResult(ok=False, error=f"fake failure at {ctx.step.value}")

        return StepResult(ok=True, session_id=f"fake-session-{ctx.run_key}")
