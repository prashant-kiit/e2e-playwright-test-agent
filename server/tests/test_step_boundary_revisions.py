"""Runs commit revisions at step boundaries, through the launcher's composition.

These drive a whole run through the launcher and `run_pipeline` with a
FakeRunner, the shared fake blob store and the Postgres fixture -- the highest
seam available. The run now *starts* from the database, so one test exercises
hydrate, the step-boundary composition and the revision commit in one pass.
Prior art: test_artifacts.py, which does the same for the artifact half.

The driver still takes exactly one step-boundary callable; that is asserted in
test_run_worktree.py, because adding a second parameter is the thing
DESIGN.md §13 names as not to do.
"""

from __future__ import annotations

import pytest

from app import launcher, repo, revisions
from app.domain.status import RunStatus
from app.domain.steps import STEP_ORDER, Step
from app.models import FileIndex, Revision
from app.orchestrator.fake import FakeRunner
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    """Revision 1 committed, a target, a run, and run/worktree dirs apart."""
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
        return run.id, target.id, store


def _drive(session_factory, run_id, store, runner=None, *, collect_override=None):
    """Hydrate, run the whole pipeline with the real composed hook, tear down."""
    lines: list[str] = []
    launcher.run_with_worktree(
        run_id,
        lines.append,
        runner or FakeRunner(),
        session_factory=session_factory,
        store=store,
        collect=collect_override,
    )
    return lines


def _revs(session_factory, target_id):
    with session_factory() as s:
        return [rev for rev, _count in revisions.list_revisions_with_file_counts(s, target_id)]


class _SharesBlobs(FakeStorage):
    """A fake store over another one's objects.

    Hydrate *reads* blobs, so a store that misbehaves on write still has to
    hand back the revision the run starts from -- otherwise the run fails
    before any step and the test proves nothing about step boundaries.
    """

    def __init__(self, seeded: FakeStorage) -> None:
        super().__init__()
        self.objects = seeded.objects


class _ChangesOn(FakeRunner):
    """A fake runner that writes a test file into the worktree on given steps."""

    def __init__(self, changes: dict[Step, str], **kw) -> None:
        super().__init__(**kw)
        self.changes = changes

    def run_step(self, ctx, emit):
        text = self.changes.get(ctx.step)
        if text is not None:
            path = ctx.worktree / "tests" / "checkout" / "generated.spec.ts"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)
        return super().run_step(ctx, emit)


# --- what a run commits ---------------------------------------------------

def test_a_run_that_changes_nothing_commits_no_revision(run_env, session_factory):
    """Revision 1 came with the target, so a run that changes nothing leaves
    the head where it was -- there is no baseline-from-disk to add a second."""
    run_id, target_id, store = run_env

    _drive(session_factory, run_id, store)

    assert [r.rev for r in _revs(session_factory, target_id)] == [1]
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


def test_a_five_step_run_over_a_tree_that_changes_once_commits_one_revision(
    run_env, session_factory
):
    """Three of the five steps routinely change no tracked file, so `rev` must
    count real changes rather than counting steps."""
    run_id, target_id, store = run_env

    _drive(session_factory, run_id, store, _ChangesOn({Step.GENERATE: "// one\n"}))

    assert len(STEP_ORDER) == 5
    revs = _revs(session_factory, target_id)
    assert [r.rev for r in revs] == [2, 1]
    assert revs[0].parent_rev == 1
    assert revs[0].produced_by_run_id == run_id


def test_a_run_that_changes_the_tree_twice_commits_two_chained_revisions(
    run_env, session_factory
):
    run_id, target_id, store = run_env

    _drive(
        session_factory,
        run_id,
        store,
        _ChangesOn({Step.GENERATE: "// generated\n", Step.HEAL: "// healed\n"}),
    )

    revs = _revs(session_factory, target_id)
    assert [r.rev for r in revs] == [3, 2, 1]
    assert revs[0].parent_rev == 2
    assert revs[1].parent_rev == 1
    assert {r.produced_by_run_id for r in revs[:2]} == {run_id}
    assert revs[2].produced_by_run_id is None  # revision 1 came with the target
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED


def test_the_committed_revision_contains_the_file_the_run_wrote(run_env, session_factory):
    run_id, target_id, store = run_env

    _drive(session_factory, run_id, store, _ChangesOn({Step.GENERATE: "// gen\n"}))

    head = _revs(session_factory, target_id)[0]
    with session_factory() as s:
        paths = {row.path for row in revisions.list_files(s, head.id)}
    assert "tests/checkout/generated.spec.ts" in paths


