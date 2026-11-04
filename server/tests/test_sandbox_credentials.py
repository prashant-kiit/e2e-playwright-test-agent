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

**P5-05 closed the last of it.** P4 recorded the store credentials as accepted
exposure with a stated plan, and the tests below are now the other end of that
note: a sandbox carries neither `DATABASE_URL` nor the `S3_*` credentials, and
what it carries instead is a run-scoped token (app/run_token.py) that authorizes
one run of one target of one tenant and stops working when that run does.

The shape of the remaining exposure is worth stating, because it is not nothing:
a sandbox can do, for the life of its run, exactly what its own run could always
do -- read its target's head revision, write its target's next one, upload its
own artifacts, append to its own log. What it can no longer do is read any other
tenant's rows or blobs, which is what `DATABASE_URL` let it do for as long as it
held one.
"""

from __future__ import annotations

import json
import re
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
FORBIDDEN = (
    "GITHUB_PAT",
    "GITHUB_TOKEN",
    "GH_TOKEN",
    "QA_ADMIN_PASSWORD",
    # Since P5-05, what run tokens are signed with. A sandbox holding it could
    # mint itself a token for any run of any tenant, which would undo the whole
    # of this phase in one variable.
    #
    # It was *also* the wrapping key for every tenant's sealed PAT until the
    # follow-up 21 fix, which moved that job to `QA_ENVELOPE_KEY` -- so what
    # this entry guards is now narrower, and there is a second entry below for
    # the other half. Both are still forbidden, for different reasons.
    "QA_SECRET_KEY",
    "QA_RUN_TOKEN_KEY",
    # The wrapping key for every tenant's sealed PAT (`envelope.LocalKeyWrapper`
    # derives from it). A sandbox holds sealed ciphertext it can do nothing
    # with, which is the property the envelope buys; this key is precisely what
    # would turn that back into a readable credential. Forbidden in compose for
    # the same reason as `QA_SECRET_KEY`: a real deployment supplies it through
    # its own secret mechanism rather than a file in the repository, and a dev
    # stack needs no value at all (`QA_ENV=dev` falls back to
    # `envelope.DEV_ENVELOPE_KEY`).
    "QA_ENVELOPE_KEY",
)

# The store credentials P5-05 removed. Kept as their own list rather than folded
# into FORBIDDEN above, because that list is also applied to every compose
# service -- and the API, the reaper and the migrations are all *supposed* to
# have these. What must not have them is a sandbox.
FORBIDDEN_IN_A_SANDBOX = (
    "DATABASE_URL",
    "S3_ENDPOINT",
    "S3_ACCESS_KEY",
    "S3_SECRET_KEY",
    "S3_BUCKET",
)

# `QA_KMS_KEY_ID` is deliberately **not** in that list. It is a key *identifier*,
# not a credential -- what authorises its use is the deployment's IAM grant --
# and the list above is also applied to every compose service, so including it
# would forbid the API from being configured with the key it needs. That a
# sandbox does not get it is asserted directly instead, in
# `test_no_sealed_credential_or_wrapping_key_reaches_the_sandbox`.


@pytest.fixture()
def run_token(monkeypatch):
    """A real minted token, because that is what a real sandbox is handed.

    Minted rather than faked: `sandbox_environment` takes it as a required
    positional argument, and a test passing a placeholder string would not
    notice if the thing being put in a container stopped being a token.
    """
    from app import run_token as tokens

    monkeypatch.setenv("QA_SECRET_KEY", "the-suite-signing-key")
    return tokens.mint(tokens.RunScope(run_id=7, target_id=3, tenant_id=42))


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
    monkeypatch.setenv("AWS_SECRET_ACCESS_KEY", "aws-secret")


# --- one function builds the environment ---------------------------------

def test_the_sandbox_environment_carries_a_token_and_where_to_present_it(
    cfg, run_token
):
    """What replaced the stores: one token, one URL.

    This is the acceptance criterion in one assertion -- a sandbox's whole
    authority over Postgres and the blob store is a string that expires with its
    run.
    """
    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    assert env["QA_RUN_TOKEN"] == run_token
    assert env["QA_CONTROL_PLANE_URL"] == "http://api:8000"
    assert env["ANTHROPIC_API_KEY"] == "sk-ant-test"


@pytest.mark.parametrize("name", FORBIDDEN_IN_A_SANDBOX)
def test_no_store_credential_reaches_the_sandbox(cfg, run_token, name):
    """P5-05's first acceptance criterion, as a structural test.

    The control plane's environment has all of these (the fixture above puts
    them there, as the API really does), and none of them comes out.
    """
    assert name not in sandbox_env.sandbox_environment(7, cfg, run_token)


def test_no_value_of_a_store_credential_reaches_the_sandbox_under_another_name(
    cfg, run_token
):
    """The rename guard, applied to the credentials this ticket removed: the way
    this would actually be lost is somebody passing the same connection string
    along under a name the list above does not mention."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
    values = {
        "postgresql+psycopg://qa:qa@postgres:5432/qa",
        "http://seaweedfs:8333",
        "qa-secret",
        "qa-artifacts",
    }

    assert {k: v for k, v in env.items() if v in values} == {}


