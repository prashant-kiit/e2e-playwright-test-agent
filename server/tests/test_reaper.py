"""The heartbeat and the reaper -- repo.heartbeat/reap_expired finally have callers.

Before this, a step longer than the 60 s lease TTL ran with an expired lease, so
a healthy run looked dead; and a genuinely dead run held its app until someone
happened to start another one.

These use `session_factory` only, never the `session` fixture as well: both
fixtures truncate on teardown, and a truncate blocks on the other's open
transaction.
"""

from __future__ import annotations

import asyncio
import time
from datetime import timedelta

from app import reaper, repo
from app.domain import lease
from app.domain.status import RunStatus
from app.models import AppLock


def _seed_run(session_factory, *, app="practice-target", story="SCRUM-201"):
    with session_factory() as s:
        project = repo.create_project(s, name="demo")
        target = repo.create_target(s, project_id=project.id, app=app, name="Practice")
        run = repo.start_run(s, target_id=target.id, story_id=story, mode="full")
        return target.id, run.id


def _run_field(session_factory, run_id, field):
    with session_factory() as s:
        return getattr(repo.get_run(s, run_id), field)


def _expire_lease(session_factory, target_id, run_id):
    """Leave the lease in the past, the way a crashed process would."""
    past = lease.utcnow() - lease.DEFAULT_LEASE_TTL
    with session_factory() as s:
        repo.get_run(s, run_id).lease_expires_at = past
        lock = s.get(AppLock, target_id)
        if lock is not None:
            lock.lease_expires_at = past
        s.commit()


def test_heartbeat_during_extends_a_live_runs_lease(session_factory):
    target_id, run_id = _seed_run(session_factory)
    with session_factory() as s:
        repo.begin_run(s, run_id)
    before = _run_field(session_factory, run_id, "lease_expires_at")

    with reaper.heartbeat_during(run_id, interval_s=0.01, session_factory=session_factory):
        _wait_until(
            lambda: _run_field(session_factory, run_id, "lease_expires_at") > before
        )

    assert _run_field(session_factory, run_id, "lease_expires_at") > before


def test_heartbeat_uses_the_default_interval_when_none_is_given(session_factory, monkeypatch):
    """The production path: `heartbeat_during(run_id)` with no explicit interval.

    Every other test here passes `interval_s=0.01`, a float, so the default
    branch was never exercised -- and the default, `lease.DEFAULT_HEARTBEAT`,
    is a **timedelta**, which `Event.wait` cannot use. The resulting TypeError
    was raised by the `while not done.wait(period)` line, outside the loop's
    try, so the daemon heartbeat thread died on its first iteration in silence
    and the lease was never refreshed. Any step longer than the 60 s TTL then
    had its perfectly healthy run reaped -- which is every step of a real agent
    run.

    The patch keeps the production *type* (a timedelta) and only shortens it,
    so this fails again the moment the conversion is dropped.
    """
    monkeypatch.setattr(lease, "DEFAULT_HEARTBEAT", timedelta(seconds=0.01))
    target_id, run_id = _seed_run(session_factory)
    with session_factory() as s:
        repo.begin_run(s, run_id)
    before = _run_field(session_factory, run_id, "lease_expires_at")

    with reaper.heartbeat_during(run_id, session_factory=session_factory):
        _wait_until(lambda: _run_field(session_factory, run_id, "lease_expires_at") > before)

    assert _run_field(session_factory, run_id, "lease_expires_at") > before


def test_heartbeat_stops_quietly_once_the_run_is_no_longer_live(session_factory):
    """A completed run has no lease to keep; that is not an error."""
    target_id, run_id = _seed_run(session_factory)
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.complete_run(s, run_id)

    with reaper.heartbeat_during(run_id, interval_s=0.01, session_factory=session_factory):
        time.sleep(0.05)  # must not raise

    assert _run_field(session_factory, run_id, "status") is RunStatus.COMPLETED


def test_reap_once_fails_an_expired_run_and_frees_the_app(session_factory):
    target_id, run_id = _seed_run(session_factory)
    _expire_lease(session_factory, target_id, run_id)

    reaped = reaper._reap_once(session_factory)

    assert run_id in reaped
    assert _run_field(session_factory, run_id, "status") is RunStatus.FAILED
    assert "lease expired" in (_run_field(session_factory, run_id, "error") or "")
    # The app is free again: a new run can start.
    with session_factory() as s:
        fresh = repo.start_run(s, target_id=target_id, story_id="SCRUM-202", mode="full")
        assert fresh.status is RunStatus.PENDING


def test_reap_once_leaves_a_paused_run_alone(session_factory):
    """A pause deliberately holds the lock with no lease; it is not a crash."""
    target_id, run_id = _seed_run(session_factory)
    with session_factory() as s:
        repo.begin_run(s, run_id)
        repo.pause_run(s, run_id)
    _expire_lease(session_factory, target_id, run_id)

    assert reaper._reap_once(session_factory) == []
    assert _run_field(session_factory, run_id, "status") is RunStatus.PAUSED


def test_reap_once_is_a_no_op_when_nothing_has_expired(session_factory):
    _seed_run(session_factory)
    assert reaper._reap_once(session_factory) == []


def test_reaper_loop_survives_a_failing_pass():
    """A dead reaper must not take the API down with it."""
    calls = {"n": 0}

    def boom(_factory=None):
        calls["n"] += 1
        raise RuntimeError("db down")

    async def drive():
        task = asyncio.create_task(reaper.reaper_loop(interval_s=0.001))
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    original = reaper._reap_once
    reaper._reap_once = boom
    try:
        asyncio.run(drive())
    finally:
        reaper._reap_once = original

    assert calls["n"] >= 1  # kept going after the first failure


def test_reaper_loop_reports_what_it_reaped():
    seen: list[list[int]] = []

    async def drive():
        task = asyncio.create_task(
            reaper.reaper_loop(interval_s=0.001, on_reap=seen.append)
        )
        await asyncio.sleep(0.05)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    original = reaper._reap_once
    reaper._reap_once = lambda _factory=None: [41, 42]
    try:
        asyncio.run(drive())
    finally:
        reaper._reap_once = original

    assert [41, 42] in seen


def _wait_until(predicate, timeout: float = 2.0) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if predicate():
            return
        time.sleep(0.01)
    raise AssertionError("condition not met in time")
