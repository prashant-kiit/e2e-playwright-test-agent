"""DB-backed tests for the repository: CRUD plus the lease-lock behaviour."""

from datetime import timedelta

import pytest

from app import repo
from app.domain import lease
from app.domain.status import RunStatus


def _project_with_target(session, app="practice-target"):
    p = repo.create_project(session, name="demo")
    t = repo.create_target(session, project_id=p.id, app=app, name="Practice Target")
    return p, t


def test_create_and_list_projects(session):
    repo.create_project(session, name="alpha")
    repo.create_project(session, name="beta")
    names = [p.name for p in repo.list_projects(session)]
    assert names == ["alpha", "beta"]


def test_create_target_requires_existing_project(session):
    with pytest.raises(repo.NotFound):
        repo.create_target(session, project_id=999, app="x", name="X")


def test_list_targets_filtered_by_project(session):
    p1, _ = _project_with_target(session, app="practice-target")
    p2 = repo.create_project(session, name="other")
    repo.create_target(session, project_id=p2.id, app="saucedemo", name="SauceDemo")
    apps_p1 = [t.app for t in repo.list_targets(session, project_id=p1.id)]
    assert apps_p1 == ["practice-target"]
    assert len(repo.list_targets(session)) == 2


def test_start_run_creates_pending_run_and_lock(session):
    _, t = _project_with_target(session)
    run = repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="full")
    assert run.status is RunStatus.PENDING
    assert run.lease_expires_at is not None
    assert "practice-target" in run.run_key  # key embeds the app name
    runs = repo.list_runs(session, target_id=t.id)
    assert len(runs) == 1


def test_start_run_rejects_bad_mode(session):
    _, t = _project_with_target(session)
    with pytest.raises(ValueError):
        repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="partial")


def test_second_live_run_on_same_app_conflicts(session):
    _, t = _project_with_target(session)
    repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="full")
    with pytest.raises(repo.RunConflict):
        repo.start_run(session, target_id=t.id, story_id="SCRUM-202", mode="full")


def test_heartbeat_extends_lease(session):
    _, t = _project_with_target(session)
    now = lease.utcnow()
    run = repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="full", now=now)
    first = run.lease_expires_at
    later = now + timedelta(seconds=30)
    run = repo.heartbeat(session, run.id, now=later)
    assert run.lease_expires_at > first


def test_reap_expired_fails_the_run_and_frees_the_app(session):
    _, t = _project_with_target(session)
    t0 = lease.utcnow()
    run = repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="full", now=t0)
    # Jump past the lease TTL and reap.
    future = t0 + lease.DEFAULT_LEASE_TTL + timedelta(seconds=1)
    reaped = repo.reap_expired(session, now=future)
    assert run.id in reaped
    session.refresh(run)
    assert run.status is RunStatus.FAILED
    assert "lease expired" in (run.error or "")
    # App is free again: a new run can start.
    run2 = repo.start_run(session, target_id=t.id, story_id="SCRUM-202", mode="full", now=future)
    assert run2.status is RunStatus.PENDING


def test_start_run_reaps_a_stale_lock_in_place(session):
    """Starting a run when the previous one's lease has lapsed should succeed
    (reaping the dead run), not raise a conflict."""
    _, t = _project_with_target(session)
    t0 = lease.utcnow()
    dead = repo.start_run(session, target_id=t.id, story_id="SCRUM-201", mode="full", now=t0)
    future = t0 + lease.DEFAULT_LEASE_TTL + timedelta(seconds=5)
    fresh = repo.start_run(session, target_id=t.id, story_id="SCRUM-202", mode="full", now=future)
    session.refresh(dead)
    assert dead.status is RunStatus.FAILED
    assert fresh.status is RunStatus.PENDING
    assert fresh.id != dead.id
