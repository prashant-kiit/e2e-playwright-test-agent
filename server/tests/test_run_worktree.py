"""A run works in its own worktree, built from the database and thrown away.

Driven through the launcher's composition and `run_pipeline` with a FakeRunner,
the shared fake blob store and the Postgres fixture -- the highest seam
available, and in P3 it proves more than it did in P2 because the run now
*starts* from the database.

What this pins down: a previous run's crash cannot contaminate the next one's
output, disk use is bounded by live runs rather than by history, and a target
with no head revision fails loudly instead of running against nothing.
"""

from __future__ import annotations

import inspect

import pytest

from app import launcher, repo, revisions
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.models import AppLock
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    """A committed revision 1, a target, a run, and run/worktree dirs apart."""
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))
    monkeypatch.setenv("QA_RUNNER", "fake")
    store = FakeStorage()
    source = make_worktree(tmp_path / "source")
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        revisions.commit_revision(s, target, store, source, author="operator")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        return run.id, run.run_key, target.id, store


def _run(session_factory, run_id, store, runner=None, *, emit=None):
    """Hydrate, drive the pipeline, tear down -- the launcher's composition."""
    lines: list[str] = []
    emit = emit or lines.append
    launcher.run_with_worktree(
        run_id,
        emit,
        runner or FakeRunner(),
        session_factory=session_factory,
        store=store,
    )
    return lines


def _status(session_factory, run_id):
    with session_factory() as s:
        return repo.get_run(s, run_id).status


# --- the driver keeps exactly one injection point -------------------------

def test_the_driver_still_takes_exactly_one_step_boundary_callable():
    """DESIGN.md §13. Hydrate and teardown run in the launcher *around* the
    pipeline; neither arrives as a driver parameter."""
    params = inspect.signature(run_pipeline).parameters
    assert list(params) == ["session_factory", "run_id", "runner", "emit", "collect"]
    assert not any("hydrate" in name or "sync" in name for name in params)


def test_hydrate_ingest_and_teardown_are_plain_functions_the_launcher_composes():
    """P4 moves them into a container: a change of where they run, not what."""
    from app.sandbox import hydrate as hyd

    for fn in (hyd.hydrate, hyd.materialize, hyd.install_dependencies, hyd.teardown):
        assert inspect.isfunction(fn)


# --- the run works in its own worktree ------------------------------------

def test_each_run_works_in_its_own_worktree(run_env, session_factory, tmp_path):
    run_id, run_key, target_id, store = run_env
    seen: list[str] = []

    class RecordingRunner(FakeRunner):
        def run_step(self, ctx, emit):
            seen.append(str(ctx.worktree))
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, RecordingRunner())

    assert seen, "the runner saw at least one step"
    assert set(seen) == {str(tmp_path / "worktrees" / run_key)}


def test_two_runs_of_the_same_target_get_different_worktrees(
    run_env, session_factory, tmp_path
):
    """A crashed run's half-written files cannot be inherited by the next one."""
    run_id, run_key, target_id, store = run_env
    first: list[str] = []

    class RecordingRunner(FakeRunner):
        def run_step(self, ctx, emit):
            first.append(str(ctx.worktree))
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, RecordingRunner())
    with session_factory() as s:
        second = repo.start_run(s, target_id=target_id, story_id="SCRUM-1", mode="full")
        second_id, second_key = second.id, second.run_key
    second_seen: list[str] = []

    class RecordingAgain(FakeRunner):
        def run_step(self, ctx, emit):
            second_seen.append(str(ctx.worktree))
            return super().run_step(ctx, emit)

    _run(session_factory, second_id, store, RecordingAgain())

    assert set(first) != set(second_seen)
    assert run_key != second_key


def test_the_worktree_holds_the_head_revisions_tree(run_env, session_factory):
    run_id, run_key, target_id, store = run_env
    found: list[set[str]] = []

    class Peeking(FakeRunner):
        def run_step(self, ctx, emit):
            if ctx.step is Step.READ_STORY:
                found.append(
                    {
                        p.relative_to(ctx.worktree).as_posix()
                        for p in ctx.worktree.rglob("*")
                        if p.is_file()
                    }
                )
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, Peeking())

    assert "seed.spec.ts" in found[0]
    assert "user-stories/SCRUM-1-checkout.md" in found[0]
    assert "playwright.config.ts" in found[0]


# --- no head revision: fail immediately -----------------------------------

def test_a_run_whose_target_has_no_head_revision_fails_immediately(
    session_factory, tmp_path, monkeypatch
):
    """The P2 baseline-from-disk hook is gone: there is no disk to baseline
    from, and every target gets revision 1 when it is created."""
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        run_id, target_id = run.id, target.id

    attempted: list[Step] = []

    class ShouldNotRun(FakeRunner):
        def run_step(self, ctx, emit):
            attempted.append(ctx.step)
            return super().run_step(ctx, emit)

    lines = _run(session_factory, run_id, FakeStorage(), ShouldNotRun())

    assert attempted == [], "no step may be attempted without a tree"
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "no head revision" in (run.error or "")
        assert s.get(AppLock, target_id) is None, "the lock is freed"
    assert any("no head revision" in line for line in lines)


