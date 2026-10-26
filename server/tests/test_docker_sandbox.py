"""The container path, against a real container.

Everything else in the suite substitutes at the dispatch seam. These two tests
do not: they really start containers, because the two things they prove are
things a fake cannot. One is that a run executed in a container produces the
rows a thread run produces -- the whole claim of the phase. The other is that a
disallowed host is unreachable from the sandbox network, where the control being
tested is the network and not the function.

**They run in CI rather than skipping.** The GitHub runners have Docker, CI
fails if any test skips, and a silently-skipped container test would make this
phase's green tick meaningless (`QA_REQUIRE_DOCKER=1`, the sibling of
`QA_REQUIRE_DB`). Locally they skip with a reason when Docker, the image or a
reachable object store is missing, so the rest of the suite still runs offline.

Two deliberate shapes:

* **The `sandbox-runtime` stage, not the full image.** With `QA_RUNNER=fake` a
  run needs no browser and no CLI, so CI builds python plus the server package
  rather than two gigabytes to prove that a container hydrates, commits
  revisions and streams a log. What the full image adds -- Node, the CLI, the
  browsers -- is proven by a real agent run in VERIFICATION-P4.md, which is the
  only thing that can prove it.
* **Nothing reaches inside a container.** Every assertion here is about a row,
  a blob or a refused connection.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
import uuid
from pathlib import Path

import pytest
from sqlalchemy.engine import make_url

from app import repo, revisions
from app.db import database_url
from app.domain.status import RunStatus, is_terminal
from app.domain.steps import Step
from app.models import Artifact
from app.orchestrator.bus import PostgresLogBus
from app.sandbox import dispatch
from app.sandbox import docker as sandbox_docker
from app.storage import S3Storage
from tests.conftest import TEST_DB
from tests.delivery_helpers import make_worktree
from tests.target_helpers import create_target, public_resolver

SERVER_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = SERVER_DIR.parent

# Built by the fixture below (and by CI before the suite runs).
RUNTIME_IMAGE = "qa-sandbox-runtime:test"
PROXY_IMAGE = "qa-egress-proxy:test"

# How a container reaches a service published on the host. Docker Desktop
# provides the name; on Linux the `host-gateway` mapping below provides it.
HOST_ALIAS = "host.docker.internal"
HOST_GATEWAY = f"{HOST_ALIAS}:host-gateway"

# A sandboxed run with the fake runner is five steps of a few seconds; the
# ceiling is for a cold container start on a loaded machine.
RUN_TIMEOUT_S = 180.0
POLL_S = 0.5

# What a container on the sandbox network reports about the world. Spelled out
# rather than compressed into a `-c` one-liner: what it prints is the evidence
# the egress test rests on, and it should be readable by whoever reviews that
# the control is real.
PROBE = """
import json, socket, urllib.error, urllib.request

PROXY = "http://{proxy}:3128"
opener = urllib.request.build_opener(
    urllib.request.ProxyHandler({{"http": PROXY, "https": PROXY}})
)


def through_proxy(url):
    try:
        opener.open(url, timeout=20)
        return "reachable"
    except urllib.error.HTTPError as exc:
        return "reachable" if exc.code < 400 else "refused:%d" % exc.code
    except Exception as exc:
        return "unreachable:%s" % type(exc).__name__


def direct(host, port):
    try:
        socket.create_connection((host, port), timeout=5).close()
        return "reachable"
    except Exception as exc:
        return "unreachable:%s" % type(exc).__name__


def resolves(host):
    try:
        return socket.gethostbyname(host)
    except Exception as exc:
        return "unresolvable:%s" % type(exc).__name__


