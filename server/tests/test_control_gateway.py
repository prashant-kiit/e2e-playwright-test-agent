"""One suite, both transports: the thread path and the container path agree.

P5-05 gives the control plane one set of operations (app/control/service.py) and
two ways to reach them -- `LocalGateway` calls it in this process, `HttpGateway`
calls it over the internal API. That is the design's main risk: two transports
can drift, and a sandbox would be the only thing to notice.

So every test here is parametrized over both gateways, and the fixture is the
only thing that differs. A field serialized on one side and not deserialized on
the other, a route that forgets a parameter, an exception that arrives as the
wrong type over HTTP -- all of them fail here rather than in a container.

The scope refusals themselves are tested at the service
(tests/test_control_service.py), which is where the decision is made. What is
tested here is that each transport *carries* them.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import internal_api, repo, revisions, run_token
from app.control.gateway import GatewayStorage, RunGateway
from app.control.http import HttpGateway
from app.control.local import LocalGateway
from app.control.model import TrackedBlob
from app.control.service import NotAuthorized, RunNotLive
from app.db import get_session
from app.domain import store_keys
from app.domain.steps import Step
from app.main import app as fastapi_app
from app.run_token import RunScope
from app.tenancy import tenant_scope
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def world(session_factory, tmp_path, monkeypatch):
    """A target at revision 1, one live run, and the token minted for it."""
    monkeypatch.setenv("QA_SECRET_KEY", "the-suite-signing-key")
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
            "run_key": run.run_key,
            "store": store,
            "session_factory": session_factory,
        }


@pytest.fixture(params=("local", "http"))
def gateway(request, world) -> RunGateway:
    """The same gateway contract, reached two ways.

    The HTTP case drives the real routes through `TestClient` with the session
    and storage dependencies overridden onto the test fixtures -- so it is the
    real router, the real token header and the real JSON, against the same
    database rows the local case uses.
    """
    if request.param == "local":
        yield LocalGateway(
            world["token"],
            session_factory=world["session_factory"],
            store=world["store"],
        )
        return

    def _session():
        s = world["session_factory"]()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = _session
    fastapi_app.dependency_overrides[internal_api.get_storage] = lambda: world["store"]
    client = TestClient(fastapi_app)
    try:
        yield HttpGateway("http://testserver", world["token"], client=client)
    finally:
        fastapi_app.dependency_overrides.clear()


# --- what a run reads ----------------------------------------------------

def test_a_run_reads_its_own_facts_and_its_targets_configuration(gateway, world):
    facts = gateway.run_facts()

    assert facts.run_key == world["run_key"]
    assert facts.app == "demo"
    assert facts.story_id == "SCRUM-1"
    assert facts.mode == "full"
    assert facts.last_completed_step is None
    # The target's configuration comes through with it: a sandbox holds exactly
    # one target's tree, so this is part of what the run *is*.
    assert facts.target.base_url.startswith("https://")
    assert facts.target.target_repo
    assert facts.target.agent_notes


def test_a_run_reads_the_state_an_operator_can_change_under_it(gateway):
    state = gateway.run_state()

    assert state.stop_requested is False
    assert state.pause_requested is False
    assert state.claude_session_id is None


def test_a_run_reads_its_head_revision_and_every_file_of_it(gateway):
    head = gateway.head_revision()

    assert head.rev == 1
    assert head.tree_hash
    paths = {f.path for f in head.files}
    assert "package.json" in paths
    assert all(f.blob_key.startswith("tenant/") for f in head.files)
    assert all(f.size > 0 for f in head.files)


# --- blobs, through the Storage adapter both paths share -----------------

def test_a_run_fetches_the_bytes_of_its_own_revision(gateway):
    """Hydrate's whole dependency on the store, exercised through the adapter
    that `materialize` actually uses."""
    head = gateway.head_revision()
    store = GatewayStorage(gateway)
    wanted = next(f for f in head.files if f.path == "package.json")

    chunks, _ct = store.get_stream(wanted.blob_key)

    assert b"".join(chunks)
    assert store.exists(wanted.blob_key)


def test_a_blob_the_store_does_not_hold_is_absent_rather_than_an_error(gateway, world):
    """`exists` is the dedup check, so "no" has to be an answer."""
    absent = revisions.blob_key(world["scope"].tenant_id, "0" * 64)

    assert GatewayStorage(gateway).exists(absent) is False


def test_a_run_uploads_a_blob_under_its_own_content_hash(gateway, world, tmp_path):
    """Ingest's upload. The key a run may write is the key its bytes name."""
    store = GatewayStorage(gateway)
    source = tmp_path / "blob.txt"
    source.write_bytes(b"the bytes a step produced")
    key = revisions.blob_key(
        world["scope"].tenant_id, revisions.file_sha256(source)
    )

    store.put_file(key, source)

    assert store.exists(key)


