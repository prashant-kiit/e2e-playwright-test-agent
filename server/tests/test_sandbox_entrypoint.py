"""One pipeline, two call sites: a run driven from outside the API process.

P3 was written so that moving a run into a container would be a change of
*where* three functions run and not of *what* they do. This is where that claim
stops being a promise: the same composition is invoked by a module with a
`__main__`, and it produces the same run row, the same step rows, the same
revisions and the same artifacts a thread run produces.

Half of these are therefore behavioural (drive a run out of process, look at the
rows) and half are **structural**, in the style of test_no_repo_mount.py. The
structural half is the one that matters longest: a second pipeline is the
failure mode this phase most tempts, and a second pipeline is invisible to every
behavioural test as long as it happens to behave the same.
"""

from __future__ import annotations

import ast
import inspect
import subprocess
import sys
from pathlib import Path

import pytest

from app import launcher, repo, revisions
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.models import AppLock, Artifact
from app.orchestrator.bus import InMemoryLogBus
from app.orchestrator.fake import FakeRunner
from app.sandbox import run as entrypoint
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target

SERVER_DIR = Path(__file__).resolve().parents[1]


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


class _ChangesTheTree(FakeRunner):
    """Writes one tracked file, so the run has work for ingest to commit.

    A plain FakeRunner changes nothing in the worktree and therefore commits no
    revision, which is correct behaviour and proves nothing about ingest.
    """

    def run_step(self, ctx, emit):
        path = ctx.worktree / "tests" / "checkout" / "generated.spec.ts"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(f"// {ctx.step.value}\n")
        return super().run_step(ctx, emit)


def _out_of_process(session_factory, run_id, store, **kwargs) -> int:
    """The entrypoint, with the two things a container gets from its environment
    -- a database and an object store -- passed in rather than read from env."""
    return entrypoint.main(
        [str(run_id)],
        session_factory=session_factory,
        store=store,
        bus=InMemoryLogBus(),
        **kwargs,
    )


# --- a run driven out of process produces the same rows -------------------

def test_the_entrypoint_drives_a_run_to_completion_and_exits_zero(
    run_env, session_factory, tmp_path
):
    run_id, run_key, target_id, store = run_env

    code = _out_of_process(session_factory, run_id, store, runner=_ChangesTheTree())

    assert code == 0
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.last_completed_step is Step.HEAL
        assert {rs.step for rs in run.steps} == set(Step)
        assert s.get(AppLock, target_id) is None, "the lock is freed"
        assert [a.kind for a in s.scalars(repo.select(Artifact))], "artifacts indexed"
        assert revisions.head_revision(s, target_id).rev > 1, "revisions committed"
    assert not (tmp_path / "worktrees" / run_key).exists(), "torn down"


def test_a_failed_run_exits_non_zero(run_env, session_factory):
    run_id, _run_key, _target_id, store = run_env

    code = _out_of_process(
        session_factory, run_id, store, runner=FakeRunner(fail_on=Step.EXPLORE)
    )

    assert code != 0
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.FAILED


def test_the_log_of_an_out_of_process_run_is_readable_by_cursor(
    run_env, session_factory
):
    """The whole reason the log became a table: the API did not run this."""
    run_id, run_key, _target_id, store = run_env
    bus = InMemoryLogBus()

    entrypoint.main(
        [str(run_id)], session_factory=session_factory, store=store, bus=bus
    )

    lines, _cursor = bus.read_from(run_id, 0)
    assert any(f"run {run_key} completed" in line for line in lines)
    assert bus.is_closed(run_id), "the stream is closed when the run ends"


def test_a_hydrate_failure_out_of_process_fails_before_any_step(
    session_factory, tmp_path, monkeypatch
):
    """Exactly as on the thread path: no tree, no tokens."""
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path / "runs"))
    monkeypatch.setenv("QA_WORKTREES_DIR", str(tmp_path / "worktrees"))
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = create_target(s, project.id, app="demo", name="Demo")
        run = repo.start_run(s, target_id=target.id, story_id="SCRUM-1", mode="full")
        run_id, target_id = run.id, target.id  # no revision 1: nothing to hydrate

    attempted: list[Step] = []

    class ShouldNotRun(FakeRunner):
        def run_step(self, ctx, emit):
            attempted.append(ctx.step)
            return super().run_step(ctx, emit)

    code = _out_of_process(
        session_factory, run_id, FakeStorage(), runner=ShouldNotRun()
    )

    assert code != 0
    assert attempted == []
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "no head revision" in (run.error or "")
        assert s.get(AppLock, target_id) is None


