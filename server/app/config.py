"""Runtime paths for the orchestrator: where a run works and where it writes.

A target's configuration lives in Postgres and its tree lives in blobs, so what
is left here is scratch space -- the per-run worktree hydrated from the database,
the per-run directory its output goes to, and the shared npm cache. All
overridable by env for containers and tests.

`repo_root()` is on its way out with the mount (P3-08); while it is here it
serves only the cutover and the two P2 revision routes.
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


def worktrees_dir() -> Path:
    """Where per-run worktrees live: a **sibling** of the runs dir, never inside it.

    Artifact collection sweeps the run dir recursively (artifacts.py), so a
    worktree under it would upload the whole source tree and `node_modules` as
    run artifacts on every step boundary. Siblings keep "what the agent works
    in" and "what we collect as evidence" structurally separate rather than
    separated by an exclusion list somebody has to remember.
    """
    return Path(os.environ.get("QA_WORKTREES_DIR", str(runs_dir().parent / "worktrees")))


def worktree_dir(run_key: str) -> Path:
    """One run's worktree. Hydrated before the pipeline, deleted after it."""
    return worktrees_dir() / run_key


def npm_cache_dir() -> Path:
    """A shared npm cache, so each run's install is not a cold download.

    P4 replaces the install step with a prebaked image and a warm cache; until
    then this is the warm half.
    """
    return Path(os.environ.get("QA_NPM_CACHE", str(worktrees_dir().parent / "npm-cache")))


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
