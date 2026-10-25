"""A wedged agent stops being unbounded.

Before this there was no step timeout, no run timeout and no token budget: a
Claude session that opened a browser and hung held a browser and a billing meter
until somebody noticed, and the reaper only freed the *lock* -- the work kept
running. §6 calls the wall-clock timeout the most expensive failure mode in the
system.

    per-step wall clock   the runner, around the CLI subprocess
                          -> the step fails "timed out", the run fails
    per-run wall clock    the deadline, reconciled by the reaper
                          -> the run fails, naming the timeout
    per-run spend         the runner, from the `result` events it already parses
                          -> the run fails, naming the budget

Every breach is a `failed` run with an explicit reason and the **last committed
revision intact** -- invariant 4, unchanged. So each test here checks all three:
the status, the reason, and that the head revision survived.
"""

from __future__ import annotations

import time
from datetime import timedelta

import pytest

from app import launcher, repo, revisions
from app.domain import lease
from app.domain.status import RunStatus
from app.domain.steps import Step
from app.models import AppLock
from app.orchestrator import limits as limits_module
from app.orchestrator.bus import InMemoryLogBus
from app.orchestrator.fake import FakeRunner
from app.orchestrator.runner import StepResult
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def ctx(tmp_path):
    """A StepContext: the limits look at none of it, and the inner runner does."""
    from app.orchestrator.runner import StepContext
    from tests.target_helpers import CONFIG

    return StepContext(
        run_id=1,
        run_key="rk",
        app="demo",
        story_id="SCRUM-1",
        mode="full",
        step=Step.PLAN,
        run_dir=tmp_path / "run",
        worktree=tmp_path / "wt",
        target=CONFIG,
        prev_session_id=None,
    )


@pytest.fixture()
def run_env(session_factory, tmp_path, monkeypatch):
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


def _drive(session_factory, run_id, store, runner):
    log = InMemoryLogBus()
    launcher.drive_run(
        run_id,
        runner=runner,
        log=log,
        session_factory=session_factory,
        store=store,
    )
    return log.read_from(run_id, 0)[0]


def _head(session_factory, target_id) -> int:
    with session_factory() as s:
        return revisions.head_revision(s, target_id).rev


class _Sleeps(FakeRunner):
    """A runner that outlives any patience, and records being told to stop."""

    def __init__(self, seconds: float = 0.5, **kw) -> None:
        super().__init__(**kw)
        self.seconds = seconds
        self.aborted = False

    def run_step(self, ctx, emit):
        time.sleep(self.seconds)
        return super().run_step(ctx, emit)

    def abort(self) -> None:
        self.aborted = True


class _Spends(FakeRunner):
    """A runner reporting a cost per step, as the real one parses from `result`."""

    def __init__(self, per_step: float, **kw) -> None:
        super().__init__(**kw)
        self.per_step = per_step
        self.last_cost_usd = 0.0

    def run_step(self, ctx, emit):
        self.last_cost_usd = self.per_step
        return super().run_step(ctx, emit)


# --- the limits as a wrapper around a runner ------------------------------

def test_a_step_that_outlives_the_wall_clock_fails_with_timed_out(ctx):
    inner = _Sleeps(seconds=5.0)
    limited = limits_module.LimitedRunner(
        inner, limits_module.RunLimits(step_timeout_s=0.05)
    )
    lines: list[str] = []

    result = limited.run_step(ctx, lines.append)

    assert not result.ok
    assert "timed out" in (result.error or "")
    assert inner.aborted, "the runner was told to kill what it had started"
    assert any("timed out" in line for line in lines)


def test_a_step_inside_the_wall_clock_is_untouched(ctx):
    inner = _Sleeps(seconds=0.0)
    limited = limits_module.LimitedRunner(
        inner, limits_module.RunLimits(step_timeout_s=30.0)
    )

    assert limited.run_step(ctx, lambda _l: None).ok
    assert not inner.aborted


def test_spend_accumulates_across_steps_and_ends_the_run_at_the_budget(ctx):
    inner = _Spends(per_step=0.5)
    limited = limits_module.LimitedRunner(
        inner, limits_module.RunLimits(spend_budget_usd=1.2)
    )

    assert limited.run_step(ctx, lambda _l: None).ok   # 0.5
    assert limited.run_step(ctx, lambda _l: None).ok   # 1.0
    third = limited.run_step(ctx, lambda _l: None)     # 1.5 -> over

    assert not third.ok
    assert "budget" in (third.error or "")
    assert "1.5" in (third.error or "") or "1.50" in (third.error or "")
    assert limited.spent_usd == pytest.approx(1.5)


def test_the_run_deadline_refuses_to_start_another_step(ctx):
    """The runner's half of the run wall clock: the reaper reconciles a run
    nobody is driving, and this stops a run that is still being driven from
    starting a sixth step past its deadline."""
    inner = FakeRunner()
    limited = limits_module.LimitedRunner(
        inner,
        limits_module.RunLimits(run_timeout_s=0.0001),
        started_at=time.monotonic() - 10,
    )

    result = limited.run_step(ctx, lambda _l: None)

    assert not result.ok
    assert "run timed out" in (result.error or "")


