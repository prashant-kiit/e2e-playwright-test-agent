"""The real pipeline, driven over the HTTP control-plane seam. P5-17 / #49.

#30's implementation decisions say "the run-scoped API is consumed by both the
thread and docker paths so the suite exercises it", and that was only partly
true. `control.factory.local_for_run` hands the thread path a `LocalGateway`,
which calls `service.py` in this process, so until this file the HTTP transport
-- `app/internal_api.py` and `app/control/http.py` -- was covered by its own
unit tests (tests/test_internal_api.py), by one suite run through both
gateways (tests/test_control_gateway.py), and by the Docker-backed checks. **No
suite run drove it through the pipeline that composes a real run.**

That gap has a measured size. P5-05's record says four real bugs in this area
were found by running a container and none by the suite, and the shape of them
is why: each was in the *composition* rather than in an operation. A client
that verified a token it holds no key for, a log bus that exited before its
last batch, a store binding one of its two interfaces -- every one of those
passes an operation-by-operation test and fails a run.

So what is different here is deliberately **not** the assertions. They are the
ones tests/test_docker_sandbox.py makes about a real container, and the ones
the thread path is checked for elsewhere: the run row, the step rows, the
revisions, the artifacts and the log. What is different is that the gateway
handed to `launcher.drive_run` is an `HttpGateway` over the real router, and
the bus is the `GatewayLogBus` a sandbox actually writes through.

**And no Docker.** `TestClient` gives the real routes, the real `Authorization`
header and the real JSON over an in-process transport, which is every layer
this file is about except the network. What is left to the Docker-backed tests
is the container, the image and the network -- and they are still the only
thing that proves those.

The composition itself is untouched, which is the other half of the ticket:
still one `drive_run`, still two call sites, and the only thing this file
supplies is which gateway.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import internal_api, launcher, repo, revisions, run_token
from app.control.http import HttpGateway
from app.control.service import NotAuthorized
from app.db import get_session
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.main import app as fastapi_app
from app.models import Artifact
from app.orchestrator.bus import GatewayLogBus, PostgresLogBus
from app.orchestrator.fake import FakeRunner
from app.run_token import RunScope
from tests.control_helpers import SIGNING_KEY
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def world(session_factory, tmp_path, monkeypatch):
    """A target at revision 1 and a run to drive, plus the run's own token."""
    monkeypatch.setenv("QA_SECRET_KEY", SIGNING_KEY)
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))
    monkeypatch.setenv("QA_RUNNER", "fake")
    store = FakeStorage()
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        revisions.commit_revision(
            s, target, store, make_worktree(tmp_path / "source"), author="operator"
        )
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        scope = RunScope(
            run_id=run.id,
            target_id=target.id,
            tenant_id=run.tenant_id,
            sandbox_attempt=run.sandbox_attempt,
        )
        return {
            "scope": scope,
            "token": run_token.mint(scope),
            "run_id": run.id,
            "run_key": run.run_key,
            "target_id": target.id,
            "store": store,
        }


@pytest.fixture()
def client(world, session_factory):
    """The internal API's real router, over an in-process transport.

    The two dependencies a deployment supplies are overridden onto the
    fixtures' database and the fixtures' store, and nothing else is: the token
    header, the routes, the status codes and the JSON are the production ones.
    """

    def _session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = _session
    fastapi_app.dependency_overrides[internal_api.get_storage] = lambda: world["store"]
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


@pytest.fixture()
def gateway(world, client) -> HttpGateway:
    """What a sandbox holds: a base URL and a token, and nothing else."""
    return HttpGateway("http://testserver", world["token"], client=client)


# --- a whole run, through the seam a container uses ----------------------

