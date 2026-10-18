"""API tests for projects/targets/runs, backed by the qa_test database.

The get_session dependency is overridden to the test session (qa_test); the app
lifespan is not triggered (TestClient is used without the context manager), so
these never touch the dev database.
"""

import pytest
from fastapi.testclient import TestClient

from app.api import get_launcher
from app.db import get_session
from app.main import app


@pytest.fixture()
def client(session):
    launched: list[int] = []
    app.dependency_overrides[get_session] = lambda: session
    # No-op launcher: tests assert on DB state, not background execution.
    app.dependency_overrides[get_launcher] = lambda: launched.append
    c = TestClient(app)
    c.launched = launched  # expose for assertions
    yield c
    app.dependency_overrides.clear()


def _make_target(client, app_name="practice-target"):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    tid = client.post(
        f"/projects/{pid}/targets", json={"app": app_name, "name": "Practice Target"}
    ).json()["id"]
    return pid, tid


def test_create_and_list_projects(client):
    r = client.post("/projects", json={"name": "alpha"})
    assert r.status_code == 201
    assert r.json()["name"] == "alpha"
    listing = client.get("/projects").json()
    assert [p["name"] for p in listing] == ["alpha"]


def test_create_target_under_missing_project_404(client):
    r = client.post("/projects/999/targets", json={"app": "x", "name": "X"})
    assert r.status_code == 404


def test_list_targets_filtered(client):
    pid, _ = _make_target(client)
    r = client.get("/targets", params={"project_id": pid})
    assert r.status_code == 200
    assert len(r.json()) == 1


def test_start_run_returns_pending_and_launches(client):
    _, tid = _make_target(client)
    r = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["mode"] == "full"
    assert client.launched == [body["id"]]  # orchestrator was kicked off


def test_second_live_run_same_app_409(client):
    _, tid = _make_target(client)
    client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"})
    r = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-202", "mode": "full"})
    assert r.status_code == 409


def test_start_run_missing_target_404(client):
    r = client.post("/targets/999/runs", json={"story_id": "SCRUM-201", "mode": "full"})
    assert r.status_code == 404


def test_invalid_mode_422(client):
    _, tid = _make_target(client)
    r = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "partial"})
    assert r.status_code == 422


def test_get_and_list_runs(client):
    _, tid = _make_target(client)
    run = client.post(
        f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "changed"}
    ).json()
    got = client.get(f"/runs/{run['id']}")
    assert got.status_code == 200
    assert got.json()["run_key"] == run["run_key"]
    listing = client.get("/runs", params={"target_id": tid}).json()
    assert len(listing) == 1


def test_get_missing_run_404(client):
    assert client.get("/runs/12345").status_code == 404


def test_run_steps_endpoint(client, session):
    from app import repo
    from app.domain.steps import Step

    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    repo.start_step(session, run["id"], Step.READ_STORY)
    repo.complete_step(session, run["id"], Step.READ_STORY)

    r = client.get(f"/runs/{run['id']}/steps")
    assert r.status_code == 200
    steps = r.json()
    assert len(steps) == 1
    assert steps[0]["step"] == "read_story"
    assert steps[0]["status"] == "completed"


def test_events_replays_history_of_a_finished_run(client, session):
    from app import repo
    from app.orchestrator.bus import bus

    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    rid = run["id"]
    bus.publish(rid, "line one")
    bus.publish(rid, "line two")
    repo.begin_run(session, rid)
    repo.complete_run(session, rid)  # terminal -> events stream should end, not block

    r = client.get(f"/runs/{rid}/events")
    assert r.status_code == 200
    body = r.text
    assert "line one" in body and "line two" in body
    assert "event: end" in body