print(json.dumps({{
    "allowed_via_proxy": through_proxy("http://example.com/"),
    "disallowed_via_proxy": through_proxy("http://registry.npmjs.org/"),
    "metadata_via_proxy": through_proxy("http://169.254.169.254/"),
    "metadata_direct": direct("169.254.169.254", 80),
    "internet_direct": direct("93.184.216.34", 80),
    "sandbox_resolves_a_name_itself": resolves("example.com"),
}}))
"""


def docker_unavailable(reason: str):
    """Skip -- unless CI promised Docker, in which case fail loudly.

    Exactly `conftest.db_unavailable`'s bargain: the one test that proves the
    container path must not be allowed to go quiet in the place that counts.
    """
    if os.environ.get("QA_REQUIRE_DOCKER", "").strip() not in ("", "0", "false"):
        pytest.fail(f"QA_REQUIRE_DOCKER is set but Docker is unusable: {reason}")
    pytest.skip(reason)


def _docker(*args: str, check: bool = True, cwd: Path | None = None) -> (
    subprocess.CompletedProcess
):
    return subprocess.run(
        ["docker", *args], capture_output=True, text=True, check=check, cwd=cwd
    )


@pytest.fixture(scope="session")
def runtime_image():
    """The sandbox image's python stage, built once per session."""
    try:
        _docker("info")
    except FileNotFoundError:
        docker_unavailable("the docker CLI is not on PATH")
    except subprocess.CalledProcessError as exc:
        docker_unavailable(f"the Docker daemon is not usable: {exc.stderr.strip()}")

    for image, target in ((RUNTIME_IMAGE, "sandbox-runtime"), (PROXY_IMAGE, "egress-proxy")):
        built = _docker(
            "build",
            "--target", target,
            "-f", "docker/Dockerfile.sandbox",
            "-t", image,
            ".",
            # The build context is the repository root: the image is built from
            # the same server package as the API (`COPY server/app`).
            cwd=REPO_ROOT,
            check=False,
        )
        if built.returncode != 0:
            docker_unavailable(
                f"could not build {image}: {built.stderr.strip()[-500:]}"
            )
    return RUNTIME_IMAGE


@pytest.fixture()
def real_store():
    """A real object store: the container has to read the blobs this seeds.

    The suite otherwise refuses `storage.from_env()` outright, and rightly --
    these tests are the exception that proves the rule, because a container
    cannot share an in-memory fake with the test that started it.
    """
    endpoint = os.environ.get("S3_ENDPOINT", "http://localhost:8333")
    store = S3Storage(
        endpoint=endpoint,
        access_key=os.environ.get("S3_ACCESS_KEY", "qa"),
        secret_key=os.environ.get("S3_SECRET_KEY", "qa-secret"),
        bucket=os.environ.get("S3_BUCKET", "qa-artifacts"),
    )
    try:
        store.ensure_bucket()
    except Exception as exc:  # the dev stack's store is not up
        docker_unavailable(f"no object store at {endpoint}: {exc}")
    return store


@pytest.fixture()
def container_env(monkeypatch, real_store):
    """The environment a dispatched container is given, pointed at the host.

    The sandbox network of the compose stack is not what a test process has, so
    these tests put the container on Docker's default bridge and let it reach
    the Postgres and the object store the suite itself is using, through the
    host gateway. That is a difference in *where the stores are*, not in what
    the run does -- and the egress test below is the one that uses the real
    internal network.
    """
    url = make_url(database_url()).set(database=TEST_DB, host=HOST_ALIAS)
    monkeypatch.setenv("DATABASE_URL", url.render_as_string(hide_password=False))
    monkeypatch.setenv(
        "S3_ENDPOINT",
        os.environ.get("S3_ENDPOINT", "http://localhost:8333").replace(
            "localhost", HOST_ALIAS
        ),
    )
    monkeypatch.setenv("QA_RUNNER", "fake")
    monkeypatch.setenv("QA_FAKE_TREE_WRITES", "1")
    monkeypatch.setenv("QA_SANDBOX", "docker")


@pytest.fixture()
def seeded_run(session_factory, tmp_path, real_store):
    """A target with revision 1 in the real store, and a run to dispatch."""
    source = make_worktree(tmp_path / "source")
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app=f"demo-{uuid.uuid4().hex[:6]}")
        revisions.commit_revision(s, target, real_store, source, author="operator")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        return run.id, run.run_key, target.id


def _scheduler(session_factory, image: str) -> sandbox_docker.DockerScheduler:
    """A scheduler pointed at the host's stores, with no proxy.

    `with_proxy=False` because what these two tests prove is the container
    path; the egress control has its own Docker-backed test below, on the real
    internal network.
    """
    return sandbox_docker.DockerScheduler(
        sandbox_docker.DockerSettings(
            image=image,
            network="bridge",
            extra_hosts=(HOST_GATEWAY,),
            with_proxy=False,
        ),
        session_factory=session_factory,
        # The target's host is `demo.example.com`, which resolves nowhere: what
        # these tests are about is the container, and the resolution rule has
        # its own tests (tests/test_egress.py, tests/test_proxy.py).
        resolve=public_resolver,
    )


def _await_terminal(session_factory, run_id: int) -> RunStatus:
    deadline = time.monotonic() + RUN_TIMEOUT_S
    while time.monotonic() < deadline:
        with session_factory() as s:
            status = repo.get_run(s, run_id).status
        if is_terminal(status):
            return status
        time.sleep(POLL_S)
    return status


# --- the container path -------------------------------------------------

