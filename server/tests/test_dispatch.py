"""The dispatch seam: one protocol, one factory, no new injection point.

"A run starts working" gets an implementation choice and **not** a second place
to inject it. `get_launcher` -- already the dependency tests override to a no-op
-- gains a factory that picks from the environment, mirroring how `make_runner`
already picks `fake` or `claude`.

Substitution happens here and nowhere deeper. No test in this file reaches
inside a sandbox: what a good test asserts about a run is what the run produced,
and whether a thread or a container did the work is the one thing the suite must
not care about. K8s and Fargate are what the seam exists for; a recording fake
and Docker are what it contains today.
"""

from __future__ import annotations

import inspect

import pytest
from fastapi.testclient import TestClient

from app import launcher, repo
from app.api import get_launcher, get_resolver, get_scheduler, get_storage
from app.auth import require_auth
from app.db import get_session
from app.domain.status import RunStatus
from app.main import app
from app.models import AppLock
from app.sandbox import dispatch
from tests.storage_helpers import FakeStorage
from tests.target_helpers import public_resolver, target_body


@pytest.fixture()
def scheduler():
    return dispatch.RecordingScheduler()


@pytest.fixture()
def client(session, scheduler):
    """A client whose launcher is the real dispatching one, over a fake seam."""
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_scheduler] = lambda: scheduler
    app.dependency_overrides[get_launcher] = lambda: dispatch.dispatching_launcher(
        scheduler, session_factory=lambda: session
    )
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


def _target(client, app_name="demo"):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    created = client.post(
        f"/projects/{pid}/targets", json=target_body(app=app_name, name="Demo")
    ).json()
    return created["target"]["id"]


def _start(client, target_id, story="SCRUM-1"):
    r = client.post(f"/targets/{target_id}/runs", json={"story_id": story, "mode": "full"})
    assert r.status_code == 201, r.text
    return r.json()


# --- the seam ------------------------------------------------------------

def test_the_scheduler_protocol_is_dispatch_and_destroy():
    """An opaque handle in, nothing out: a scheduler that needed to be asked
    anything else would be a scheduler the API has to understand."""
    assert set(dispatch.Scheduler.__protocol_attrs__) == {"dispatch", "destroy"}
    assert list(inspect.signature(dispatch.RecordingScheduler.dispatch).parameters) == [
        "self",
        "run_id",
    ]
    assert list(inspect.signature(dispatch.RecordingScheduler.destroy).parameters) == [
        "self",
        "handle",
    ]


def test_the_launcher_factory_picks_the_thread_path_by_default(monkeypatch):
    """Today's behaviour, and the test and CI default."""
    monkeypatch.delenv("QA_SANDBOX", raising=False)
    assert dispatch.make_launcher() is launcher.launch_run


def test_the_launcher_factory_picks_dispatch_for_docker(monkeypatch):
    monkeypatch.setenv("QA_SANDBOX", "docker")
    assert dispatch.make_launcher() is not launcher.launch_run


def test_an_unknown_sandbox_kind_is_refused_rather_than_guessed(monkeypatch):
    """A typo in QA_SANDBOX must not silently run the agent in the API."""
    monkeypatch.setenv("QA_SANDBOX", "kubernets")
    with pytest.raises(ValueError, match="QA_SANDBOX"):
        dispatch.make_launcher()


def test_get_launcher_is_still_the_only_injection_point_for_starting_a_run():
    """DESIGN.md §13. The dependency's shape is unchanged, which is what keeps
    `test_api.py`'s override a no-op lambda."""
    assert inspect.signature(get_launcher).parameters == {}
    source = inspect.getsource(get_launcher)
    assert "make_launcher" in source


# --- starting a run dispatches exactly once ------------------------------

def test_starting_a_run_dispatches_once_with_the_runs_id(client, scheduler):
    target_id = _target(client)

    run = _start(client, target_id)

    assert scheduler.dispatched == [run["id"]]


def test_the_handle_is_recorded_on_the_run_and_readable_through_the_api(
    client, scheduler
):
    """So an SRE can find the container behind a live run, and so the stop path
    has something to kill."""
    target_id = _target(client)

    run = _start(client, target_id)

    assert client.get(f"/runs/{run['id']}").json()["sandbox_handle"] == (
        scheduler.handles[0]
    )


def test_a_thread_run_records_no_handle(client, session):
    """There is no sandbox to find: the column says so rather than lying."""
    app.dependency_overrides[get_launcher] = lambda: launcher.launch_run
    target_id = _target(client)

    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(launcher, "drive_run", lambda *a, **kw: None)
        run = _start(client, target_id)

    assert client.get(f"/runs/{run['id']}").json()["sandbox_handle"] is None