def test_the_baseline_from_disk_hook_is_gone():
    """It conflated the tree a run inherited with the tree it produced, and in
    P3 there is no disk to baseline from at all."""
    assert not hasattr(launcher, "ensure_baseline_revision")


def test_a_corrupt_blob_fails_the_run_before_any_step(run_env, session_factory):
    """No run burns tokens against a tree we cannot verify."""
    run_id, run_key, target_id, store = run_env
    for key in list(store.objects):
        store.objects[key] = (b"tampered", "application/octet-stream")
    attempted: list[Step] = []

    class ShouldNotRun(FakeRunner):
        def run_step(self, ctx, emit):
            attempted.append(ctx.step)
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, ShouldNotRun())

    assert attempted == []
    assert _status(session_factory, run_id) is RunStatus.FAILED


# --- teardown at every terminal state and on pause -------------------------

def test_teardown_removes_the_worktree_when_the_run_completes(
    run_env, session_factory, tmp_path
):
    run_id, run_key, _target_id, store = run_env

    _run(session_factory, run_id, store)

    assert _status(session_factory, run_id) is RunStatus.COMPLETED
    assert not (tmp_path / "worktrees" / run_key).exists()


def test_teardown_removes_the_worktree_when_the_run_fails(
    run_env, session_factory, tmp_path
):
    run_id, run_key, _target_id, store = run_env

    _run(session_factory, run_id, store, FakeRunner(fail_on=Step.EXPLORE))

    assert _status(session_factory, run_id) is RunStatus.FAILED
    assert not (tmp_path / "worktrees" / run_key).exists()


def test_teardown_removes_the_worktree_when_the_run_is_stopped(
    run_env, session_factory, tmp_path
):
    """Stop is honoured at the next step boundary, which is where the worktree
    stops being needed."""
    run_id, run_key, _target_id, store = run_env

    class StopsAfterPlan(FakeRunner):
        def run_step(self, ctx, emit):
            result = super().run_step(ctx, emit)
            if ctx.step is Step.PLAN:
                with session_factory() as s:
                    repo.request_stop(s, ctx.run_id)
            return result

    _run(session_factory, run_id, store, StopsAfterPlan())

    assert _status(session_factory, run_id) is RunStatus.STOPPED
    assert not (tmp_path / "worktrees" / run_key).exists()


def test_teardown_removes_the_worktree_on_pause(run_env, session_factory, tmp_path):
    run_id, run_key, _target_id, store = run_env

    class PausesAfterPlan(FakeRunner):
        def run_step(self, ctx, emit):
            result = super().run_step(ctx, emit)
            if ctx.step is Step.PLAN:
                with session_factory() as s:
                    repo.request_pause(s, ctx.run_id)
            return result

    _run(session_factory, run_id, store, PausesAfterPlan())

    assert _status(session_factory, run_id) is RunStatus.PAUSED
    assert not (tmp_path / "worktrees" / run_key).exists()


def test_a_resumed_run_re_hydrates_from_the_head_and_continues(
    run_env, session_factory, tmp_path
):
    """Mid-step work is lost, which is invariant 4 rather than a regression."""
    run_id, run_key, _target_id, store = run_env

    class PausesAfterPlan(FakeRunner):
        def run_step(self, ctx, emit):
            result = super().run_step(ctx, emit)
            if ctx.step is Step.PLAN:
                with session_factory() as s:
                    repo.request_pause(s, ctx.run_id)
            return result

    _run(session_factory, run_id, store, PausesAfterPlan())
    assert _status(session_factory, run_id) is RunStatus.PAUSED

    with session_factory() as s:
        repo.resume_run(s, run_id)
    resumed_steps: list[Step] = []
    rehydrated: list[bool] = []

    class RecordingRunner(FakeRunner):
        def run_step(self, ctx, emit):
            resumed_steps.append(ctx.step)
            rehydrated.append((ctx.worktree / "seed.spec.ts").is_file())
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, RecordingRunner())

    assert resumed_steps == [Step.EXPLORE, Step.GENERATE, Step.HEAL]
    assert all(rehydrated), "the worktree was rebuilt from the head revision"
    assert _status(session_factory, run_id) is RunStatus.COMPLETED
    assert not (tmp_path / "worktrees" / run_key).exists()


# --- the artifact sweep never sees the worktree ----------------------------

def test_an_artifact_sweep_indexes_no_tracked_file_and_no_node_modules(
    run_env, session_factory, tmp_path
):
    """The reason the worktree is a sibling of the run dir and not a child."""
    from app.models import Artifact

    run_id, run_key, _target_id, store = run_env

    class WritesNodeModules(FakeRunner):
        def run_step(self, ctx, emit):
            pkg = ctx.worktree / "node_modules" / "p"
            pkg.mkdir(parents=True, exist_ok=True)
            (pkg / "index.js").write_text("//\n")
            return super().run_step(ctx, emit)

    _run(session_factory, run_id, store, WritesNodeModules())

    with session_factory() as s:
        keys = [a.s3_key for a in s.scalars(repo.select(Artifact))]
    assert keys, "the run dir's own output is still collected"
    assert not any("node_modules" in k for k in keys)
    assert not any("seed.spec.ts" in k for k in keys)
    assert not any("playwright.config.ts" in k for k in keys)