def test_the_token_is_a_real_run_token_and_says_only_what_it_should(cfg, run_token):
    """It carries one run, one target and one tenant -- and the sandbox cannot
    change any of them, because it does not hold the signing key."""
    from app import run_token as tokens

    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    scope = tokens.verify(env["QA_RUN_TOKEN"])
    assert (scope.run_id, scope.target_id, scope.tenant_id) == (7, 3, 42)


def test_the_sandbox_environment_carries_the_scratch_paths_and_the_runner_kind(
    cfg, run_token
):
    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    assert env["QA_RUNS_DIR"]
    assert env["QA_WORKTREES_DIR"]
    assert env["QA_NPM_CACHE"]
    assert env["QA_RUNNER"] in ("fake", "claude")


def test_the_sandbox_writes_its_log_through_the_control_plane(cfg, run_token):
    """It cannot publish into the API's memory, and after P5-05 it has no
    database to append to either -- so its lines go to the control plane, which
    appends them on its behalf. The entrypoint is not the process that chose the
    dispatch, so it is told explicitly."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    assert env["QA_LOG_BUS"] == "gateway"


@pytest.mark.parametrize("name", FORBIDDEN)
def test_no_github_or_portal_credential_reaches_the_sandbox(cfg, run_token, name):
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
    assert name not in env


def test_no_value_of_a_forbidden_credential_reaches_the_sandbox_under_another_name(
    cfg, run_token
):
    """A rename is the way this guarantee would actually be lost."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
    secrets = {f"secret-{name.lower()}" for name in FORBIDDEN}
    leaked = {key: value for key, value in env.items() if value in secrets}
    assert leaked == {}


def test_the_environment_is_built_from_a_list_rather_than_copied(cfg, run_token):
    """`os.environ` is never the starting point: a control-plane variable added
    next year must not arrive in a sandbox because nobody updated a deny list."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
    assert "QA_CORS_ORIGINS" not in env
    assert "QA_SANDBOX" not in env
    source = Path(sandbox_env.__file__).read_text()
    assert "**os.environ" not in source
    assert "dict(os.environ" not in source
    assert "os.environ.copy" not in source


def test_the_agent_runtimes_telemetry_and_error_reporting_are_disabled(cfg, run_token):
    """Disabled by environment rather than allowlisted, so the allowlist stays
    the length of what a run genuinely needs."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
    assert env["DISABLE_TELEMETRY"] == "1"
    assert env["DISABLE_ERROR_REPORTING"] == "1"
    assert env["CLAUDE_CODE_ENABLE_TELEMETRY"] == "0"
    assert env["DISABLE_AUTOUPDATER"] == "1"


def test_every_value_is_a_string_a_container_can_take(cfg, run_token):
    env = sandbox_env.sandbox_environment(7, cfg, run_token)
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
    assert "playwright install" in dockerfile
    # Node 22 or newer, grafted from the official image: the CLI requires it and
    # this base's apt ships 20, so `apt-get install nodejs` would build an image
    # whose agent runtime refuses to start.
    assert "/usr/local/bin/node" in dockerfile
    major = int(
        re.search(r"node:(\d+)-", dockerfile).group(1)
    )
    assert major >= 22


def test_the_sandbox_image_installs_the_browsers_at_build_time():
    """A run starts without downloading one: time-to-first-step in seconds."""
    dockerfile = _dockerfile()
    assert 'npm install -g "playwright@${PLAYWRIGHT_VERSION}"' in dockerfile
    assert "PLAYWRIGHT_BROWSERS_PATH" in dockerfile