def test_a_run_driven_over_http_produces_the_rows_a_thread_run_produces(
    world, session_factory, gateway
):
    """The file's load-bearing test, and all of it is about rows.

    Every operation the ticket lists is in here, and none of them is called by
    this test: hydrate reads the head revision and every blob of it, the step
    boundary hook writes blobs and commits revision N+1, the sweep uploads and
    indexes artifacts, and the bus publishes the log -- all through
    `launcher.drive_run`, which is handed an `HttpGateway` and is otherwise the
    function the thread path and the container path both call.
    """
    run_id, run_key, target_id = world["run_id"], world["run_key"], world["target_id"]

    launcher.drive_run(
        gateway,
        # `writes_tree=True` for the same reason P4's container-path test sets
        # it: a step that changes no tracked file correctly commits no
        # revision, and a fake that can never produce one cannot stand in for
        # a run that does. The blob *writes* are the half of the seam this
        # buys, and they are half the ticket.
        runner=FakeRunner(writes_tree=True),
        # The bus a sandbox writes through, not an in-memory stand-in: its
        # batching, its background flusher and its `close` are part of the
        # composition, and `close` losing the last batch was a real bug here.
        bus=GatewayLogBus(gateway),
    )

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED, run.error
        assert run.last_completed_step is Step.HEAL
        assert {rs.step for rs in run.steps} == set(Step)

        revs = [
            rev for rev, _n in revisions.list_revisions_with_file_counts(s, target_id)
        ]
        assert len(revs) > 1, "the run committed a revision over the HTTP seam"
        head = revisions.head_revision(s, target_id)
        assert head.author == f"run:{run_key}"
        assert head.produced_by_run_id == run_id
        assert head.parent_rev == head.rev - 1

        artifacts = list(
            s.scalars(repo.select(Artifact).where(Artifact.run_id == run_id))
        )
        assert artifacts, "artifacts were uploaded and indexed over the HTTP seam"

    lines, _cursor = PostgresLogBus(session_factory=session_factory).read_from(run_id, 0)
    assert any("hydrate" in line for line in lines), lines[:5]
    # The lines emitted *after* the final status transition, which are the ones
    # an operator reads first and the ones a liveness gate over `publish_log`
    # would have swallowed (app/control/service.py names this).
    assert any(f"=== run {run_key} completed ===" == line for line in lines), lines[-5:]


def test_the_token_is_carried_and_verified_over_that_path(world, gateway):
    """The claims a sandbox reads are the claims the server verified.

    A sandbox cannot verify its own token -- it holds no signing key, by design
    -- so `HttpGateway` reads the claims unverified for addressing and the
    control plane is the only verifier. This asserts the two agree: the scope
    the gateway addresses with is the scope the server authorized, which is
    the invariant the "a sandbox must never verify its own token" rule rests
    on.
    """
    assert gateway.scope == world["scope"]
    # Answered by the server, under the token, for the run the claims name.
    assert gateway.run_facts().run_key == world["run_key"]


def test_a_token_for_the_wrong_run_is_refused_over_http(
    world, session_factory, client
):
    """Asserted rather than assumed, and over the transport rather than at the
    service.

    A second live run of the **same tenant**, so the enforced read filter is
    not what refuses it. On its own target, because one target has at most one
    live run (the target lock), which is also why a sandbox holding run B's
    token is a plausible thing: both runs exist at once.
    """
    with session_factory() as s:
        project = repo.create_project(s, name="sibling-project")
        sibling = create_target(s, project.id, app="sibling", name="Sibling")
        other = repo.start_run(
            s, target_id=sibling.id, story_id="SCRUM-2", mode="full"
        )
        stolen = run_token.mint(
            RunScope(
                run_id=other.id,
                target_id=sibling.id,
                tenant_id=other.tenant_id,
                sandbox_attempt=other.sandbox_attempt,
            )
        )

    # Run B's token on run A's path. The run id is in every URL, so this is the
    # only shape the attempt can take, and the API checks the claim against the
    # path before it reads a row.
    response = client.get(
        f"/internal/runs/{world['run_id']}/facts",
        headers={"Authorization": f"Bearer {stolen}"},
    )
    assert response.status_code == 403

    # Note what the gateway's own shape rules out: `HttpGateway._url` builds
    # every path from the run id in its *own* claims, so a sandbox cannot
    # address another run's path through it at all. The mismatch above is
    # reachable only by a client that writes its own URLs -- which is why it is
    # asserted here, against the router, rather than through the gateway.


def test_a_forged_token_is_refused_over_http_and_arrives_typed(
    world, session_factory, client, monkeypatch
):
    """The other way a sandbox could try to widen its scope: sign its own.

    It cannot -- the signing key is on the forbidden list
    (tests/test_sandbox_credentials.py) precisely because a sandbox that could
    verify a token could also mint one -- and this is what happens if it ever
    could. The claims are well formed and the gateway reads them happily,
    because reading is all it does; the server is the only verifier.

    Over the gateway rather than the router, so the refusal is asserted to
    arrive as the typed exception the run-side code is written against rather
    than as a status code it would have to interpret.
    """
    monkeypatch.setenv("QA_SECRET_KEY", "a-key-the-deployment-never-had")
    forged = run_token.mint(world["scope"])
    monkeypatch.setenv("QA_SECRET_KEY", SIGNING_KEY)

    gateway = HttpGateway("http://testserver", forged, client=client)
    assert gateway.scope == world["scope"], "the claims read back; the signature does not"

    with pytest.raises(NotAuthorized):
        gateway.run_facts()
