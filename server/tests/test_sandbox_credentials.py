"""No GitHub credential ever enters a sandbox, and this is what keeps it out.

§6's credential rule is the one P4 makes structural. The agent explores the
customer's live web app, so page content can carry prompt injection into a
session that writes and executes TypeScript; a PAT inside that blast radius is
an exfiltration path to a customer's repository. Delivery is a separate,
human-approved control-plane action (§7), so the push does not need to happen
where the agent is -- and after this phase it cannot.

Structural tests, in the style of test_no_repo_mount.py, because the guarantee
is about what *cannot* happen rather than about what did. A behavioural test
passes for as long as nobody adds the variable.

The store credentials are **accepted exposure for this phase, deliberately**:
hydrate and ingest are the run, so they need the stores. Routing them through a
narrow, run-scoped internal API is P5's, where the token that authorizes one
run's target is the same mechanism that authorizes one tenant's data. That
decision is recorded in DESIGN.md §6 rather than left to be rediscovered, and
the test below pins the *shape* of the exposure so it cannot quietly grow.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from app.sandbox import env as sandbox_env
from app.target_config import TargetConfig
from tests.source_helpers import code_lines, code_of

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent

# Everything that would let a sandbox write to a customer's repository or act as
# the portal. Named individually rather than by prefix: a list is readable, and
# a prefix rule would quietly stop covering a credential named differently.
FORBIDDEN = ("GITHUB_PAT", "GITHUB_TOKEN", "GH_TOKEN", "QA_ADMIN_PASSWORD", "QA_SECRET_KEY")


@pytest.fixture()
def cfg():
    return TargetConfig(
        app="demo",
        name="Demo",
        base_url="https://shop.example.com",
        locators="",
        agent_notes=(),
        target_repo="o/r",
        target_branch="master",
    )


@pytest.fixture(autouse=True)
def _control_plane_environment(monkeypatch):
    """The API's own environment, as the thing building a sandbox env sees it."""
    for name in FORBIDDEN:
        monkeypatch.setenv(name, f"secret-{name.lower()}")
    monkeypatch.setenv("DATABASE_URL", "postgresql+psycopg://qa:qa@postgres:5432/qa")
    monkeypatch.setenv("S3_ENDPOINT", "http://seaweedfs:8333")
    monkeypatch.setenv("S3_ACCESS_KEY", "qa")
    monkeypatch.setenv("S3_SECRET_KEY", "qa-secret")
    monkeypatch.setenv("S3_BUCKET", "qa-artifacts")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "sk-ant-test")
    monkeypatch.setenv("QA_CORS_ORIGINS", "http://localhost:5173")


# --- one function builds the environment ---------------------------------

def test_the_sandbox_environment_carries_what_hydrate_and_ingest_need(cfg):
    env = sandbox_env.sandbox_environment(7, cfg)

    assert env["DATABASE_URL"] == "postgresql+psycopg://qa:qa@postgres:5432/qa"
    assert env["S3_ENDPOINT"] == "http://seaweedfs:8333"
    assert env["S3_ACCESS_KEY"] == "qa"
    assert env["S3_SECRET_KEY"] == "qa-secret"
    assert env["S3_BUCKET"] == "qa-artifacts"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"


def test_the_sandbox_environment_carries_the_scratch_paths_and_the_runner_kind(cfg):
    env = sandbox_env.sandbox_environment(7, cfg)

    assert env["QA_RUNS_DIR"]
    assert env["QA_WORKTREES_DIR"]
    assert env["QA_NPM_CACHE"]
    assert env["QA_RUNNER"] in ("fake", "claude")


def test_the_sandbox_writes_its_log_to_postgres(cfg):
    """It cannot publish into the API's memory, and the entrypoint is not the
    process that chose the dispatch, so it is told explicitly."""
    assert sandbox_env.sandbox_environment(7, cfg)["QA_LOG_BUS"] == "postgres"


@pytest.mark.parametrize("name", FORBIDDEN)
def test_no_github_or_portal_credential_reaches_the_sandbox(cfg, name):
    env = sandbox_env.sandbox_environment(7, cfg)
    assert name not in env