def test_a_blob_whose_bytes_do_not_match_its_key_is_refused(gateway, world, tmp_path):
    """The poisoning case, and the reason the write rule is a content check.

    Blob keys are per-tenant, not per-target, so two targets of one tenant share
    a content-address space. `commit_revision` confirms a blob *exists*, not
    what is in it -- so without this a run could write chosen bytes under
    another target's blob key and corrupt a revision it is not even allowed to
    read. A prefix rule cannot catch that; content addressing can, and makes the
    attempt a no-op instead.
    """
    store = GatewayStorage(gateway)
    source = tmp_path / "poison.txt"
    source.write_bytes(b"not what this key names")
    someone_elses = revisions.blob_key(world["scope"].tenant_id, "a" * 64)

    with pytest.raises(NotAuthorized):
        store.put_file(someone_elses, source)


def test_a_blob_no_revision_of_this_target_references_cannot_be_read(
    gateway, world, tmp_path
):
    """#30: "every blob read authorized through a Postgres row... no
    serve-by-key-alone".

    A blob key *is* a content hash, so it is guessable and shareable, and the
    tenant prefix alone would let one target's run read another target's tree.
    The row is what pins the read to the target the token actually names.
    """
    store = GatewayStorage(gateway)
    source = tmp_path / "unreferenced.txt"
    source.write_bytes(b"uploaded but never committed")
    key = revisions.blob_key(
        world["scope"].tenant_id, revisions.file_sha256(source)
    )
    store.put_file(key, source)  # allowed: the bytes match the key

    with pytest.raises(NotAuthorized):
        store.get_stream(key)


def test_a_key_outside_the_tokens_prefixes_is_refused_on_both_paths(gateway):
    """The refusal is the service's; this is that it survives the transport.

    Over HTTP it has to arrive as `NotAuthorized` rather than as a bare
    non-2xx, because that is the type the run-side code is written against.
    """
    store = GatewayStorage(gateway)

    with pytest.raises(NotAuthorized):
        store.exists("tenant/99999/blobs/" + "b" * 64)


# --- what a run writes ---------------------------------------------------

def test_a_run_drives_its_own_status_through_the_gateway(gateway, world):
    gateway.begin_run()
    assert gateway.run_state().status.value == "running"

    gateway.complete_run()
    assert gateway.run_status() == "completed"


def test_a_run_records_its_steps(gateway, world):
    gateway.begin_run()

    gateway.start_step(Step.READ_STORY)
    gateway.complete_step(Step.READ_STORY)

    assert gateway.run_facts().last_completed_step is Step.READ_STORY


def test_a_run_records_and_clears_the_agents_session_id(gateway):
    gateway.set_session_id("sess-abc123")
    assert gateway.run_state().claude_session_id == "sess-abc123"

    gateway.clear_session_id()
    assert gateway.run_state().claude_session_id is None


def test_a_run_commits_revision_two_from_a_manifest(gateway, world, tmp_path):
    """Ingest's half: the blobs go up, then the manifest, and the control plane
    derives the tree hash and writes the row."""
    store = GatewayStorage(gateway)
    head = gateway.head_revision()
    source = tmp_path / "new.spec.ts"
    source.write_bytes(b"test('healed', () => {});")
    sha = revisions.file_sha256(source)
    store.put_file(revisions.blob_key(world["scope"].tenant_id, sha), source)

    manifest = [
        TrackedBlob(path=f.path, sha256=revisions.sha256_from_blob_key(f.blob_key), size=f.size)
        for f in head.files
    ] + [TrackedBlob(path="tests/new.spec.ts", sha256=sha, size=source.stat().st_size)]

    assert gateway.commit_revision(manifest, author="run:test") == 2


def test_committing_an_unchanged_tree_commits_nothing(gateway, world):
    """Three of the five steps change no tracked file, so this is the ordinary
    case rather than an edge one."""
    head = gateway.head_revision()
    manifest = [
        TrackedBlob(path=f.path, sha256=revisions.sha256_from_blob_key(f.blob_key), size=f.size)
        for f in head.files
    ]

    assert gateway.commit_revision(manifest, author="run:test") is None


def test_a_revision_naming_a_blob_nobody_uploaded_is_refused(gateway, world):
    """The split path's own failure mode: over a network the upload and the
    commit are separate requests, so a dropped upload must not become a
    revision that hydrates to nothing later."""
    from app.control.service import ControlPlaneError

    manifest = [TrackedBlob(path="tests/ghost.ts", sha256="c" * 64, size=12)]

    with pytest.raises(ControlPlaneError):
        gateway.commit_revision(manifest, author="run:test")