# --- a dispatch failure is a platform failure, reported as one ------------

@pytest.mark.parametrize(
    "reason",
    [
        "no such image: qa-sandbox:latest",
        "cannot connect to the Docker daemon",
        "quota exceeded: no capacity for another sandbox",
    ],
)
def test_a_dispatch_failure_fails_the_run_with_that_reason(client, session, reason):
    """A broken platform is never reported as a broken run."""
    target_id = _target(client)
    app.dependency_overrides[get_launcher] = lambda: dispatch.dispatching_launcher(
        dispatch.RecordingScheduler(fail_with=RuntimeError(reason)),
        session_factory=lambda: session,
    )

    run = _start(client, target_id)

    body = client.get(f"/runs/{run['id']}").json()
    assert body["status"] == RunStatus.FAILED.value
    assert reason in body["error"]
    assert "dispatch" in body["error"]


def test_a_dispatch_failure_frees_the_app_lock(client, session):
    """No administrator in the database to start the next run."""
    target_id = _target(client)
    app.dependency_overrides[get_launcher] = lambda: dispatch.dispatching_launcher(
        dispatch.RecordingScheduler(fail_with=RuntimeError("no capacity")),
        session_factory=lambda: session,
    )

    _start(client, target_id)

    assert session.get(AppLock, target_id) is None


def test_a_second_run_starts_after_a_dispatch_failure(client, session, scheduler):
    """The operator's actual next move, which is the point of freeing the lock."""
    target_id = _target(client)
    app.dependency_overrides[get_launcher] = lambda: dispatch.dispatching_launcher(
        dispatch.RecordingScheduler(fail_with=RuntimeError("no capacity")),
        session_factory=lambda: session,
    )
    first = _start(client, target_id)

    app.dependency_overrides[get_launcher] = lambda: dispatch.dispatching_launcher(
        scheduler, session_factory=lambda: session
    )
    second = _start(client, target_id, story="SCRUM-2")

    assert second["id"] != first["id"]
    assert second["status"] == RunStatus.PENDING.value
    assert scheduler.dispatched == [second["id"]]


def test_a_resume_dispatches_a_fresh_sandbox(client, session, scheduler):
    """Resume is a new sandbox hydrating from the head, not a revived one."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])
    repo.pause_run(session, run["id"])

    r = client.post(f"/runs/{run['id']}/resume")

    assert r.status_code == 200
    assert scheduler.dispatched == [run["id"], run["id"]]


# --- the recording fake is a seam double, not a scheduler ----------------

def test_the_recording_fake_records_destroys(scheduler):
    handle = scheduler.dispatch(7)
    scheduler.destroy(handle)
    assert scheduler.destroyed == [handle]


def test_the_recording_fake_hands_out_one_handle_per_run(scheduler):
    first, second = scheduler.dispatch(1), scheduler.dispatch(2)
    assert first != second


# --- stop and pause reach the seam ---------------------------------------

def test_stopping_a_run_kills_its_sandbox_and_the_run_reaches_stopped(
    client, session, scheduler
):
    """"Stop" has to mean the work stops, not that the status changes: an agent
    holding a browser is minutes of billing away from its next step boundary."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])

    r = client.post(f"/runs/{run['id']}/stop")

    assert r.status_code == 200
    assert r.json()["status"] == RunStatus.STOPPED.value
    assert scheduler.destroyed == scheduler.handles
    assert session.get(AppLock, target_id) is None, "the target is free"


def test_stopping_a_run_without_a_sandbox_still_stops_it(client, session):
    """The thread path, and a run whose dispatch never got that far."""
    app.dependency_overrides[get_launcher] = lambda: (lambda _id: None)
    target_id = _target(client)
    run = _start(client, target_id)

    r = client.post(f"/runs/{run['id']}/stop")

    assert r.status_code == 200
    assert r.json()["status"] == RunStatus.STOPPED.value


def test_destroying_a_sandbox_is_idempotent(scheduler):
    """Pause, stop and the reaper may all reach for the same handle, and a
    container that has already exited is what each of them wanted."""
    handle = scheduler.dispatch(1)

    assert dispatch.destroy_handle(handle, scheduler)
    assert dispatch.destroy_handle(handle, scheduler)
    assert scheduler.destroyed == [handle, handle]


def test_there_is_nothing_to_destroy_on_the_thread_path(monkeypatch):
    monkeypatch.setenv("QA_SANDBOX", "thread")
    assert dispatch.make_scheduler() is None
    assert dispatch.destroy_handle("qa-run-whatever") is False


