"""M3: pause / resume / stop at step boundaries, and the reaper vs. paused runs."""

from datetime import timedelta

import pytest

from app import repo
from app.domain import lease
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.models import AppLock
from app.orchestrator.driver import run_pipeline
from app.orchestrator.fake import FakeRunner


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
    monkeypatch.setenv("QA_RUNS_DIR", str(tmp_path))
    with session_factory() as s:
        p = repo.create_project(s, name="demo")
        t = repo.create_target(s, project_id=p.id, app="practice-target", name="Practice")
        run = repo.start_run(s, target_id=t.id, story_id="SCRUM-201", mode="full")
        return run.id, run.run_key, tmp_path, t.id


class _HookRunner:
    """Wraps FakeRunner and fires a hook after a chosen step, to simulate an
    operator hitting pause/stop from the API mid-run."""

    def __init__(self, hook):
        self._fake = FakeRunner()
        self._hook = hook

    def run_step(self, ctx, emit):
        result = self._fake.run_step(ctx, emit)
        self._hook(ctx.step)
        return result


def _artifacts(runs_dir, run_key):
    return {p.stem for p in (runs_dir / run_key).glob("*.txt")}


def test_pause_halts_after_current_step_and_keeps_lock(run_env, session_factory):
    run_id, run_key, runs_dir, target_id = run_env

    def hook(step):
        if step is Step.EXPLORE:
            with session_factory() as s:
                repo.request_pause(s, run_id)

    run_pipeline(session_factory, run_id, _HookRunner(hook))

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.PAUSED
        assert run.last_completed_step is Step.EXPLORE
        assert run.lease_expires_at is None
        assert s.get(AppLock, target_id) is not None  # lock still held while paused
    assert _artifacts(runs_dir, run_key) == {
        Step.READ_STORY.value,
        Step.PLAN.value,
        Step.EXPLORE.value,
    }


def test_resume_continues_from_checkpoint_to_completion(run_env, session_factory):
    run_id, run_key, runs_dir, target_id = run_env

    def pause_hook(step):
        if step is Step.PLAN:
            with session_factory() as s:
                repo.request_pause(s, run_id)

    run_pipeline(session_factory, run_id, _HookRunner(pause_hook))
    with session_factory() as s:
        assert repo.get_run(s, run_id).status is RunStatus.PAUSED

    # Resume: clear flags, re-run; it should begin at EXPLORE and finish.
    with session_factory() as s:
        repo.resume_run(s, run_id)
    run_pipeline(session_factory, run_id, FakeRunner())

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.last_completed_step is Step.HEAL
        assert s.get(AppLock, target_id) is None  # released on completion
    assert _artifacts(runs_dir, run_key) == {s.value for s in Step}


def test_stop_at_boundary_stops_and_releases_lock(run_env, session_factory):
    run_id, run_key, runs_dir, target_id = run_env

    def hook(step):
        if step is Step.PLAN:
            with session_factory() as s:
                repo.request_stop(s, run_id)

    run_pipeline(session_factory, run_id, _HookRunner(hook))

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.STOPPED
        assert run.last_completed_step is Step.PLAN
        assert s.get(AppLock, target_id) is None  # freed on stop
    assert _artifacts(runs_dir, run_key) == {Step.READ_STORY.value, Step.PLAN.value}


def test_stop_a_pending_run_is_immediate(run_env, session_factory):
    run_id, _, _, target_id = run_env
    with session_factory() as s:
        run = repo.request_stop(s, run_id)
        assert run.status is RunStatus.STOPPED
        assert s.get(AppLock, target_id) is None


def test_stop_a_paused_run_is_immediate(run_env, session_factory):
    run_id, _, _, target_id = run_env
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.pause_run(s, run_id)
        assert repo.get_run(s, run_id).status is RunStatus.PAUSED
    with session_factory() as s:
        run = repo.request_stop(s, run_id)
        assert run.status is RunStatus.STOPPED
        assert s.get(AppLock, target_id) is None


def test_reaper_does_not_touch_a_paused_run(run_env, session_factory):
    run_id, _, _, target_id = run_env
    t0 = lease.utcnow()
    with session_factory() as s:
        repo.begin_run(s, run_id, now=t0)
        repo.pause_run(s, run_id)  # paused; lock lease stays at its old value
    future = t0 + lease.DEFAULT_LEASE_TTL + timedelta(seconds=10)
    with session_factory() as s:
        reaped = repo.reap_expired(s, now=future)
        assert reaped == []  # paused run is a deliberate hold, not a crash
        assert repo.get_run(s, run_id).status is RunStatus.PAUSED
        assert s.get(AppLock, target_id) is not None
