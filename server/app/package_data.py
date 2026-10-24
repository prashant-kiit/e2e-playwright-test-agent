"""Where the code-shipped data lives, inside the installed package.

The three things P3 stopped reading off a mounted repo: the step prompts, the
agent's own Claude Code config, and the delivery templates. They are resolved
from this module's location, so an API image finds them with nothing mounted and
whatever the working directory happens to be.

It exists as its own module for two reasons. It is the **one** definition of
"where the package data is", so a future reader adding a fourth kind has an
obvious home rather than a path expression to copy. And it breaks a layering
inversion: the portal's Prompts page used to reach into
`orchestrator/claude.py` for the prompts directory, which made a page depend on
the CLI runner.

Deliberately *not* in `config.py`. That module is runtime scratch paths, all
env-overridable; these are neither. Making them configurable would be the repo
mount growing back one option at a time.
"""

from __future__ import annotations

from pathlib import Path

# server/app/package_data.py -> the installed `app` package.
PACKAGE_DIR = Path(__file__).resolve().parent


def prompts_dir() -> Path:
    """The step prompts the runner sends and the portal displays.

    Prompts move into Postgres with tenant overrides in P5 (DESIGN.md §12);
    code-shipped is this phase.
    """
    return PACKAGE_DIR / "prompts"


def runtime_dir() -> Path:
    """The agent's shipped Claude Code config: settings, MCP servers, subagents.

    Owned by the application, not the repo-root `.claude/`, which exists only
    for developing this harness.
    """
    return PACKAGE_DIR / "agent_runtime"


def templates_dir() -> Path:
    """The infra templates and the seed that delivery pushes and hydrate renders."""
    return PACKAGE_DIR / "delivery" / "templates"
