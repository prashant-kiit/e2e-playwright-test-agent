"""Runs commit revisions at step boundaries, through the launcher's composition.

These drive a whole run through `run_pipeline` with a FakeRunner, the shared
fake blob store and the Postgres fixture -- the highest seam available -- so they
cover the hook composition in the launcher as well as the functions behind it.
Prior art: test_artifacts.py, which does the same for artifact collection.

The driver still takes exactly one step-boundary callable; that is asserted
here too, because adding a second parameter is the thing DESIGN.md §13 names as
not to do.
"""

from __future__ import annotations

import inspect

import pytest

from app import launcher, repo, revisions
from app.domain.status import RunStatus
from app.domain.steps import STEP_ORDER, Step
from app.models import FileIndex, Revision
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner
from tests.delivery_helpers import make_workspace
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    """A real temp workspace with one app, a target, a run, and a runs dir."""
    workspace = make_workspace(tmp_path / "workspace", app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        return run.id, target.id, workspace


def _drive(session_factory, run_id, store, *, emit=None, collect_override=None):
    """Run the whole pipeline with the launcher's real composed hook."""
    lines: list[str] = []
    emit = emit or lines.append
    launcher.ensure_baseline_revision(
        run_id, emit, session_factory=session_factory, store=store
    )
    hook = launcher.make_step_boundary_hook(
        emit, session_factory=session_factory, store=store, collect=collect_override
    )
    run_pipeline(session_factory, run_id, FakeRunner(), emit=emit, collect=hook)
    return lines


def _revs(session_factory, target_id):
    with session_factory() as s:
        return [rev for rev, _count in revisions.list_revisions_with_file_counts(s, target_id)]


def test_the_driver_still_takes_exactly_one_step_boundary_callable():
    """DESIGN.md §13: the driver keeps one injection point. Sync-out composes
    behind `collect`; it must not arrive as a second parameter."""
    params = inspect.signature(run_pipeline).parameters
    assert list(params) == ["session_factory", "run_id", "runner", "emit", "collect"]
    assert not any("sync" in name for name in params)


def test_a_run_on_a_fresh_target_baselines_then_commits_the_runs_change(
    run_env, session_factory
):
    """User story 22: revision 1 is the tree the run *inherited*, so the run's
    own revision describes what the run did."""
    run_id, target_id, workspace = run_env
    store = FakeStorage()
    tests_dir = workspace / "apps" / "demo" / "tests" / "checkout"

    # The baseline is taken before the pipeline starts, so capture it first...
    lines: list[str] = []
    launcher.ensure_baseline_revision(
        run_id, lines.append, session_factory=session_factory, store=store
    )
    baseline = _revs(session_factory, target_id)
    assert [r.rev for r in baseline] == [1]
    assert baseline[0].parent_rev is None
    assert baseline[0].produced_by_run_id is None  # it is not the run's work

    # ...then let one step change the tree.
    class ChangesOnGenerate(FakeRunner):
        def run_step(self, ctx, emit):
            if ctx.step is Step.GENERATE:
                (tests_dir / "generated.spec.ts").write_text("// generated\n")
            return super().run_step(ctx, emit)

    hook = launcher.make_step_boundary_hook(
        lines.append, session_factory=session_factory, store=store
    )
    run_pipeline(session_factory, run_id, ChangesOnGenerate(), collect=hook)

    revs = _revs(session_factory, target_id)
    assert [r.rev for r in revs] == [2, 1]
    assert revs[0].parent_rev == 1
    assert revs[0].produced_by_run_id == run_id
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


def test_a_five_step_run_over_a_tree_that_changes_once_commits_one_revision(
    run_env, session_factory
):
    """Three of the five steps routinely change no tracked file, so `rev` must
    count real changes rather than counting steps."""
    run_id, target_id, workspace = run_env
    store = FakeStorage()
    tests_dir = workspace / "apps" / "demo" / "tests" / "checkout"

    class ChangesOnce(FakeRunner):
        def run_step(self, ctx, emit):
            if ctx.step is Step.GENERATE:
                (tests_dir / "one.spec.ts").write_text("// one\n")
            return super().run_step(ctx, emit)

    lines: list[str] = []
    launcher.ensure_baseline_revision(
        run_id, lines.append, session_factory=session_factory, store=store
    )
    hook = launcher.make_step_boundary_hook(
        lines.append, session_factory=session_factory, store=store
    )
    run_pipeline(session_factory, run_id, ChangesOnce(), collect=hook)

    assert len(STEP_ORDER) == 5
    assert [r.rev for r in _revs(session_factory, target_id)] == [2, 1]


def test_a_run_that_changes_the_tree_twice_commits_two_chained_revisions(
    run_env, session_factory
):
    run_id, target_id, workspace = run_env
    store = FakeStorage()
    tests_dir = workspace / "apps" / "demo" / "tests" / "checkout"

    class ChangesTwice(FakeRunner):
        def run_step(self, ctx, emit):
            if ctx.step is Step.GENERATE:
                (tests_dir / "gen.spec.ts").write_text("// generated\n")
            if ctx.step is Step.HEAL:
                (tests_dir / "gen.spec.ts").write_text("// healed\n")
            return super().run_step(ctx, emit)

    lines: list[str] = []
    launcher.ensure_baseline_revision(
        run_id, lines.append, session_factory=session_factory, store=store
    )
    hook = launcher.make_step_boundary_hook(
        lines.append, session_factory=session_factory, store=store
    )
    run_pipeline(session_factory, run_id, ChangesTwice(), collect=hook)

    # Baseline, then generate's tree, then heal's tree -- chained.
    revs = _revs(session_factory, target_id)
    assert [r.rev for r in revs] == [3, 2, 1]
    assert revs[0].parent_rev == 2
    assert revs[1].parent_rev == 1
    assert {r.produced_by_run_id for r in revs[:2]} == {run_id}
    assert revs[2].produced_by_run_id is None  # the baseline
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


def test_a_run_on_a_target_that_already_has_a_head_does_not_re_baseline(
    run_env, session_factory
):
    run_id, target_id, workspace = run_env
    store = FakeStorage()

    _drive(session_factory, run_id, store)
    after_first = [r.rev for r in _revs(session_factory, target_id)]

    with session_factory() as s:
        second = repo.start_run(s, target_id=target_id, story_id="SCRUM-1", mode="full")
        second_id = second.id
    _drive(session_factory, second_id, store)

    # Nothing changed the tree in either run, so the baseline is still the head.
    assert after_first == [1]
    assert [r.rev for r in _revs(session_factory, target_id)] == [1]


def test_a_blob_store_whose_upload_raises_leaves_no_revisions_and_completes(
    run_env, session_factory
):
    """The phase's load-bearing promise: scaffolding for a future phase can
    never cost a run today."""
    run_id, target_id, _ = run_env

    class ExplodingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    lines = _drive(session_factory, run_id, ExplodingStorage())

    with session_factory() as s:
        assert list(s.scalars(repo.select(Revision))) == []
        assert list(s.scalars(repo.select(FileIndex))) == []
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("object store is down" in line for line in lines)


def test_an_artifact_collector_that_raises_does_not_prevent_the_revision_commit(
    run_env, session_factory
):
    """The driver wraps the whole hook in one best-effort try/except, so without
    per-half isolation a failing collector would silently skip sync-out."""
    run_id, target_id, _ = run_env
    store = FakeStorage()

    def exploding_collect(run_id, step):
        raise RuntimeError("artifact sweep failed")

    lines = _drive(session_factory, run_id, store, collect_override=exploding_collect)

    assert [r.rev for r in _revs(session_factory, target_id)] == [1]
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("artifact sweep failed" in line for line in lines)


def test_a_revision_write_that_raises_does_not_prevent_artifact_collection(
    run_env, session_factory
):
    run_id, _, _ = run_env
    collected: list[Step] = []

    class ExplodingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    def recording_collect(run_id, step):
        collected.append(step)

    lines = _drive(
        session_factory,
        run_id,
        ExplodingStorage(),
        collect_override=recording_collect,
    )

    assert collected == list(STEP_ORDER), "artifacts are swept at every boundary"
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("object store is down" in line for line in lines)


def test_artifacts_are_collected_before_the_revision_snapshot(run_env, session_factory):
    """Existing behavior runs first and is never delayed by new work."""
    run_id, _, workspace = run_env
    order: list[str] = []
    tests_dir = workspace / "apps" / "demo" / "tests" / "checkout"

    class RecordingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            order.append("revision")
            super().put_file(key, path, content_type)

    def recording_collect(run_id, step):
        order.append("artifacts")

    store = RecordingStorage()
    lines: list[str] = []
    launcher.ensure_baseline_revision(
        run_id, lines.append, session_factory=session_factory, store=store
    )
    order.clear()  # the baseline is before the pipeline; only boundaries matter
    (tests_dir / "changed.spec.ts").write_text("// changed\n")
    hook = launcher.make_step_boundary_hook(
        lines.append,
        session_factory=session_factory,
        store=store,
        collect=recording_collect,
    )
    run_pipeline(session_factory, run_id, FakeRunner(), collect=hook)

    assert order[0] == "artifacts"
    assert "revision" in order


def test_both_halves_report_their_failures_to_the_runs_log_stream(
    run_env, session_factory
):
    run_id, _, _ = run_env

    class ExplodingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("blobs are gone")

    def exploding_collect(run_id, step):
        raise RuntimeError("artifacts are gone")

    lines = _drive(
        session_factory,
        run_id,
        ExplodingStorage(),
        collect_override=exploding_collect,
    )

    assert any("artifacts are gone" in line for line in lines)
    assert any("blobs are gone" in line for line in lines)
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


def test_a_failed_baseline_does_not_prevent_the_run(run_env, session_factory):
    run_id, _, _ = run_env

    class ExplodingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    lines: list[str] = []
    launcher.ensure_baseline_revision(
        run_id, lines.append, session_factory=session_factory, store=ExplodingStorage()
    )
    run_pipeline(session_factory, run_id, FakeRunner(), collect=lambda *_: None)

    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("object store is down" in line for line in lines)