def test_a_failed_ingest_out_of_process_still_fails_the_run(run_env, session_factory):
    """P3's inversion survives the move: a run never reports success having
    dropped its work, wherever the work happened."""
    run_id, _run_key, target_id, store = run_env

    class Exploding(FakeStorage):
        """Hydrate still reads the seeded blobs; every write fails."""

        def __init__(self, seeded):
            super().__init__()
            self.objects = seeded.objects

        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    code = _out_of_process(
        session_factory, run_id, Exploding(store), runner=_ChangesTheTree()
    )

    assert code != 0
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "step boundary failed" in (run.error or "")
        assert revisions.head_revision(s, target_id).rev == 1, "the head is intact"


def test_the_heartbeat_is_taken_inside_the_process_that_runs_the_pipeline(
    run_env, session_factory, monkeypatch
):
    """The reaper's crash detection has to measure the thing that is working."""
    run_id, _run_key, _target_id, store = run_env
    beating: list[int] = []
    real = launcher.heartbeat_during

    def recording(rid, **kwargs):
        beating.append(rid)
        return real(rid, **kwargs)

    monkeypatch.setattr(launcher, "heartbeat_during", recording)

    _out_of_process(session_factory, run_id, store)

    assert beating == [run_id]


# --- structural: one composition, two call sites --------------------------

def _calls(fn) -> list[str]:
    """The dotted names `fn` calls, in source order."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    names: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        target = node.func
        parts: list[str] = []
        while isinstance(target, ast.Attribute):
            parts.append(target.attr)
            target = target.value
        if isinstance(target, ast.Name):
            parts.append(target.id)
        if parts:
            names.append(".".join(reversed(parts)))
    return names


def test_the_composition_is_hydrate_the_pipeline_and_teardown_and_nothing_else():
    """Three function calls and a `finally`, deliberately boring.

    `teardown` stays even though a container is about to be destroyed: it is
    what makes the two call sites the same composition, and it is what keeps
    pause honest.
    """
    calls = _calls(launcher.run_with_worktree)
    composition = [
        name
        for name in calls
        if name in {"hydrate_worktree", "run_pipeline", "hydrate.teardown"}
    ]
    assert composition == ["hydrate_worktree", "run_pipeline", "hydrate.teardown"]


def _referenced(fn) -> set[str]:
    """Every bare name `fn` mentions -- called, passed or assigned."""
    tree = ast.parse(inspect.getsource(fn).lstrip())
    return {node.id for node in ast.walk(tree) if isinstance(node, ast.Name)}


def test_the_thread_launcher_and_the_entrypoint_call_one_composition_function():
    """Not two pipelines that happen to agree.

    The thread launcher hands `drive_run` to a thread rather than calling it, so
    this is about the name each one reaches for, not the call syntax.
    """
    assert "drive_run" in _referenced(launcher.launch_run)
    assert "drive_run" in _referenced(entrypoint.main)


def test_the_entrypoint_composes_nothing_of_its_own():
    """A second pipeline is invisible to every behavioural test for as long as
    it behaves the same, so the assertion is on the source."""
    source = Path(entrypoint.__file__).read_text()
    for forbidden in (
        "hydrate_worktree(",
        "run_pipeline(",
        "teardown(",
        "make_step_boundary_hook(",
        "commit_revision(",
    ):
        assert forbidden not in source, (
            f"the sandbox entrypoint calls {forbidden} itself; it must call the "
            f"one composition function the thread launcher calls"
        )


def test_hydrate_ingest_and_teardown_are_still_plain_composed_functions():
    from app.sandbox import hydrate as hyd

    for fn in (hyd.hydrate, hyd.materialize, hyd.install_dependencies, hyd.teardown):
        assert inspect.isfunction(fn)
    assert inspect.isfunction(launcher.make_ingest)
    assert inspect.isfunction(launcher.hydrate_worktree)


def test_the_driver_still_takes_exactly_one_step_boundary_callable():
    """DESIGN.md §13, re-asserted here because this is the phase that tempts a
    second one: a container needs no extra driver parameter."""
    from app.orchestrator.driver import run_pipeline

    params = inspect.signature(run_pipeline).parameters
    assert list(params) == ["session_factory", "run_id", "runner", "emit", "collect"]


def test_the_module_is_runnable_as_python_m_app_sandbox_run():
    """`python -m app.sandbox.run <run_id>` is the container's command, so the
    module has to be executable and has to refuse a missing argument."""
    proc = subprocess.run(
        [sys.executable, "-m", "app.sandbox.run"],
        cwd=str(SERVER_DIR),
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 2, proc.stderr
    assert "run_id" in (proc.stderr + proc.stdout)