@pytest.mark.docker
def test_a_dispatched_container_produces_the_rows_a_thread_run_produces(
    runtime_image, container_env, seeded_run, session_factory
):
    """The phase's load-bearing assertion, and all of it is about rows.

    Whether a thread or a container did the work is the one thing the tests must
    not care about -- so what this checks is exactly what a thread run is
    checked for elsewhere: the run row, the step rows, the revisions, the
    artifacts and the log.
    """
    run_id, run_key, target_id = seeded_run
    scheduler = _scheduler(session_factory, runtime_image)
    # Through the launcher the API uses, so the handle is recorded as it is in
    # production rather than by this test.
    launch = dispatch.dispatching_launcher(scheduler, session_factory=session_factory)

    launch(run_id)
    with session_factory() as s:
        handle = repo.get_run(s, run_id).sandbox_handle
    try:
        status = _await_terminal(session_factory, run_id)
    finally:
        scheduler.destroy(handle or "")

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert status is RunStatus.COMPLETED, run.error
        assert run.last_completed_step is Step.HEAL
        assert {rs.step for rs in run.steps} == set(Step)
        assert run.sandbox_handle == handle, "the dispatch recorded its sandbox"

        revs = [rev for rev, _n in revisions.list_revisions_with_file_counts(s, target_id)]
        assert len(revs) > 1, "the sandboxed run committed revisions"
        head = revisions.head_revision(s, target_id)
        # Indistinguishable from a thread run's, which is what keeps the
        # Revisions panel, the delivery badge and `delivered_sha` working.
        assert head.author == f"run:{run_key}"
        assert head.produced_by_run_id == run_id
        assert head.parent_rev == head.rev - 1

        artifacts = list(s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id)))
        assert artifacts, "artifacts collected inside the container are indexed"

    lines, _cursor = PostgresLogBus(session_factory=session_factory).read_from(run_id, 0)
    assert any("hydrate" in line for line in lines), lines[:5]
    assert any(f"run {run_key} completed" in line for line in lines)


@pytest.mark.docker
def test_the_handle_names_a_container_a_human_can_find(
    runtime_image, container_env, seeded_run, session_factory
):
    """An SRE with a live run should be able to type the handle into `docker`."""
    run_id, run_key, _target_id = seeded_run
    scheduler = _scheduler(session_factory, runtime_image)

    handle = scheduler.dispatch(run_id)
    try:
        assert run_key in handle
        listed = _docker(
            "ps", "-a", "--filter", f"name={handle}", "--format", "{{.Names}}"
        ).stdout
        assert handle in listed
    finally:
        scheduler.destroy(handle)
        _await_terminal(session_factory, run_id)


# --- the network, not the function --------------------------------------

@pytest.mark.docker
def test_from_the_sandbox_network_only_the_allowlist_is_reachable(runtime_image):
    """The control being tested is the network: an internal network with no
    default route, and a proxy that refuses what is not on the allowlist.

    Nothing here is about a run. It stands up the real topology -- an internal
    network, a proxy on it with one allowed host -- and asks a container on that
    network what it can reach. The unit tests prove the policy; this proves that
    the policy is where an agent cannot get around it.
    """
    suffix = uuid.uuid4().hex[:8]
    internal = f"qa-sandbox-itest-{suffix}"
    egress_net = f"qa-egress-itest-{suffix}"
    proxy_name = f"qa-proxy-itest-{suffix}"

    _docker("network", "create", "--internal", internal)
    _docker("network", "create", egress_net)
    try:
        started = _docker(
            "run", "-d", "--name", proxy_name,
            "--network", egress_net,
            "-e", "QA_EGRESS_ALLOWLIST=example.com",
            "-e", "QA_PROXY_PORT=3128",
            PROXY_IMAGE,
            check=False,
        )
        if started.returncode != 0:
            docker_unavailable(f"could not start the proxy: {started.stderr.strip()}")
        _docker("network", "connect", internal, proxy_name)

        result = _docker(
            "run", "--rm", "--network", internal,
            "--entrypoint", "python",
            runtime_image, "-c", PROBE.format(proxy=proxy_name),
            check=False,
        )
        assert result.returncode == 0, result.stderr
        report = json.loads(result.stdout.strip().splitlines()[-1])

        # The allowlisted host is reachable *through the proxy* -- which is also
        # the proof that the proxy, not the sandbox, did the resolving.
        assert report["allowed_via_proxy"] == "reachable", report
        # Another host is refused by the proxy; 403 is the proxy's own answer.
        assert report["disallowed_via_proxy"] == "refused:403", report
        assert report["metadata_via_proxy"].startswith(("refused", "unreachable")), report
        # And with no default route there is nothing to reach directly: not the
        # metadata endpoint, not the internet, with or without the proxy.
        assert report["metadata_direct"].startswith("unreachable"), report
        assert report["internet_direct"].startswith("unreachable"), report
        # The sandbox resolves nothing itself: names go to the proxy.
        assert report["sandbox_resolves_a_name_itself"].startswith("unresolvable"), report
    finally:
        _docker("rm", "-f", proxy_name, check=False)
        _docker("network", "rm", internal, check=False)
        _docker("network", "rm", egress_net, check=False)