def test_no_value_of_a_forbidden_credential_reaches_the_sandbox_under_another_name(cfg):
    """A rename is the way this guarantee would actually be lost."""
    env = sandbox_env.sandbox_environment(7, cfg)
    secrets = {f"secret-{name.lower()}" for name in FORBIDDEN}
    leaked = {key: value for key, value in env.items() if value in secrets}
    assert leaked == {}


def test_the_environment_is_built_from_a_list_rather_than_copied(cfg):
    """`os.environ` is never the starting point: a control-plane variable added
    next year must not arrive in a sandbox because nobody updated a deny list."""
    env = sandbox_env.sandbox_environment(7, cfg)
    assert "QA_CORS_ORIGINS" not in env
    assert "QA_SANDBOX" not in env
    source = Path(sandbox_env.__file__).read_text()
    assert "**os.environ" not in source
    assert "dict(os.environ" not in source
    assert "os.environ.copy" not in source


def test_the_agent_runtimes_telemetry_and_error_reporting_are_disabled(cfg):
    """Disabled by environment rather than allowlisted, so the allowlist stays
    the length of what a run genuinely needs."""
    env = sandbox_env.sandbox_environment(7, cfg)
    assert env["DISABLE_TELEMETRY"] == "1"
    assert env["DISABLE_ERROR_REPORTING"] == "1"
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "0"
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_every_value_is_a_string_a_container_can_take(cfg):
    env = sandbox_env.sandbox_environment(7, cfg)
    assert all(isinstance(k, str) and isinstance(v, str) for k, v in env.items())


# --- nothing the sandbox runs can even read a GitHub credential ----------

