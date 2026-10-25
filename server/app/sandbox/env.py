"""The environment a sandbox is given: one function, an explicit list.

In the sandbox environment:

    DATABASE_URL          hydrate reads the head revision; ingest commits N+1
    S3_*                  blobs in, blobs out, artifacts up
    ANTHROPIC_API_KEY     the model the agent talks to
    the scratch paths, the runner kind, the limits, the proxy

Never in the sandbox:

    GITHUB_PAT            or any GitHub credential
    QA_ADMIN_PASSWORD     or any portal credential
    a repo mount          or any path into the control plane
    the control plane's own configuration

**Built from a list, never copied from `os.environ`.** The difference is what
happens to the control-plane variable somebody adds next year: a copy with a
deny list ships it to the sandbox until somebody remembers, and a list does not
ship it at all. That is the whole structural argument, and
tests/test_sandbox_credentials.py is what keeps it true.

**The store credentials are accepted exposure for this phase, deliberately.**
§6's credential rule is specifically about GitHub, and for a stated reason:
delivery is human-approved and happens in the control plane, so the push need
not happen where the agent is. Hydrate and ingest *are* the run, so they do need
the stores. Routing them through a narrow, run-scoped internal API is the right
long-term answer and the wrong thing to bundle into this phase -- it belongs with
P5's tenant-scoped reads, where the token that authorizes one run's target is
the same mechanism that authorizes one tenant's data. Recorded in DESIGN.md §6
so P5 inherits a decision rather than a surprise.

The agent runtime's telemetry and error reporting are **disabled here** rather
than allowlisted in the proxy, so the allowlist stays the length of what a run
genuinely needs (app/sandbox/egress.py).
"""

from __future__ import annotations

import os

from .. import config
from ..target_config import TargetConfig

# Where the sandbox keeps the agent's own CLI state. It has to be a path the
# session archive can be taken from and restored into (app/sandbox/session.py):
# `--resume` works today only because the CLI's store happens to sit on the host
# that started the run, and a container destroyed on pause takes it with it.
CLAUDE_CONFIG_DIR = "/data/claude-config"

# Scratch inside the container. Named here rather than inherited from the API's
# own values: the API's paths are its volume's, and a sandbox has its own
# filesystem that is destroyed with it.
RUNS_DIR = "/data/runs"
WORKTREES_DIR = "/data/worktrees"
# The cache the image baked from the template lockfile (docker/Dockerfile.sandbox).
# Not a shared volume: a writable cache mounted into every sandbox would be a
# supply-chain path between containers running different customers' agents,
# which is what container-per-run exists to close. Warm *and* per-run, because
# it is in the image and written to only in the container's own layer.
NPM_CACHE = "/npm-cache"

# Hosts the sandbox reaches without the proxy, because they are on its own
# internal network: the stores it hydrates from and ingests to.
NO_PROXY_HOSTS = ("localhost", "127.0.0.1")


def _from_control_plane(name: str, default: str = "") -> str:
    """One named value out of this process's environment.

    Every read of the control plane's environment goes through here, so the list
    of what a sandbox inherits is the list of calls to this function.
    """
    return os.environ.get(name, default)


def store_environment() -> dict[str, str]:
    """The narrowest set hydrate and ingest need: the database and the blobs."""
    return {
        "DATABASE_URL": _from_control_plane(
            "DATABASE_URL", "postgresql+psycopg://qa:qa@postgres:5432/qa"
        ),
        "S3_ENDPOINT": _from_control_plane("S3_ENDPOINT", "http://seaweedfs:8333"),
        "S3_ACCESS_KEY": _from_control_plane("S3_ACCESS_KEY", "qa"),
        "S3_SECRET_KEY": _from_control_plane("S3_SECRET_KEY", "qa-secret"),
        "S3_BUCKET": _from_control_plane("S3_BUCKET", "qa-artifacts"),
    }


def telemetry_off() -> dict[str, str]:
    """The agent runtime's telemetry, error reporting and auto-update, off.

    Disabled rather than allowlisted: every host this saves is a host the
    allowlist would otherwise have to carry for every run of every tenant.
    """
    return {
        "DISABLE_TELEMETRY": "1",
        "DISABLE_ERROR_REPORTING": "1",
        "DISABLE_AUTOUPDATER": "1",
        "DISABLE_NON_ESSENTIAL_MODEL_CALLS": "1",
        "CLAUDE_CODE_ENABLE_TELEMETRY": "0",
    }


def proxy_environment(proxy_url: str, *, no_proxy: tuple[str, ...] = ()) -> dict[str, str]:
    """Point npm, the CLI and Playwright at the allowlisting proxy.

    The proxy is not how egress is *enforced* -- the sandbox network has no
    default route, so there is nothing to opt out of (app/sandbox/proxy.py).
    These variables are how the clients find the only way out, which is why an
    agent unsetting them reaches nothing rather than reaching everything.

    `QA_PROXY_URL` is read by the generated `playwright.config.ts`, which is
    rendered from the target's row and has exactly one author -- the natural
    place for a proxy stanza, and one more reason not to reintroduce a
    hand-maintained copy of that file.
    """
    hosts = ",".join(NO_PROXY_HOSTS + no_proxy)
    return {
        "HTTP_PROXY": proxy_url,
        "HTTPS_PROXY": proxy_url,
        "http_proxy": proxy_url,
        "https_proxy": proxy_url,
        "NO_PROXY": hosts,
        "no_proxy": hosts,
        "QA_PROXY_URL": proxy_url,
    }


def sandbox_environment(
    run_id: int,
    cfg: TargetConfig,
    *,
    proxy_url: str | None = None,
    no_proxy: tuple[str, ...] = (),
) -> dict[str, str]:
    """Everything one sandbox is given, and nothing else.

    `cfg` is the target's configuration: it is a parameter because a sandbox
    holds exactly one target's tree, and because the proxy's allowlist is built
    from the same row (app/sandbox/egress.py).
    """
    env: dict[str, str] = {
        **store_environment(),
        "ANTHROPIC_API_KEY": _from_control_plane("ANTHROPIC_API_KEY"),
        # The run's own identity, for the log lines the runtime emits. The run
        # id the entrypoint works on is an argument, not an environment
        # variable: a container with the wrong id in its environment and the
        # right one on its command line is a confusion worth not having.
        "QA_RUN_ID": str(run_id),
        "QA_APP": cfg.app,
        "QA_RUNS_DIR": RUNS_DIR,
        "QA_WORKTREES_DIR": WORKTREES_DIR,
        "QA_NPM_CACHE": NPM_CACHE,
        "QA_RUNNER": config.runner_kind(),
        "QA_FAKE_DELAY": str(config.fake_delay()),
        "QA_FAKE_TREE_WRITES": "1" if config.fake_tree_writes() else "0",
        # It cannot publish into the API's memory, and it is not the process
        # that chose the dispatch, so it is told rather than left to infer.
        "QA_LOG_BUS": "postgres",
        "QA_STEP_TIMEOUT_S": str(config.step_timeout_s()),
        "QA_RUN_TIMEOUT_S": str(config.run_timeout_s()),
        "QA_SPEND_BUDGET_USD": str(config.spend_budget_usd()),
        "CLAUDE_CONFIG_DIR": CLAUDE_CONFIG_DIR,
        **telemetry_off(),
    }
    if proxy_url:
        env.update(proxy_environment(proxy_url, no_proxy=no_proxy))
    return {name: str(value) for name, value in env.items() if value != ""}
