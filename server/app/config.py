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


def sandbox_kind() -> str:
    """How a run starts working: 'docker' (a container per run) or 'thread'.

    The mirror of `runner_kind`, and read by the same kind of factory: the
    launcher seam picks an implementation from here rather than growing a second
    injection point (DESIGN.md §13).

    Defaults to 'thread' -- today's behaviour -- so tests, CI and a bare
    development process need no container. The compose stack sets 'docker'.
    """
    return os.environ.get("QA_SANDBOX", "thread").lower()


def log_bus_kind() -> str:
    """Where live log lines go: 'postgres', 'memory', or 'gateway' in a sandbox.

    It **follows the dispatch kind** rather than being a second thing to
    configure: a run in a container cannot publish into the API's memory, and a
    run on a thread has no reason to need a database for a log line. The
    override exists for the sandbox entrypoint, which sets it explicitly because
    it is not the process that chose the dispatch.

    P5-05 added the third value. A sandbox has no database, so it cannot append
    to `run_log` itself: it publishes through its run's gateway and the control
    plane appends on its behalf (`GatewayLogBus`). The value is informational
    for that process -- the entrypoint builds its own bus, because a gateway is
    not something `bus_from_env` could conjure -- and `bus_from_env` refuses it
    rather than silently handing back an in-process dictionary whose lines
    nobody would ever read.
    """
    explicit = os.environ.get("QA_LOG_BUS", "").strip().lower()
    if explicit:
        return explicit
    return "postgres" if sandbox_kind() == "docker" else "memory"


# The limits P4 puts around a run (DESIGN.md §6, "Quotas and timeouts"). Each
# is configurable with a sane default, and each breach is a `failed` run with an
# explicit reason and the last committed revision intact -- never a silent kill.
#
# The defaults are deliberately generous rather than tight: the failure mode
# being bounded is a wedged agent holding a browser open for hours, and a limit
# that interrupts healthy work is a limit an operator turns off.
DEFAULT_STEP_TIMEOUT_S = 1800.0      # 30 minutes for one step
DEFAULT_RUN_TIMEOUT_S = 7200.0       # two hours for the whole run
DEFAULT_SPEND_BUDGET_USD = 20.0      # per run, from the CLI's own cost reports


def _positive_float(name: str, default: float) -> float:
    """An env-configured limit. A value that is not a positive number is the
    default rather than an outage: a typo in a limit must not wedge every run,
    and 0 is how somebody would try to spell "no limit" -- which this is not."""
    try:
        value = float(os.environ.get(name, default))
    except ValueError:
        return default
    return value if value > 0 else default


def step_timeout_s() -> float:
    """Wall clock for one step, enforced by the runner around the CLI."""
    return _positive_float("QA_STEP_TIMEOUT_S", DEFAULT_STEP_TIMEOUT_S)


def run_timeout_s() -> float:
    """Wall clock for a whole run, checked at step boundaries and by the reaper."""
    return _positive_float("QA_RUN_TIMEOUT_S", DEFAULT_RUN_TIMEOUT_S)


def spend_budget_usd() -> float:
    """What one run may cost before it is ended, from the `result` events the
    runner already parses."""
    return _positive_float("QA_SPEND_BUDGET_USD", DEFAULT_SPEND_BUDGET_USD)


def fake_tree_writes() -> bool:
    """Whether the FakeRunner also writes a tracked file per step.

    Off by default: most tests want a runner that changes nothing, because a
    step that changes no tracked file must commit no revision. The
    container-path integration test turns it on, so a synthetic run exercises
    ingest as well as the log and the artifacts.
    """
    return os.environ.get("QA_FAKE_TREE_WRITES", "0") not in ("0", "", "false")


def log_retention_days() -> int:
    """How long a run's live log lines stay readable before the reaper prunes.

    It bounds the *live view's* history, not the audit trail: `session.jsonl` is
    the durable per-run record (DESIGN.md §10). Seven days matches §9's
    reaped-snapshot retention, so an operator reviewing last week's incident
    finds both halves or neither.
    """
    try:
        return int(os.environ.get("QA_LOG_RETENTION_DAYS", "7"))
    except ValueError:
        return 7