def _modules_reachable_from_the_entrypoint() -> list[str]:
    """The `app.*` modules importing the entrypoint actually loads.

    A fresh interpreter, because this process has the whole suite imported.
    """
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            "import app.sandbox.run, json, sys;"
            "print(json.dumps(sorted(m for m in sys.modules if m.startswith('app'))))",
        ],
        cwd=str(SERVER_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, proc.stderr
    return json.loads(proc.stdout)


def test_the_entrypoint_imports_a_recognisable_slice_of_the_package():
    """A pass because the import graph came back empty would be the worst
    outcome here."""
    modules = _modules_reachable_from_the_entrypoint()
    assert "app.launcher" in modules
    assert "app.sandbox.hydrate" in modules
    assert "app.orchestrator.driver" in modules


@pytest.mark.parametrize("credential", ("GITHUB_PAT", "GITHUB_TOKEN", "GH_TOKEN"))
def test_no_module_reachable_from_the_entrypoint_reads_a_github_credential(credential):
    """The structural half of the credential rule.

    The sandbox image ships the same server package as the API, so the delivery
    *code* exists in it -- what must not exist is a path from the entrypoint to
    the one function that reads a token. `app/delivery/__init__.py` therefore
    exposes its entry points lazily: wanting the tracked-tree definition does
    not import the credential reader.
    """
    offenders = []
    for module in _modules_reachable_from_the_entrypoint():
        path = SERVER_DIR / (module.replace(".", "/") + ".py")
        if not path.is_file():
            path = SERVER_DIR / module.replace(".", "/") / "__init__.py"
        if path.is_file() and credential in code_of(path):
            offenders.append(module)
    assert offenders == [], (
        f"{offenders} are reachable from the sandbox entrypoint and mention "
        f"{credential}; no GitHub credential may be readable from a sandbox"
    )


def test_the_delivery_entry_points_are_still_importable_from_the_package():
    """The lazy re-export has to stay a re-export: the control plane imports
    these by name and a typo in the lazy map would be found at runtime."""
    import app.delivery as delivery

    for name in delivery.__all__:
        assert getattr(delivery, name) is not None, name


# --- the image and its service ------------------------------------------

def _dockerfile() -> str:
    return (REPO_ROOT / "docker" / "Dockerfile.sandbox").read_text()


def _compose() -> dict:
    import yaml

    return yaml.safe_load((REPO_ROOT / "docker-compose.yml").read_text())


def test_the_sandbox_image_builds_from_the_same_server_package_as_the_api():
    """So the prompts, the agent runtime and the tracked-tree definition cannot
    disagree between the thing serving HTTP and the thing running agents."""
    dockerfile = _dockerfile()
    assert "COPY server/app ./app" in dockerfile
    assert "server/pyproject.toml" in dockerfile
    assert "uv sync" in dockerfile


def test_the_sandbox_image_carries_the_cli_node_and_the_browsers():
    dockerfile = _dockerfile()
    assert "@anthropic-ai/claude-code" in dockerfile
    assert "nodejs" in dockerfile
    assert "playwright install" in dockerfile


def test_the_sandbox_image_installs_the_browsers_at_build_time():
    """A run starts without downloading one: time-to-first-step in seconds."""
    dockerfile = _dockerfile()
    assert "RUN npm install -g \"playwright@${PLAYWRIGHT_VERSION}\"" in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH" in dockerfile


def test_the_prebaked_browser_version_matches_the_revisions_lockfile():
    """The one failure that silently undoes "no download at run time": `npm ci`
    from the lockfile fetching a browser build the image does not hold."""
    import json
    import re

    lock = json.loads(
        (SERVER_DIR / "app" / "delivery" / "templates" / "package-lock.json").read_text()
    )
    pinned = lock["packages"]["node_modules/@playwright/test"]["version"]
    baked = re.search(r"ARG PLAYWRIGHT_VERSION=([\d.]+)", _dockerfile()).group(1)
    assert baked == pinned


def test_the_sandbox_image_declares_no_repo_mount():
    """P3's guarantee is not reacquired through a volume."""
    dockerfile = code_lines(_dockerfile())
    assert "VOLUME" not in dockerfile
    assert "/workspace" not in dockerfile
    assert "QA_REPO_ROOT" not in dockerfile


def test_the_sandbox_image_has_no_git_to_push_with():
    """Structural rather than procedural: the credential rule says the push
    cannot happen here, and there is no binary here to push with."""
    dockerfile = _dockerfile()
    assert "git" not in dockerfile.replace("GITHUB", "").lower().split("# ")[0]
    install_lines = [
        line for line in dockerfile.splitlines() if "apt-get install" in line
    ]
    assert install_lines, "the image installs something, so the check means something"
    assert not any(" git" in line for line in install_lines)


def test_the_sandbox_image_declares_no_credential():
    dockerfile = _dockerfile()
    for name in FORBIDDEN:
        assert name not in code_lines(dockerfile), name


def test_the_api_image_no_longer_carries_node_or_the_cli():
    """The thing that serves HTTP stops having to be the thing that runs
    agents, and the two are versioned separately."""
    dockerfile = (REPO_ROOT / "docker" / "Dockerfile.server").read_text()
    assert "claude-code" not in code_lines(dockerfile)
    assert "nodejs" not in code_lines(dockerfile)
    assert "playwright" not in code_lines(dockerfile).lower()


def test_the_compose_sandbox_service_mounts_nothing_and_carries_no_credential():
    sandbox = _compose()["services"]["sandbox"]

    assert "volumes" not in sandbox, "a sandbox holds one target's tree and nothing else"
    assert "environment" not in sandbox, "its environment is built per run, from a list"
    for credential in FORBIDDEN:
        assert credential not in str(sandbox), credential


def test_no_compose_service_carries_a_github_or_portal_credential():
    services = _compose()["services"]
    for name, service in services.items():
        rendered = str(service.get("environment", "")) + str(service.get("env_file", ""))
        for credential in FORBIDDEN:
            assert credential not in rendered, f"{name} carries {credential}"


def test_the_sandbox_image_is_built_but_never_started_by_the_stack():
    """There is no long-lived sandbox service: a container per run is the
    phase. The service exists so one `make up` builds the image."""
    sandbox = _compose()["services"]["sandbox"]
    assert sandbox["profiles"] == ["never-started"]
    assert sandbox["build"]["dockerfile"] == "docker/Dockerfile.sandbox"
