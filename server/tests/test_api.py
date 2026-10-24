"""API tests for projects/targets/runs, backed by the qa_test database.

The get_session dependency is overridden to the test session (qa_test); the app
lifespan is not triggered (TestClient is used without the context manager), so
these never touch the dev database.
"""

import pytest
from fastapi.testclient import TestClient

from app import apphub
from app.api import get_launcher, get_storage
from app.auth import require_auth
from app.db import get_session
from app.main import app
from app.tenancy import current_tenant_id
from tests.storage_helpers import FakeStorage
from tests.target_helpers import target_body


@pytest.fixture()
def client(session):
    launched: list[int] = []
    app.dependency_overrides[get_session] = lambda: session
    # No-op launcher: tests assert on DB state, not background execution.
    app.dependency_overrides[get_launcher] = lambda: launched.append
    # Bypass auth for the API tests (auth itself is tested in test_auth.py).
    app.dependency_overrides[require_auth] = lambda: None
    c = TestClient(app)
    c.launched = launched  # expose for assertions
    yield c
    app.dependency_overrides.clear()


def _make_target(client, app_name="practice-target"):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    tid = client.post(
        f"/projects/{pid}/targets",
        json=target_body(app=app_name, name="Practice Target"),
    ).json()["id"]
    return pid, tid


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


def test_list_apps_and_stories_from_repo(client):
    apps = client.get("/apps").json()
    assert "practice-target" in [a["app"] for a in apps]
    stories = client.get("/apps/practice-target/stories").json()
    assert any(s["story_id"] == "SCRUM-201" for s in stories)


def test_settings_and_prompts(client):
    s = client.get("/settings").json()
    assert "runner" in s and "repo_root" in s
    prompts = client.get("/prompts").json()
    assert any(p["name"] == "qa_system_prompt.md" for p in prompts)


def test_bootstrap_via_api(client, tmp_path, monkeypatch):
    from app.api import get_bootstrap_runner

    monkeypatch.setenv("QA_REPO_ROOT", str(tmp_path))
    (tmp_path / "apps").mkdir()
    calls = []
    app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda a: calls.append(a) or apphub.BootstrapOutcome(ok=True, output="ok")
    )
    r = client.post("/apps/bootstrap", json={"app": "demoapp", "name": "Demo", "targetRepo": "o/r"})
    assert r.status_code == 201
    assert (tmp_path / "apps" / "demoapp" / "app.json").exists()
    assert calls == ["demoapp"]
    # The portal gets an outcome plus some text, not a shell return code.
    assert r.json()["bootstrap"] == {"ok": True, "output": "ok"}


def test_bootstrap_app_reports_a_failed_target_sync_as_an_outcome(client, tmp_path, monkeypatch):
    """A target-repo failure is still a 201 with ok=False: apps/<app>/ was
    created, and the form shows why the sync did not land."""
    from app.api import get_bootstrap_runner

    monkeypatch.setenv("QA_REPO_ROOT", str(tmp_path))
    (tmp_path / "apps").mkdir()
    app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda a: apphub.BootstrapOutcome(ok=False, output="no GitHub token")
    )
    r = client.post("/apps/bootstrap", json={"app": "demoapp", "name": "Demo"})
    assert r.status_code == 201
    assert r.json()["bootstrap"] == {"ok": False, "output": "no GitHub token"}


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
