"""Prompts, settings, and the optional infra sync.

What is left of a module that used to read apps/<app>/: the portal's Prompts
page, the Settings page, and the "sync infra to the target repo" step the
new-target form offers. A target's configuration is a row (app/target_config.py),
its stories are revision content (app/authoring.py), and neither is a file this
module can read any more.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import config
from .orchestrator.claude import prompts_dir


def read_prompts() -> list[dict]:
    """Every prompt the agent can be given, for the portal's Prompts page.

    Read from package data -- the same directory the runner reads -- so what the
    portal shows is what the agent is actually sent. Prompts move into Postgres
    with tenant overrides in P5 (DESIGN.md §12).
    """
    root = prompts_dir()
    files: list[Path] = []
    overview = root / "qa_system_prompt.md"
    if overview.exists():
        files.append(overview)
    steps = root / "steps"
    if steps.exists():
        files.extend(sorted(steps.glob("*.md")))
    return [
        {"name": p.relative_to(root).as_posix(), "content": p.read_text()} for p in files
    ]


def settings() -> dict:
    """What the Settings page shows.

    There is no repo root here. P3 removed the shared authoritative mount, and a
    UI that still reported one would be describing a disk that does not exist --
    the runs dir and the worktrees dir are per-run scratch, which is what is
    left.
    """
    return {
        "runner": config.runner_kind(),
        "fake_delay": config.fake_delay(),
        "runs_dir": str(config.runs_dir()),
        "worktrees_dir": str(config.worktrees_dir()),
        "model": os.environ.get("ANTHROPIC_MODEL") or os.environ.get("CLAUDE_MODEL") or "default",
        "anthropic_api_key_set": bool(os.environ.get("ANTHROPIC_API_KEY")),
    }


@dataclass(frozen=True)
class BootstrapOutcome:
    """The portal-facing result of the optional infra sync.

    A DeliveryError is an outcome, not a server error, so the new-target form
    can report a failed sync next to the target it did create.
    """

    ok: bool
    output: str


def run_bootstrap(app: str, *, tools=None) -> BootstrapOutcome:
    """Push the infra entries to the target repo, through app/delivery.

    `tools` is the delivery seam; left unset it is built from the environment.
    Tests pass one backed by a bare repo on disk, so this needs neither network
    nor credentials.
    """
    from .delivery import DeliveryError, bootstrap_target

    try:
        result = bootstrap_target(app, tools=tools)
    except DeliveryError as exc:
        return BootstrapOutcome(ok=False, output=str(exc))
    lines = [
        f"Target: {result.repo} ({result.branch})",
        *([result.changes.strip()] if result.changes.strip() else []),
        result.message,
    ]
    return BootstrapOutcome(ok=True, output="\n".join(lines))