def test_a_second_run_starts_from_the_first_runs_revision(run_env, session_factory):
    """The worktree is thrown away; the revision is what carries forward."""
    run_id, target_id, store = run_env
    _drive(session_factory, run_id, store, _ChangesOn({Step.GENERATE: "// first\n"}))

    with session_factory() as s:
        second = repo.start_run(s, target_id=target_id, story_id="SCRUM-1", mode="full")
        second_id = second.id
    inherited: list[str] = []

    class ReadsWhatItInherited(FakeRunner):
        def run_step(self, ctx, emit):
            if ctx.step is Step.READ_STORY:
                inherited.append(
                    (ctx.worktree / "tests" / "checkout" / "generated.spec.ts").read_text()
                )
            return super().run_step(ctx, emit)

    _drive(session_factory, second_id, store, ReadsWhatItInherited())

    assert inherited == ["// first\n"]


# --- the step-boundary halves -------------------------------------------
#
# P2's failure policy, unchanged here: artifact collection and the revision
# commit each catch their own failures and a run still completes. P3-05 inverts
# the revision half -- a failed ingest must fail the run -- which is that
# ticket's whole point and is asserted there.

def test_artifacts_are_collected_before_the_revision_snapshot(run_env, session_factory):
    """Existing behavior runs first and is never delayed by new work."""
    run_id, _target_id, store = run_env
    order: list[str] = []

    class RecordingStorage(_SharesBlobs):
        def put_file(self, key, path, content_type=None):
            order.append("revision")
            super().put_file(key, path, content_type)

    _drive(
        session_factory,
        run_id,
        RecordingStorage(store),
        _ChangesOn({Step.GENERATE: "// changed\n"}),
        collect_override=lambda run_id, step: order.append("artifacts"),
    )

    assert order[0] == "artifacts"
    assert "revision" in order


def test_an_artifact_collector_that_raises_does_not_prevent_the_revision_commit(
    run_env, session_factory
):
    """Without per-half isolation a failing collector would silently skip the
    revision commit, and vice versa."""
    run_id, target_id, store = run_env

    def exploding_collect(run_id, step):
        raise RuntimeError("artifact sweep failed")

    lines = _drive(
        session_factory,
        run_id,
        store,
        _ChangesOn({Step.GENERATE: "// gen\n"}),
        collect_override=exploding_collect,
    )

    assert [r.rev for r in _revs(session_factory, target_id)] == [2, 1]
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("artifact sweep failed" in line for line in lines)


def test_a_revision_write_that_raises_does_not_prevent_artifact_collection(
    run_env, session_factory
):
    run_id, _target_id, store = run_env
    collected: list[Step] = []

    class Exploding(_SharesBlobs):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    lines = _drive(
        session_factory,
        run_id,
        Exploding(store),
        _ChangesOn({Step.GENERATE: "// gen\n"}),
        collect_override=lambda run_id, step: collected.append(step),
    )

    assert collected == list(STEP_ORDER), "artifacts are swept at every boundary"
    with session_factory() as s:
        assert list(s.scalars(repo.select(Revision).where(Revision.rev > 1))) == []
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("object store is down" in line for line in lines)


def test_both_halves_report_their_failures_to_the_runs_log_stream(
    run_env, session_factory
):
    run_id, _target_id, store = run_env

    class Exploding(_SharesBlobs):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("blobs are gone")

    def exploding_collect(run_id, step):
        raise RuntimeError("artifacts are gone")

    lines = _drive(
        session_factory,
        run_id,
        Exploding(store),
        _ChangesOn({Step.GENERATE: "// gen\n"}),
        collect_override=exploding_collect,
    )

    assert any("artifacts are gone" in line for line in lines)
    assert any("blobs are gone" in line for line in lines)


def test_a_failed_revision_commit_leaves_the_previous_head_intact(
    run_env, session_factory
):
    """Blob before row (invariant 3): a failure may leave an unreferenced blob,
    never a revision pointing at bytes that are not there."""
    run_id, target_id, store = run_env

    class Exploding(_SharesBlobs):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    _drive(
        session_factory,
        run_id,
        Exploding(store),
        _ChangesOn({Step.GENERATE: "// gen\n"}),
    )

    assert [r.rev for r in _revs(session_factory, target_id)] == [1]
    with session_factory() as s:
        orphans = [
            row for row in s.scalars(repo.select(FileIndex))
            if row.path == "tests/checkout/generated.spec.ts"
        ]
    assert orphans == [], "no partial file_index"