def test_a_paused_run_that_still_names_a_sandbox_is_the_reapers_business(
    client, session, scheduler
):
    """The pause route kills the container itself, so a handle left on a paused
    row means that did not finish -- an API that died mid-pause, or a pause that
    raced a dispatch. The reaper is the net under it, and what makes "a paused
    run has no sandbox" true and not just intended."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])
    repo.pause_run(session, run["id"])

    assert repo.idle_sandbox_runs(session) == [run["id"]]

    repo.set_sandbox_handle(session, run["id"], None)
    assert repo.idle_sandbox_runs(session) == []
    assert repo.get_run(session, run["id"]).status is RunStatus.PAUSED, "still paused"


def test_pausing_a_run_destroys_its_sandbox_at_once(client, session, scheduler):
    """Pause exists to stop costing money, so it cannot wait for a boundary an
    agent holding a browser is minutes of billing away from. The row is moved to
    `paused` here because the process that would have done it is the one just
    killed."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])

    r = client.post(f"/runs/{run['id']}/pause")

    assert r.status_code == 200
    assert r.json()["status"] == RunStatus.PAUSED.value
    assert scheduler.destroyed == scheduler.handles
    assert r.json()["sandbox_handle"] is None, "a paused run names no sandbox"
    assert session.get(AppLock, target_id) is not None, "the run still owns the app"


def test_a_paused_run_is_not_waiting_for_a_boundary_to_notice(
    client, session, scheduler
):
    """`pause_requested` is cleared by the transition, so nothing is left for a
    step boundary that will never come."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])

    client.post(f"/runs/{run['id']}/pause")

    row = repo.get_run(session, run["id"])
    assert row.pause_requested is False
    assert row.lease_expires_at is None, "a pause holds the lock with no lease"


def test_pausing_a_run_without_a_sandbox_still_asks_the_boundary(client, session):
    """The thread path keeps the flag-at-a-boundary behaviour: there is no
    container to kill, and the thread doing the work notices at its next step."""
    app.dependency_overrides[get_launcher] = lambda: (lambda _id: None)
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])

    r = client.post(f"/runs/{run['id']}/pause")

    assert r.status_code == 200
    assert r.json()["status"] == RunStatus.RUNNING.value
    assert r.json()["pause_requested"] is True


# --- a sandbox nothing is using -----------------------------------------
#
# Found by watching a real run finish rather than by a test: the run container
# carries `AutoRemove` and vanishes, but its egress proxy is a long-running
# container that exits on nobody's schedule, and only `destroy` removes it. With
# the sweep limited to paused runs, **every completed run left a proxy running
# for ever** -- one idle container per run, which is exactly what "a finished run
# leaves nothing to pay for" was supposed to rule out. No test caught it because
# the seam tests use a recording scheduler and the container test runs with
# `with_proxy=False`.


@pytest.mark.parametrize(
    "terminal",
    [RunStatus.COMPLETED, RunStatus.FAILED, RunStatus.STOPPED],
)
def test_a_finished_run_that_still_names_a_sandbox_is_the_reapers_business(
    client, session, scheduler, terminal
):
    """Terminal, not just paused. The run's own process cannot do this: it is
    inside the sandbox, it has no Docker socket by design, and the proxy has to
    outlive it long enough to serve the last step."""
    target_id = _target(client)
    run = _start(client, target_id)
    repo.begin_run(session, run["id"])
    if terminal is RunStatus.COMPLETED:
        repo.complete_run(session, run["id"])
    elif terminal is RunStatus.FAILED:
        repo.fail_run(session, run["id"], "whatever ended it")
    else:
        repo.stop_run(session, run["id"])

    assert repo.get_run(session, run["id"]).status is terminal
    assert repo.idle_sandbox_runs(session) == [run["id"]], (
        "a terminal run's proxy is nobody else's to remove"
    )


def test_a_live_run_is_never_swept(client, session, scheduler):
    """The other side of it, and the one that would be a disaster: sweeping a
    RUNNING run would destroy the container doing the work. A PENDING run is a
    dispatch that has not begun yet, which is the same mistake a moment earlier.
    """
    target_id = _target(client)
    run = _start(client, target_id)

    assert repo.get_run(session, run["id"]).status is RunStatus.PENDING
    assert repo.idle_sandbox_runs(session) == [], "a pending dispatch is not idle"

    repo.begin_run(session, run["id"])
    assert repo.idle_sandbox_runs(session) == [], "a running run is not idle"