def fake_delay() -> float:
    """Seconds the FakeRunner sleeps per emitted line. 0 by default; raise it
    (e.g. QA_FAKE_DELAY=1) to make runs slow enough to pause/stop in a demo."""
    try:
        return float(os.environ.get("QA_FAKE_DELAY", "0"))
    except ValueError:
        return 0.0


# --- what kind of deployment this is -------------------------------------
#
# One signal, read by the two things that must behave differently in
# development: the session cookies' `Secure` flag (app/auth.py) and the
# envelope's local key fallback (app/envelope.py). They are the same question
# -- "is this a real deployment?" -- so they are one variable rather than two.

DEFAULT_ENV = "prod"


def is_dev_deployment() -> bool:
    """True only for `QA_ENV=dev`. **Everything else is a deployment.**

    The default is `prod`, and the asymmetry is deliberate. The two callers
    both guard a customer credential: one decides whether a 30-day refresh
    cookie may travel over plain HTTP, the other whether the key that decrypts
    every stored PAT may be derived from a well-known constant. For both, the
    cost of reading an unset or misspelled variable as "development" is a live
    credential exposure, and the cost of reading it as "deployment" is a
    developer who sets `QA_ENV=dev` once. So only the exact word opts out --
    `devv`, `staging` and `""` are all deployments.

    The dev stack says so explicitly (`docker-compose.yml`), and so does the
    test suite (`tests/conftest.py`), for the same reason: the insecure branch
    should be reachable only on purpose.
    """
    return os.environ.get("QA_ENV", DEFAULT_ENV).strip().lower() == "dev"


# --- the keys this deployment signs with ---------------------------------
#
# Here because three modules need to know what they are and a review found
# them disagreeing: `app/auth.py` defaulted `QA_SECRET_KEY` to
# `dev-secret-change-me`, `app/run_token.py` layered `QA_RUN_TOKEN_KEY` over
# the same default, and `app/envelope.py`'s "the two keys must differ" guard
# re-derived the first with a default of `""`. So with `QA_SECRET_KEY` unset --
# every dev stack -- `QA_ENVELOPE_KEY=dev-secret-change-me` *was* the cookie
# signing key, and the guard compared it to the empty string and allowed it.
# That is the arrangement follow-up 21 exists to prevent, in the configuration
# whose refusal is documented in three places.
#
# The lesson is the one this codebase keeps relearning: a value known in two
# places is a value that will disagree in one of them. These are the one place.

DEV_SECRET_KEY = "dev-secret-change-me"


def secret_key() -> str:
    """The key the portal signs session cookies with (`app/auth.py`).

    Falls back to a well-known development value, which is why
    `envelope.wrapper_from_env` must compare against *this* rather than
    against a bare `os.environ.get`: the fallback is a real key that really
    signs cookies, not an absence.
    """
    return os.environ.get("QA_SECRET_KEY", DEV_SECRET_KEY)


def run_token_key() -> str:
    """The key run-scoped sandbox tokens are signed with (`app/run_token.py`).

    `QA_RUN_TOKEN_KEY` where a deployment wants the two separated, else the
    portal's own key -- unchanged behaviour, moved here so there is one answer
    to "what is actually signing run tokens".
    """
    return os.environ.get("QA_RUN_TOKEN_KEY") or secret_key()


def cookies_secure() -> bool:
    """Whether the session cookies carry `Secure` (app/auth.py).

    Its own function rather than `not is_dev_deployment()` at the call site, so
    the cookie contract reads as a contract and this file stays the one place
    that knows what `QA_ENV` means.

    Note that development over `http://localhost` does not actually need this
    to be false -- browsers treat localhost as a secure context and accept
    `Secure` cookies there. It is false in development for the cases that are
    not localhost: a stack reached over a LAN address or a tunnel on plain
    HTTP, and a test client that is not a browser at all.
    """
    return not is_dev_deployment()
