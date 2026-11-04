"""The Runner abstraction: how one pipeline step gets executed.

A Runner knows how to run a single step for a run and emit log lines as it goes.
The driver owns ordering, checkpointing, lease heartbeats and status; a Runner
owns only "do this one step." This split is what makes the orchestrator testable
without Claude Code (see FakeRunner).
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Protocol

from ..domain.steps import Step
from ..prompt_store import ResolvedPrompt
from ..target_config import TargetConfig

# A sink for a single log line (already newline-free).
Emit = Callable[[str], None]


@dataclass(frozen=True)
class StepContext:
    """Everything a Runner needs for one step, and nothing it has to look up.

    `worktree` arrived with P3: the tree hydrate built from the head revision,
    which is the only place the agent works. It reaches a sandboxed runner the
    same way it reaches the in-process one, which is the whole reason it travels
    in the context rather than being read from config inside the runner.

    `target` arrived with it, for the same reason and one more: `app.json` does
    not exist, so `baseURL`, `locators` and `agentNotes` have to reach the
    agent's prompt from the row, and a Runner must not need a database session
    to read them.
    """

    run_id: int
    run_key: str
    app: str            # the target's slug
    story_id: str       # e.g. SCRUM-201
    mode: str           # "changed" | "full"
    step: Step
    run_dir: Path       # per-run working dir (logs + Playwright output)
    worktree: Path      # per-run hydrated tree: the agent's working directory
    target: TargetConfig  # the row's config, rendered into the prompt
    prev_session_id: str | None  # Claude Code session to --resume, if any
    # The prompts this run was pinned to, keyed by name (P5-06). They arrive
    # here for the same reason `target` and `worktree` do: a Runner must not
    # need a database session to find what it was told to do, and in a sandbox
    # there is no session to find it with.
    #
    # Defaulted to empty so a test or a FakeRunner-driven path can build a
    # context without a prompts table behind them. A *rendering* runner needs
    # them: `claude.build_message` raises on a name it was not given rather
    # than reading the file, so empty is usable only by a runner that renders
    # no prompt. Every dispatched run arrives with its set populated --
    # `control.service.run_facts` serves the shipped defaults even for a run
    # from before the column, so there is no live path that leaves this empty.
    prompts: dict[str, ResolvedPrompt] = field(default_factory=dict)


@dataclass(frozen=True)
class StepResult:
    ok: bool
    session_id: str | None = None  # the Claude Code session id to carry forward
    error: str | None = None


class Runner(Protocol):
    def run_step(self, ctx: StepContext, emit: Emit) -> StepResult: ...