def test_a_run_indexes_an_artifact_and_versions_it_on_change(gateway, world, tmp_path):
    store = GatewayStorage(gateway)
    # Asked of the key builder rather than spelled out. It was spelled out, in
    # the pre-P5-10 shape, and kept passing after #42 moved artifacts under the
    # tenant prefix -- because the service still accepted the old shape on
    # writes. Tightening that to reads only is what made this test fail, which
    # is the test doing its job a release late.
    key = store_keys.artifact_key(
        world["scope"].tenant_id, world["run_key"], "trace.zip"
    )
    source = tmp_path / "trace.zip"
    source.write_bytes(b"first")
    store.put_file(key, source)

    first = gateway.index_artifact(
        key=key, sha256=revisions.file_sha256(source), kind="trace", step=Step.READ_STORY
    )
    source.write_bytes(b"second, different")
    second = gateway.index_artifact(
        key=key, sha256=revisions.file_sha256(source), kind="trace", step=Step.READ_STORY
    )

    assert (first, second) == (1, 2)
    assert [row.key for row in gateway.artifacts()] == [key]


def test_a_run_publishes_log_lines_in_order(gateway, world):
    """The lines land in `run_log` where a reader in the API process -- another
    process entirely, on the container path -- reads them back by cursor.

    Nothing asserts the stream was *closed*: a Postgres-backed stream ends when
    the run's status ends (`PostgresLogBus.close` is a no-op and says why), so
    there is no close operation to exercise.
    """
    from app.orchestrator.bus import PostgresLogBus

    gateway.publish_log(["=== step: read-story ===", "=== step read-story done ==="])
    gateway.publish_log(["=== step: plan ==="])

    with tenant_scope(world["scope"].tenant_id):
        bus = PostgresLogBus(session_factory=world["session_factory"])
        lines, cursor = bus.read_from(world["scope"].run_id, 0)
    assert lines == [
        "=== step: read-story ===",
        "=== step read-story done ===",
        "=== step: plan ===",
    ]
    assert cursor == 3


def test_a_run_refreshes_its_lease_and_records_its_cost(gateway, world):
    gateway.begin_run()
    gateway.heartbeat()
    gateway.record_cost(spend_usd=1.25, sandbox_seconds=42)

    with world["session_factory"]() as s, tenant_scope(world["scope"].tenant_id):
        run = repo.get_run(s, world["scope"].run_id)
        assert float(run.spend_usd) == 1.25
        assert run.sandbox_seconds == 42


# --- the liveness gate, carried by both transports -----------------------

def test_once_the_run_is_over_the_gateway_refuses_everything(gateway, world):
    """AC: the token is rejected once the run is no longer live. Over HTTP this
    must arrive as `RunNotLive` and not as a generic failure, because the
    sandbox tells "my run was stopped" from "my deployment is broken" by the
    type."""
    gateway.begin_run()
    gateway.complete_run()

    with pytest.raises(RunNotLive):
        gateway.run_facts()
    with pytest.raises(RunNotLive):
        gateway.heartbeat()


def test_a_finished_run_can_still_be_asked_for_its_status(gateway):
    """The one read a token outlives its run to perform: the entrypoint's exit
    code is read off the row rather than inferred."""
    gateway.begin_run()
    gateway.complete_run()

    assert gateway.run_status() == "completed"


def test_a_finished_run_can_still_publish_the_lines_that_say_it_finished(gateway, world):
    """The lines an operator reads first are emitted after the run ends.

    `=== run <key> completed ===`, the teardown line and the cost line are all
    emitted from `drive_run`'s `finally`, after the final status transition. A
    liveness gate on the log therefore drops exactly them -- which is what it
    did, and the symptom was a container path whose log was complete except for
    how the run ended.
    """
    from app.orchestrator.bus import PostgresLogBus

    gateway.begin_run()
    gateway.complete_run()

    gateway.publish_log(["=== run completed ===", "=== teardown: worktree removed ==="])

    with tenant_scope(world["scope"].tenant_id):
        bus = PostgresLogBus(session_factory=world["session_factory"])
        lines, _cursor = bus.read_from(world["scope"].run_id, 0)
    assert lines == ["=== run completed ===", "=== teardown: worktree removed ==="]


def test_a_finished_run_can_still_record_what_it_cost(gateway, world):
    """Recorded in the same `finally`, for the same reason."""
    gateway.begin_run()
    gateway.complete_run()

    gateway.record_cost(spend_usd=2.5, sandbox_seconds=99)

    with world["session_factory"]() as s, tenant_scope(world["scope"].tenant_id):
        run = repo.get_run(s, world["scope"].run_id)
        assert float(run.spend_usd) == 2.5
        assert run.sandbox_seconds == 99


def test_a_finished_run_still_cannot_commit_a_revision_or_drive_its_status(
    gateway, world
):
    """The gate is intact where it matters: the exemptions are reads, accounting
    and an append-only log, never the run's work."""
    gateway.begin_run()
    gateway.complete_run()

    with pytest.raises(RunNotLive):
        gateway.commit_revision([], author="run:test")
    with pytest.raises(RunNotLive):
        gateway.start_step(Step.HEAL)
    with pytest.raises(RunNotLive):
        gateway.index_artifact(
            key=f"{world['run_key']}/late.zip", sha256="d" * 64, kind="trace", step=None
        )
