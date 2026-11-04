"""The environment a sandbox is given: one function, an explicit list.

In the sandbox environment:

    QA_RUN_TOKEN          one run, one target, one tenant -- and nothing else
    QA_CONTROL_PLANE_URL  where the internal API answering for that token is
    ANTHROPIC_API_KEY     the model the agent talks to
    the scratch paths, the runner kind, the limits, the proxy

Never in the sandbox:

    DATABASE_URL          removed by P5-05. A sandbox used to hold the control
                          plane's own database credential, which is to say read
                          and write access to every tenant's rows, and was
                          trusted not to use it
    S3_*                  removed by P5-05 as well: the same thing for every
                          tenant's blobs
    a GitHub credential   there is no longer a `GITHUB_PAT` anywhere; a tenant's
                          PAT lives sealed on its target's row, and the sandbox
                          is handed a `TargetConfig`, which has no field for one
    QA_SECRET_KEY         the session-cookie signing key, or any portal
                          credential. It is also what run tokens are signed
                          with, so a sandbox holding it could mint a token for
                          any run of any tenant
    QA_ENVELOPE_KEY       where no cloud KMS is configured, the key that would
                          unwrap every tenant's sealed PAT. A sandbox holds
                          ciphertext it can do nothing with, and this is the one
                          value that would change that. It used to be
                          `QA_SECRET_KEY`'s second job; the follow-up 21 fix
                          split them
    QA_KMS_KEY_ID         the sandbox has no business naming the wrapping key
    a repo mount          or any path into the control plane
    the control plane's own configuration

**Built from a list, never copied from `os.environ`.** The difference is what
happens to the control-plane variable somebody adds next year: a copy with a
deny list ships it to the sandbox until somebody remembers, and a list does not
ship it at all. That is the whole structural argument, and
tests/test_sandbox_credentials.py is what keeps it true.

**The store credentials are gone, which is what P5-05 is.** P4 recorded them as
accepted exposure with a stated plan: §6's credential rule was about GitHub,
because delivery is human-approved and happens in the control plane, while
hydrate and ingest *are* the run and so needed the stores. The answer that note
promised was a narrow, run-scoped internal API, and this is it -- the token that
authorizes one run's target is the same mechanism that authorizes one tenant's
data (app/run_token.py, app/control/service.py).

What the sandbox carries instead is a token and a URL. Neither is a credential
for anything but one live run: the token names one run, one target and one
tenant, it is refused the moment that run stops being live, and the URL answers
only for the run the token names.

The agent runtime's telemetry and error reporting are **disabled here** rather
than allowlisted in the proxy, so the allowlist stays the length of what a run
genuinely needs (app/sandbox/egress.py).
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

from .. import config
from ..control import factory
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

# Hosts a sandbox always reaches without the proxy: its own loopback. The
# *control plane* is added to this per run by `internal_hosts`, derived from the
# URL the sandbox is actually given rather than listed here, so a stack whose
# API is somewhere else does not need this file edited. Before P5-05 the stores
# were what went here; they are not reachable from a sandbox at all now.
LOOPBACK_HOSTS = ("localhost", "127.0.0.1")


def _from_control_plane(name: str, default: str = "") -> str:
    """One named value out of this process's environment.

    Every read of the control plane's environment goes through here, so the list
    of what a sandbox inherits is the list of calls to this function.
    """
    return os.environ.get(name, default)


def control_plane_environment(run_token: str) -> dict[str, str]:
    """Where the control plane is, and the token this run presents to it.

    The replacement for `store_environment`, and the shape of the replacement is
    the point: two values, one of which is a URL and the other of which expires
    with this run. There is no credential here for an agent to exfiltrate that
    is worth anything to anybody tomorrow.

    The URL is the control plane's **internal** address -- the API on the
    sandbox's own network, not the portal's public hostname -- because that is
    the only address a sandbox can reach, and `internal_hosts` keeps it off the
    proxy for the same reason the stores were kept off it.
    """
    return {
        factory.CONTROL_PLANE_URL: _from_control_plane(
            factory.CONTROL_PLANE_URL, "http://api:8000"
        ),
        factory.RUN_TOKEN: run_token,
    }


def internal_hosts(control_plane: dict[str, str]) -> tuple[str, ...]:
    """The hosts the sandbox reaches **directly**, on its own internal network.

    This exists because of a trap: `HTTP_PROXY` is honoured by more clients than
    the ones it is set for. Before P5-05 the client in question was boto3, which
    tunnelled `http://seaweedfs:8333` to the allowlisting proxy -- which refused
    it, correctly, because the object store was deliberately not on the egress
    allowlist. The client is `httpx` now and the host is the control plane's, but
    the trap is identical: with a proxy configured and nothing in `NO_PROXY`,
    every call a run makes to the internal API would be tunnelled to a proxy
    whose whole job is to refuse things that are not the target.

    So the control plane bypasses the proxy rather than being allowlisted
    through it. A proxy that could reach the control plane's internal API would
    be a proxy worth attacking -- the same argument that kept the stores off the
    allowlist, now protecting the thing that replaced them.

    **This is also where the stores stopped being reachable.** The sandbox used
    to be given their endpoints, and this function derived their hostnames from
    what it was given; it is given the control plane's URL now and nothing else,
    so there is no store hostname for a sandbox to resolve, in `NO_PROXY` or out
    of it. The hosts are still *derived* from the endpoints the sandbox was
    handed, so a stack whose API is somewhere else does not need this file
    edited.
    """
    hosts: list[str] = []
    for value in (control_plane.get(factory.CONTROL_PLANE_URL, ""),):
        host = urlparse(value).hostname if value else None
        if host and host not in hosts:
            hosts.append(host)
    return tuple(hosts)


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


def proxy_environment(proxy_url: str, *, direct: tuple[str, ...] = ()) -> dict[str, str]:
    """Point npm, the CLI and Playwright at the allowlisting proxy.

    The proxy is not how egress is *enforced* -- the sandbox network has no
    default route, so there is nothing to opt out of (app/sandbox/proxy.py).
    These variables are how the clients find the only way out, which is why an
    agent unsetting them reaches nothing rather than reaching everything.

    `QA_PROXY_URL` is read by the generated `playwright.config.ts`, which is
    rendered from the target's row and has exactly one author -- the natural
    place for a proxy stanza, and one more reason not to reintroduce a
    hand-maintained copy of that file.

    `direct` is what must **not** go through it: the control plane's internal
    API, on the sandbox's own network (see `internal_hosts`). Both spellings of
    every variable, because the clients that read them disagree about case.
    """
    hosts = ",".join(LOOPBACK_HOSTS + direct)
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
    run_token: str,
    *,
    proxy_url: str | None = None,
) -> dict[str, str]:
    """Everything one sandbox is given, and nothing else.

    `cfg` is the target's configuration: it is a parameter because a sandbox
    holds exactly one target's tree, and because the proxy's allowlist is built
    from the same row (app/sandbox/egress.py).

    `run_token` is a **required positional** parameter, deliberately. It is the
    whole of the sandbox's authority, and a default -- or a keyword with a
    fallback to the environment -- would let a caller build an environment with
    no authority in it and find out one hydrate later. There is nothing sensible
    to default it to: minting needs the signing key and the run's row
    (app/control/factory.py).
    """
    control_plane = control_plane_environment(run_token)
    env: dict[str, str] = {
        **control_plane,
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
        # It cannot publish into the API's memory and it has no database to
        # append to, so its lines go to the control plane; it is not the process
        # that chose the dispatch, so it is told rather than left to infer.
        "QA_LOG_BUS": "gateway",
        "QA_STEP_TIMEOUT_S": str(config.step_timeout_s()),
        "QA_RUN_TIMEOUT_S": str(config.run_timeout_s()),
        "QA_SPEND_BUDGET_USD": str(config.spend_budget_usd()),
        "CLAUDE_CONFIG_DIR": CLAUDE_CONFIG_DIR,
        **telemetry_off(),
    }
    if proxy_url:
        env.update(
            proxy_environment(proxy_url, direct=internal_hosts(control_plane))
        )
    return {name: str(value) for name, value in env.items() if value != ""}
