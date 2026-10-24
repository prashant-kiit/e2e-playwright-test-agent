"""API tests for projects/targets/runs, backed by the qa_test database.

The get_session dependency is overridden to the test session (qa_test); the app
lifespan is not triggered (TestClient is used without the context manager), so
these never touch the dev database.
"""

import pytest
from fastapi.testclient import TestClient

from app import apphub
from app.api import get_bootstrap_runner, get_launcher, get_storage
from app.auth import require_auth
from app.db import get_session
from app.main import app
from app.tenancy import current_tenant_id
from tests.storage_helpers import FakeStorage
from tests.target_helpers import target_body


@pytest.fixture()
def client(session):
    launched: list[int] = []
    store = FakeStorage()
    app.dependency_overrides[get_session] = lambda: session
    # No-op launcher: tests assert on DB state, not background execution.
    app.dependency_overrides[get_launcher] = lambda: launched.append
    # Bypass auth for the API tests (auth itself is tested in test_auth.py).
    app.dependency_overrides[require_auth] = lambda: None
    # Creating a target commits its revision 1, so the blob store is in play.
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda a: apphub.BootstrapOutcome(ok=True, output="synced")
    )
    c = TestClient(app)
    c.launched = launched  # expose for assertions
    c.store = store
    yield c
    app.dependency_overrides.clear()


def _make_target(client, app_name="practice-target"):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    created = client.post(
        f"/projects/{pid}/targets",
        json=target_body(app=app_name, name="Practice Target"),
    ).json()
    return pid, created["target"]["id"]


def test_create_and_list_projects(client):
    r = client.post("/projects", json={"name": "alpha"})
    assert r.status_code == 201
    assert r.json()["name"] == "alpha"
    listing = client.get("/projects").json()
    assert [p["name"] for p in listing] == ["alpha"]


def test_create_target_under_missing_project_404(client):
    r = client.post("/projects/999/targets", json=target_body(app="x", name="X"))
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


def test_pause_sets_flag_on_running_run(client, session):
    from app import repo

    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    repo.begin_run(session, run["id"])  # make it RUNNING (launcher is a no-op in tests)
    r = client.post(f"/runs/{run['id']}/pause")
    assert r.status_code == 200
    assert r.json()["pause_requested"] is True


def test_stop_a_pending_run_via_api(client):
    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    r = client.post(f"/runs/{run['id']}/stop")
    assert r.status_code == 200
    assert r.json()["status"] == "stopped"
    # app is free again
    again = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-202", "mode": "full"})
    assert again.status_code == 201


def test_resume_a_paused_run_relaunches(client, session):
    from app import repo

    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    repo.begin_run(session, run["id"])
    repo.pause_run(session, run["id"])
    client.launched.clear()
    r = client.post(f"/runs/{run['id']}/resume")
    assert r.status_code == 200
    assert client.launched == [run["id"]]  # orchestrator re-launched


def test_resume_a_non_paused_run_409(client):
    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    r = client.post(f"/runs/{run['id']}/resume")  # still pending, not paused
    assert r.status_code == 409


def test_list_and_download_artifacts(client, session):
    from app.models import Artifact

    store = FakeStorage()
    app.dependency_overrides[get_storage] = lambda: store

    _, tid = _make_target(client)
    run = client.post(f"/targets/{tid}/runs", json={"story_id": "SCRUM-201", "mode": "full"}).json()
    key = f"{run['run_key']}/report.html"
    store.objects[key] = (b"<html>hi</html>", "text/html")
    session.add(
        Artifact(
            tenant_id=current_tenant_id(),
            run_id=run["id"],
            step="heal",
            kind="report",
            s3_key=key,
            sha256="x" * 64,
            version=1,
        )
    )
    session.commit()

    arts = client.get(f"/runs/{run['id']}/artifacts").json()
    assert len(arts) == 1 and arts[0]["kind"] == "report"

    content = client.get(f"/artifacts/{arts[0]['id']}/content")
    assert content.status_code == 200
    assert content.content == b"<html>hi</html>"
    assert content.headers["content-type"].startswith("text/html")


def test_download_missing_artifact_404(client):
    assert client.get("/artifacts/999/content").status_code == 404


def test_there_is_no_filesystem_backed_app_list(client):
    """Apps and targets collapsed into one concept. A route reading an app list
    off a disk is a route describing a disk that does not exist."""
    assert client.get("/apps").status_code == 404
    assert client.get("/apps/practice-target/stories").status_code == 404
    assert client.post("/apps/bootstrap", json={"app": "x", "name": "X"}).status_code == 404


def test_the_snapshot_and_parity_routes_are_gone(client):
    """No endpoint claims to snapshot a filesystem that is not authoritative,
    and there is no second copy of the truth to compare against."""
    _pid, tid = _make_target(client)
    assert client.post(f"/targets/{tid}/revisions/snapshot").status_code == 404
    assert client.get(f"/targets/{tid}/parity").status_code == 404


def test_settings_reports_no_repo_root(client):
    """The UI must not describe a mount that no longer exists."""
    s = client.get("/settings").json()
    assert "runner" in s
    assert "repo_root" not in s
    assert "worktrees_dir" in s


def test_prompts_are_served_from_package_data(client):
    prompts = client.get("/prompts").json()
    names = [p["name"] for p in prompts]
    assert "qa_system_prompt.md" in names
    assert "steps/_context.md" in names


def test_creating_a_target_returns_its_revision_one(client):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]

    r = client.post(f"/projects/{pid}/targets", json=target_body(app="fresh", name="Fresh"))

    assert r.status_code == 201
    body = r.json()
    assert body["target"]["app"] == "fresh"
    assert body["revision"]["rev"] == 1
    assert body["revision"]["author"] == "operator"
    assert body["revision"]["file_count"] > 0
    assert body["bootstrap"] is None, "the infra sync is opt-in"


def test_creating_a_target_can_sync_the_infra(client):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]

    r = client.post(
        f"/projects/{pid}/targets",
        json=target_body(app="fresh", name="Fresh", sync_infra=True),
    )

    assert r.json()["bootstrap"] == {"ok": True, "output": "synced"}


def test_a_duplicate_target_slug_is_a_409(client):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    client.post(f"/projects/{pid}/targets", json=target_body(app="twice", name="One"))

    r = client.post(f"/projects/{pid}/targets", json=target_body(app="twice", name="Two"))

    assert r.status_code == 409
    assert "twice" in r.json()["detail"]


def test_an_invalid_configuration_is_a_422(client):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]

    r = client.post(
        f"/projects/{pid}/targets", json=target_body(app="bad", base_url="nope")
    )

    assert r.status_code == 422
    assert "base URL" in r.json()["detail"]


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