def test_the_prebaked_browser_version_is_read_from_the_revisions_lockfile():
    """The one failure that silently undoes "no download at run time" is `npm
    ci` from the lockfile fetching a browser build the image does not hold.

    Structural rather than compared: a second copy of the pin that a test keeps
    honest is still a second copy, and the lockfile every revision carries is
    already the source of truth for the dependency. So the image reads the
    version out of it at build time, and this asserts there is nothing left to
    keep in sync.
    """
    dockerfile = _dockerfile()
    lockfile = "server/app/delivery/templates/package-lock.json"

    assert f"COPY {lockfile}" in dockerfile
    assert "node_modules/@playwright/test" in dockerfile, "read from the lockfile"
    assert "PLAYWRIGHT_VERSION=" not in code_lines(dockerfile).replace(
        'PLAYWRIGHT_VERSION="$(node', ""
    ), "no hand-maintained copy of the pin"


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


def test_the_npm_cache_is_baked_into_the_image_rather_than_shared():
    """Story 23 wants `npm ci` warm. A cache *volume* mounted into every
    sandbox would be a writable directory shared between containers running
    different customers' agents -- a supply-chain path between them, which is
    what container-per-run exists to close. So it is in the image."""
    dockerfile = _dockerfile()
    assert "npm ci --cache /npm-cache" in dockerfile
    assert "package-lock.json" in dockerfile
    assert sandbox_env.NPM_CACHE == "/npm-cache"
    assert "volumes" not in _compose()["services"]["sandbox"]


def test_install_dependencies_is_still_one_named_function():
    """The image makes that install fast; it does not replace it, because the
    lockfile in the revision stays the source of truth for dependencies."""
    import inspect

    from app.sandbox import hydrate

    assert inspect.isfunction(hydrate.install_dependencies)
    assert "npm" in inspect.getsource(hydrate.install_dependencies)


# --- the control plane is reached directly, not through the proxy --------
#
# This section used to be about the stores. P5-05 took them off the sandbox's
# network entirely, and the trap they were here for moved intact to the thing
# that replaced them.

def test_the_internal_control_plane_is_not_sent_through_the_proxy(cfg, run_token):
    """The bug this test exists for, now one layer up.

    `HTTP_PROXY` is honoured by more clients than the ones it is set for. It was
    boto3 before -- the S3 client tunnelled `http://seaweedfs:8333` to the
    allowlisting proxy, which refused it, correctly, and hydrate and ingest both
    failed in any stack that had a proxy. The client is `httpx` now and the host
    is the control plane's, and the consequence is worse rather than better: not
    one operation but *every* operation a run performs goes through the internal
    API.

    So the control plane bypasses the proxy rather than being allowlisted
    through it. A proxy that could reach the internal API would be a proxy worth
    attacking -- the same argument that kept the stores off the allowlist, now
    protecting what replaced them. The Docker-backed integration test cannot
    catch this: it runs with no proxy at all.
    """
    env = sandbox_env.sandbox_environment(
        7, cfg, run_token, proxy_url="http://qa-proxy-run:3128"
    )

    for name in ("NO_PROXY", "no_proxy"):
        hosts = env[name].split(",")
        assert "api" in hosts, env[name]
    assert env["HTTPS_PROXY"] == "http://qa-proxy-run:3128"


def test_the_stores_are_not_on_the_sandboxs_network_at_all(cfg, run_token):
    """The other half of "the stores are unreachable from a sandbox".

    They are not allowlisted through the proxy, and they are no longer on the
    bypass path either -- because the sandbox is not told where they are. There
    is no hostname here for a run to resolve, in `NO_PROXY` or out of it.
    """
    env = sandbox_env.sandbox_environment(
        7, cfg, run_token, proxy_url="http://qa-proxy-run:3128"
    )

    for name in ("NO_PROXY", "no_proxy"):
        hosts = env[name].split(",")
        assert "seaweedfs" not in hosts, env[name]
        assert "postgres" not in hosts, env[name]
    assert not any("seaweedfs" in value for value in env.values())
    assert not any("postgres" in value for value in env.values())


def test_the_host_in_no_proxy_is_the_control_plane_the_sandbox_was_given(
    cfg, run_token, monkeypatch
):
    """Derived from the URL, never hand-listed: a stack whose API is somewhere
    else must not need this file edited to keep working."""
    monkeypatch.setenv("QA_CONTROL_PLANE_URL", "http://control.internal:9000")

    env = sandbox_env.sandbox_environment(7, cfg, run_token, proxy_url="http://p:3128")

    assert "control.internal" in env["NO_PROXY"].split(",")


