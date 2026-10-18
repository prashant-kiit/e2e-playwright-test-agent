"""API tests for projects/targets/runs, backed by the qa_test database.

The get_session dependency is overridden to the test session (qa_test); the app
lifespan is not triggered (TestClient is used without the context manager), so
these never touch the dev database.
"""

import pytest
from fastapi.testclient import TestClient

from app.db import get_session
from app.main import app


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    c = TestClient(app)
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


def test_start_run_returns_pending(client):
    _, tid = _make_target(client)
    r = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"})
    assert r.status_code == 201
    body = r.json()
    assert body["status"] == "pending"
    assert body["mode"] == "full"


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
