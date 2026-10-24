"""Runtime paths for the orchestrator: where a run works and where it writes.

A target's configuration lives in Postgres and its tree lives in blobs, so what
is left here is **scratch space** -- the per-run worktree hydrated from the
database, the per-run directory its output goes to, and the shared npm cache.
All overridable by env for containers and tests.

There is no `repo_root()`. P3 deleted it with the mount: no code path may
quietly reacquire a dependency on a shared disk, which a structural test now
keeps true (tests/test_no_repo_mount.py). What used to resolve through it --
`apps/`, `prompts/`, the agent runtime -- is either a row, a blob, or package
data shipped inside the server package.
"""

from __future__ import annotations

import os
from pathlib import Path

# Scratch defaults, used when nothing is configured. Deliberately not derived
# from this file's location: a path relative to the installed package is a
# plausible-looking way to reacquire "somewhere on the host we all share".
DEFAULT_RUNS_DIR = "/tmp/qa-runs"
DEFAULT_WORKTREES_DIR = "/tmp/qa-worktrees"
DEFAULT_NPM_CACHE = "/tmp/qa-npm-cache"


def runs_dir() -> Path:
    """Where per-run output goes: logs, Playwright results, the session log."""
    return Path(os.environ.get("QA_RUNS_DIR", DEFAULT_RUNS_DIR))


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
    return Path(os.environ.get("QA_WORKTREES_DIR", DEFAULT_WORKTREES_DIR))


def worktree_dir(run_key: str) -> Path:
    """One run's worktree. Hydrated before the pipeline, deleted after it."""
    return worktrees_dir() / run_key


def npm_cache_dir() -> Path:
    """A shared npm cache, so each run's install is not a cold download.

    P4 replaces the install step with a prebaked image and a warm cache; until
    then this is the warm half.
    """
    return Path(os.environ.get("QA_NPM_CACHE", DEFAULT_NPM_CACHE))


def runner_kind() -> str:
    """Which Runner the background orchestrator uses: 'fake' (synthetic steps,
    no tokens) or 'claude' (real, shells out to the claude CLI).

    Defaults to 'fake': a safe default avoids accidental token spend, and the
    API image does not ship the claude CLI (P4's prebaked sandbox image does).
    Set QA_RUNNER=claude where the CLI and node are available.
    """
    return os.environ.get("QA_RUNNER", "fake").lower()


def fake_delay() -> float:
    """Seconds the FakeRunner sleeps per emitted line. 0 by default; raise it
    (e.g. QA_FAKE_DELAY=1) to make runs slow enough to pause/stop in a demo."""
    try:
        return float(os.environ.get("QA_FAKE_DELAY", "0"))
    except ValueError:
        return 0.0