# --- the networks a dispatch needs --------------------------------------
#
# Found by running a run from the portal rather than by a test: Compose
# *declares* `qa-egress` but never creates it, because the only service on it is
# the `never-started` egress-proxy, and Compose skips the networks of a service
# a profile excludes. Every run therefore failed at dispatch with "network
# qa-egress not found" -- #23's "no extra steps", broken. These two pin the fix
# and, more importantly, its asymmetry.


@pytest.mark.docker
def test_the_egress_network_is_created_when_it_is_missing():
    """The proxy's way out is an ordinary bridge, so a dispatch may create it,
    and must, or `make up` does not give container-per-run on a laptop."""
    name = f"qa-egress-test-{uuid.uuid4().hex[:8]}"
    scheduler = sandbox_docker.DockerScheduler(
        sandbox_docker.DockerSettings(network="bridge", egress_network=name),
        resolve=public_resolver,
    )
    assert _docker("network", "inspect", name, check=False).returncode != 0, (
        "the premise: it is not there yet"
    )
    try:
        scheduler._ensure_egress_network()
        assert _docker("network", "inspect", name, check=False).returncode == 0
        # Idempotent, because every dispatch calls it.
        scheduler._ensure_egress_network()
        assert _docker("network", "inspect", name, check=False).returncode == 0
    finally:
        _docker("network", "rm", name, check=False)


@pytest.mark.docker
def test_a_missing_sandbox_network_is_refused_and_not_created():
    """The asymmetry, and the reason it is not a tidy-up away from being gone:
    a network Docker creates by default is **not** `internal`, so inventing
    `qa-sandbox` here would hand every sandbox a default route and remove the
    egress control without failing anything. A broken stack is the honest
    answer."""
    missing = f"qa-sandbox-absent-{uuid.uuid4().hex[:8]}"
    egress_name = f"qa-egress-test-{uuid.uuid4().hex[:8]}"
    scheduler = sandbox_docker.DockerScheduler(
        sandbox_docker.DockerSettings(network=missing, egress_network=egress_name),
        resolve=public_resolver,
    )
    try:
        with pytest.raises(sandbox_docker.DockerError) as caught:
            scheduler._require_sandbox_network()
        assert missing in str(caught.value)
        assert "internal" in str(caught.value), "it says why, not just that"
        assert _docker("network", "inspect", missing, check=False).returncode != 0, (
            "it did not create the one it refused"
        )
        assert _docker("network", "inspect", egress_name, check=False).returncode != 0, (
            "and it creates nothing at all: this method only ever refuses"
        )
    finally:
        _docker("network", "rm", missing, check=False)
        _docker("network", "rm", egress_name, check=False)


@pytest.mark.docker
def test_dispatch_checks_the_sandbox_network_even_with_no_proxy(
    seeded_run, session_factory
):
    """Where the check is called from, not what it does.

    The first fix put this check inside `_start_proxy`, so the `with_proxy=False`
    path never ran it -- the one configuration with no proxy to make a missing
    network loud was the one configuration that skipped the guard. The two tests
    above call the methods directly and would both stay green if the line in
    `dispatch` were deleted, so this one goes through `dispatch` and asserts the
    run is refused *before* a container is created.
    """
    run_id, run_key, _target_id = seeded_run
    missing = f"qa-sandbox-absent-{uuid.uuid4().hex[:8]}"
    scheduler = sandbox_docker.DockerScheduler(
        sandbox_docker.DockerSettings(network=missing, with_proxy=False),
        session_factory=session_factory,
        resolve=public_resolver,
    )

    with pytest.raises(sandbox_docker.DockerError) as caught:
        scheduler.dispatch(run_id)
    assert missing in str(caught.value)
    listed = _docker(
        "ps", "-a", "--filter", f"name={sandbox_docker.RUN_PREFIX}{run_key}",
        "--format", "{{.Names}}",
    ).stdout
    assert not listed.strip(), "it failed before starting anything"
