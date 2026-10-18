"""Orchestrator driver tests, using the FakeRunner (no Claude Code, no tokens)."""

import pytest

from app import repo
from app.domain.status import RunStatus
from app.domain.steps import STEP_ORDER, Step
from app.models import AppLock, RunStep
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    """A project+target+PENDING run and an isolated runs dir."""
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path))
    with session_factory() as s:
        p = repo.create_project(s, name="demo")
        t = repo.create_target(s, project_id=p.id, app="practice-target", name="Practice")
        run = repo.start_run(s, target_id=t.id, story_id="SCRUM-201", mode="full")
        run_id, run_key = run.id, run.run_key
    return run_id, run_key, tmp_path


def _steps_by_name(session_factory, run_id):
    with session_factory() as s:
        rows = s.query(RunStep).filter(RunStep.run_id == run_id).all()
        return {r.step: r.status for r in rows}


def test_happy_path_completes_all_steps_and_releases_lock(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    lines: list[str] = []
    run_pipeline(session_factory, run_id, FakeRunner(), emit=lines.append)

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.last_completed_step is Step.HEAL
        assert run.current_step is None
        assert s.get(AppLock, run.target_id) is None  # lock released

    statuses = _steps_by_name(session_factory, run_id)
    assert all(statuses[step] == "completed" for step in STEP_ORDER)
    # One placeholder artifact file per step landed in the run dir.
    produced = {p.stem for p in (runs_dir / run_key).glob("*.txt")}
    assert produced == {s.value for s in STEP_ORDER}
    assert any("completed" in ln for ln in lines)


def test_failure_midway_fails_run_and_releases_lock(run_env, session_factory):
    run_id, _, _ = run_env
    run_pipeline(session_factory, run_id, FakeRunner(fail_on=Step.GENERATE))

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "generate" in (run.error or "")
        assert s.get(AppLock, run.target_id) is None  # freed despite failure

    statuses = _steps_by_name(session_factory, run_id)
    assert statuses[Step.READ_STORY] == "completed"
    assert statuses[Step.PLAN] == "completed"
    assert statuses[Step.EXPLORE] == "completed"
    assert statuses[Step.GENERATE] == "failed"
    assert Step.HEAL not in statuses  # never reached


def test_runner_crash_is_contained(run_env, session_factory):
    run_id, _, _ = run_env

    class Boom:
        def run_step(self, ctx, emit):
            raise RuntimeError("kaboom")

    run_pipeline(session_factory, run_id, Boom())
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "crashed" in (run.error or "")
        assert s.get(AppLock, run.target_id) is None


def test_resume_starts_after_last_completed_step(run_env, session_factory):
    run_id, run_key, runs_dir = run_env
    # Pretend steps 1-2 already ran: mark PLAN complete.
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.start_step(s, run_id, Step.READ_STORY)
        repo.complete_step(s, run_id, Step.READ_STORY)
        repo.start_step(s, run_id, Step.PLAN)
        repo.complete_step(s, run_id, Step.PLAN)
        # back to a resumable state
        run = repo.get_run(s, run_id)
        run.status = RunStatus.PAUSED
        s.commit()

    lines: list[str] = []
    run_pipeline(session_factory, run_id, FakeRunner(), emit=lines.append)

    # Only explore/generate/heal should have produced artifacts this time.
    produced = {p.stem for p in (runs_dir / run_key).glob("*.txt")}
    assert produced == {Step.EXPLORE.value, Step.GENERATE.value, Step.HEAL.value}
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.COMPLETED
    assert any("begin at explore" in ln for ln in lines)