def test_the_limits_come_from_the_environment_with_sane_defaults(monkeypatch):
    monkeypatch.delenv("QA_STEP_TIMEOUT_S", raising=False)
    defaults = limits_module.RunLimits.from_env()
    assert defaults.step_timeout_s > 0
    assert defaults.run_timeout_s > defaults.step_timeout_s
    assert defaults.spend_budget_usd > 0

    monkeypatch.setenv("QA_STEP_TIMEOUT_S", "12.5")
    monkeypatch.setenv("QA_SPEND_BUDGET_USD", "3")
    configured = limits_module.RunLimits.from_env()
    assert configured.step_timeout_s == 12.5
    assert configured.spend_budget_usd == 3.0


def test_a_runner_with_nothing_to_abort_is_not_a_problem(ctx):
    """`abort` is optional: a Runner that cannot kill anything is still subject
    to the limit, and the step still fails."""

    class NoAbort:
        def run_step(self, ctx, emit):
            time.sleep(5.0)
            return StepResult(ok=True)

    limited = limits_module.LimitedRunner(
        NoAbort(), limits_module.RunLimits(step_timeout_s=0.05)
    )

    assert not limited.run_step(ctx, lambda _l: None).ok


# --- through a whole run: failed, with a reason, revision intact ----------

def test_a_step_timeout_fails_the_run_frees_the_lock_and_keeps_the_revision(
    run_env, session_factory
):
    run_id, _run_key, target_id, store = run_env
    runner = limits_module.LimitedRunner(
        _Sleeps(seconds=5.0), limits_module.RunLimits(step_timeout_s=0.05)
    )

    lines = _drive(session_factory, run_id, store, runner)

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "timed out" in (run.error or "")
        assert s.get(AppLock, target_id) is None, "the lock is freed"
    assert _head(session_factory, target_id) == 1, "the last revision is intact"
    assert any("timed out" in line for line in lines), "and the log says so"


def test_a_budget_breach_fails_the_run_naming_the_budget(run_env, session_factory):
    run_id, _run_key, target_id, store = run_env
    runner = limits_module.LimitedRunner(
        _Spends(per_step=1.0), limits_module.RunLimits(spend_budget_usd=1.5)
    )

    lines = _drive(session_factory, run_id, store, runner)

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "budget" in (run.error or "")
        assert s.get(AppLock, target_id) is None
    assert _head(session_factory, target_id) == 1
    assert any("budget" in line for line in lines)


def test_the_runs_spend_and_sandbox_seconds_are_recorded(run_env, session_factory):
    """Cost is attributable per run before per-tenant quotas exist."""
    run_id, _run_key, _target_id, store = run_env
    runner = limits_module.LimitedRunner(
        _Spends(per_step=0.25), limits_module.RunLimits()
    )

    _drive(session_factory, run_id, store, runner)

    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.COMPLETED
        assert run.spend_usd == pytest.approx(1.25)  # five steps
        assert run.sandbox_seconds is not None and run.sandbox_seconds >= 0


def test_a_run_that_breached_still_records_what_it_spent(run_env, session_factory):
    run_id, _run_key, _target_id, store = run_env
    runner = limits_module.LimitedRunner(
        _Spends(per_step=1.0), limits_module.RunLimits(spend_budget_usd=1.5)
    )

    _drive(session_factory, run_id, store, runner)

    with session_factory() as s:
        assert repo.get_run(s, run_id).spend_usd == pytest.approx(2.0)


def test_the_configured_runner_is_wrapped_in_the_limits(monkeypatch):
    """A limit only one kind of runner respects is not a limit."""
    monkeypatch.setenv("QA_RUNNER", "fake")
    runner = launcher.make_runner()
    assert isinstance(runner, limits_module.LimitedRunner)
    assert isinstance(runner.inner, FakeRunner)


# --- the reaper's half: a run nobody is driving any more ------------------

def test_the_reaper_fails_a_run_past_the_run_wall_clock(run_env, session_factory):
    """Reconciled rather than noticed: nothing is driving this run, so nothing
    is left to check its own deadline."""
    run_id, _run_key, target_id, _store = run_env
    with session_factory() as s:
        repo.begin_run(s, run_id)
        run = repo.get_run(s, run_id)
        run.created_at = lease.utcnow() - timedelta(hours=4)
        s.commit()

    with session_factory() as s:
        overdue = repo.fail_overdue_runs(s, max_age_s=7200)

    assert overdue == [run_id]
    with session_factory() as s:
        run = repo.get_run(s, run_id)
        assert run.status is RunStatus.FAILED
        assert "timed out" in (run.error or "")
        assert s.get(AppLock, target_id) is None
    assert _head(session_factory, target_id) == 1


