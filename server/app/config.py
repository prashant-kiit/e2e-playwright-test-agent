"""Filesystem/runtime config for the orchestrator.

The portal wraps the existing file/shell harness, so the backend needs to know
where the repo root is (apps/, prompts/, scripts/ live there) and where to put
per-run working dirs. All overridable by env for containers/tests.
"""

from __future__ import annotations

import os
from pathlib import Path

# server/app/config.py -> parents: [app, server, <repo root>]
_DEFAULT_REPO_ROOT = Path(__file__).resolve().parents[2]


def repo_root() -> Path:
    return Path(os.environ.get("QA_REPO_ROOT", str(_DEFAULT_REPO_ROOT)))


def runs_dir() -> Path:
    return Path(os.environ.get("QA_RUNS_DIR", str(repo_root() / "runs")))


def run_dir(run_key: str) -> Path:
    return runs_dir() / run_key


def runner_kind() -> str:
    """Which Runner the background orchestrator uses: 'fake' (synthetic steps,
    no tokens) or 'claude' (real, shells out to the claude CLI).

    Defaults to 'fake': the API container has no claude CLI/repo context yet
    (wired in a later milestone), and a safe default avoids accidental token
    spend. Set QA_RUNNER=claude where the CLI and repo are available."""
    return os.environ.get("QA_RUNNER", "fake").lower()


def fake_delay() -> float:
    """Seconds the FakeRunner sleeps per emitted line. 0 by default; raise it
    (e.g. QA_FAKE_DELAY=1) to make runs slow enough to pause/stop in a demo."""
    try:
        return float(os.environ.get("QA_FAKE_DELAY", "0"))
    except ValueError:
        return 0.0