def test_the_target_is_not_in_no_proxy(cfg, run_token):
    """It must go *through* the proxy: that is where the allowlist and the
    public-address rule are enforced."""
    env = sandbox_env.sandbox_environment(7, cfg, run_token, proxy_url="http://p:3128")

    assert "shop.example.com" not in env["NO_PROXY"].split(",")


def test_without_a_proxy_there_is_no_proxy_environment_at_all(cfg, run_token):
    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    for name in ("HTTP_PROXY", "HTTPS_PROXY", "NO_PROXY", "QA_PROXY_URL"):
        assert name not in env


# --- the per-tenant PAT (P5-03) ------------------------------------------
#
# P4's rule was about one operator `GITHUB_PAT`. P5-03 turns the credential
# into a per-tenant secret on the target row, which makes the rule larger
# rather than smaller: there is now a credential *per customer* to keep out,
# plus the key material that would open it. The tests below are the same shape
# as the ones above -- what cannot happen, not what did.


def test_the_target_configuration_a_sandbox_is_handed_carries_no_credential():
    """The structural half, and the reason it is cheap to be sure of.

    `sandbox_environment` takes a `TargetConfig`, which is the target's row
    *minus* its credential: the dataclass has no field for one, so there is no
    value for the environment builder to pass along even by mistake. A sealed
    PAT reaching a sandbox would have to start with somebody adding a field
    here, which is a reviewable line rather than an oversight.
    """
    import dataclasses

    fields = {f.name for f in dataclasses.fields(TargetConfig)}

    assert fields == {
        "app",
        "name",
        "base_url",
        "locators",
        "agent_notes",
        "target_repo",
        "target_branch",
    }
    for name in ("github_pat_ciphertext", "pat_expires_at", "credential_state"):
        assert name not in fields


def test_no_sealed_credential_or_wrapping_key_reaches_the_sandbox(
    cfg, run_token, monkeypatch
):
    """Belt as well as braces: a real sealed PAT and the key that opens it are
    both in the control plane's environment, and neither comes out."""
    from app import envelope

    monkeypatch.setenv("QA_KMS_KEY_ID", "arn:aws:kms:eu-west-1:1:key/abc")
    sealed = envelope.seal(
        "ghp_aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
        envelope.LocalKeyWrapper(b"the-suite-wrapping-key"),
    )

    env = sandbox_env.sandbox_environment(7, cfg, run_token)

    assert "QA_KMS_KEY_ID" not in env
    assert not any(sealed in value for value in env.values())
    assert not any("ghp_" in value for value in env.values())
    # The wrapping key itself, under whatever name: `_control_plane_environment`
    # puts a recognisable value in QA_SECRET_KEY, and the rename guard above
    # covers the general case.
    assert not any(value == "secret-qa_secret_key" for value in env.values())


def test_no_module_reachable_from_the_entrypoint_can_open_a_sealed_credential():
    """The import-graph half, extended to the decrypt path.

    The sandbox image ships the same server package as the API, so
    `app/envelope.py` and `app/delivery/credentials.py` exist in it. What must
    not exist is a path from the entrypoint to them: until P5-05 the sandbox
    holds `DATABASE_URL`, so it can *read* `targets.github_pat_ciphertext`
    already -- the envelope is what makes that harmless, and it stays harmless
    only while nothing in there can unwrap a data key.
    """
    modules = _modules_reachable_from_the_entrypoint()

    assert "app.envelope" not in modules
    assert "app.delivery.credentials" not in modules


@pytest.mark.parametrize("name", ("decrypt_pat", "open_sealed", "LocalKeyWrapper"))
def test_nothing_the_sandbox_imports_mentions_the_decrypt_path(name):
    """The rename guard, as for the forbidden credentials above: a module that
    acquired this by being imported for something else would not show up as a
    failing behaviour anywhere."""
    offenders = []
    for module in _modules_reachable_from_the_entrypoint():
        path = SERVER_DIR / (module.replace(".", "/") + ".py")
        if not path.is_file():
            path = SERVER_DIR / module.replace(".", "/") / "__init__.py"
        if path.is_file() and name in code_of(path):
            offenders.append(module)
    assert offenders == [], (
        f"{offenders} are reachable from the sandbox entrypoint and mention "
        f"{name}; no sandbox may be able to open a tenant's sealed credential"
    )