def test_a_run_inside_the_wall_clock_is_left_alone(run_env, session_factory):
    run_id, _run_key, _target_id, _store = run_env
    with session_factory() as s:
        repo.begin_run(s, run_id)

    with session_factory() as s:
        assert repo.fail_overdue_runs(s, max_age_s=7200) == []
        assert repo.get_run(s, run_id).status is RunStatus.RUNNING


def test_a_paused_run_is_not_failed_by_the_run_wall_clock(run_env, session_factory):
    """A deliberate pause is not a wedged agent, which is what this bounds."""
    run_id, _run_key, target_id, _store = run_env
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.pause_run(s, run_id)
        run = repo.get_run(s, run_id)
        run.created_at = lease.utcnow() - timedelta(hours=4)
        s.commit()

    with session_factory() as s:
        assert repo.fail_overdue_runs(s, max_age_s=7200) == []
        assert repo.get_run(s, run_id).status is RunStatus.PAUSED
        assert s.get(AppLock, target_id) is not None


def test_the_reaper_loop_reaps_the_overdue_as_well_as_the_leaseless(
    session_factory, monkeypatch
):
    import asyncio

    from app import reaper

    swept: list[int] = []
    monkeypatch.setattr(
        reaper.repo, "fail_overdue_runs", lambda session, **kw: swept.append(1) or []
    )

    async def one_pass():
        task = asyncio.create_task(
            reaper.reaper_loop(interval_s=0.01, session_factory=session_factory)
        )
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(one_pass())

    assert swept


def test_the_reaper_destroys_the_sandbox_of_a_run_it_reaps(session_factory, run_env):
    """A failed run whose container is still burning minutes is the cost this
    limit exists to stop."""
    import asyncio

    from app import reaper

    run_id, _run_key, _target_id, _store = run_env
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.set_sandbox_handle(s, run_id, "qa-run-whatever")
        run = repo.get_run(s, run_id)
        run.created_at = lease.utcnow() - timedelta(hours=4)
        s.commit()
    reaped: list[int] = []

    async def one_pass():
        task = asyncio.create_task(
            reaper.reaper_loop(
                interval_s=0.01,
                session_factory=session_factory,
                reap_sandbox=reaped.append,
            )
        )
        await asyncio.sleep(0.2)
        task.cancel()

    asyncio.run(one_pass())

    assert run_id in reaped


# --- the lock trio is untouched -------------------------------------------

def test_this_ticket_added_nothing_to_the_lock_trio():
    """§5 says to leave it alone; the limits sit beside it, never inside it."""
    import inspect

    for fn in (repo.start_run, repo.pause_run, repo.reap_expired):
        source = inspect.getsource(fn)
        for word in ("budget", "timeout", "spend", "overdue"):
            assert word not in source, f"{fn.__name__} mentions {word}"





# --- the real runner's half: the kill, and where the cost comes from -----

def test_the_real_runner_reports_the_cost_from_the_result_event(ctx, monkeypatch):
    """The budget rides on something the runner already parses, which is why it
    is a budget and not a new accounting system."""
    import json
    import sys

    from app.orchestrator import claude

    event = json.dumps(
        {"type": "result", "is_error": False, "total_cost_usd": 0.42, "session_id": "s1"}
    )
    monkeypatch.setattr(
        claude,
        "step_invocation",
        lambda c, workers="2": (
            [sys.executable, "-c", f"print({event!r})"],
            {},
            ctx.run_dir,
        ),
    )
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    runner = claude.ClaudeRunner()

    result = runner.run_step(ctx, lambda _line: None)

    assert result.ok
    assert runner.last_cost_usd == pytest.approx(0.42)


def test_a_timed_out_step_takes_the_process_group_with_it(ctx, monkeypatch):
    """The CLI spawns node, which spawns a browser. Killing only the process we
    hold would leave the expensive half running, which is the whole failure mode
    the wall clock exists for."""
    import os
    import subprocess
    import sys

    from app.orchestrator import claude

    marker = ctx.run_dir / "child.pid"
    ctx.run_dir.mkdir(parents=True, exist_ok=True)
    # A child that outlives its parent unless the *group* is signalled.
    script = (
        "import os, subprocess, sys, time;"
        f"c = subprocess.Popen([sys.executable, '-c', 'import time; time.sleep(60)']);"
        f"open({str(marker)!r}, 'w').write(str(c.pid));"
        "time.sleep(60)"
    )
    monkeypatch.setattr(
        claude,
        "step_invocation",
        lambda c, workers="2": ([sys.executable, "-c", script], {}, ctx.run_dir),
    )
    limited = limits_module.LimitedRunner(
        claude.ClaudeRunner(), limits_module.RunLimits(step_timeout_s=2.0)
    )

    result = limited.run_step(ctx, lambda _line: None)

    assert not result.ok and "timed out" in (result.error or "")
    child_pid = int(marker.read_text())
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        try:
            os.kill(child_pid, 0)
        except ProcessLookupError:
            break
        time.sleep(0.1)
    else:
        subprocess.run(["kill", "-9", str(child_pid)], check=False)
        pytest.fail(f"the grandchild {child_pid} outlived the step that started it")
