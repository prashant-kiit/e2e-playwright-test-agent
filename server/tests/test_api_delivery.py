"""The delivery routes: bootstrap-check, deliver, reset.

These are what replaced "a human runs a shell script" (DESIGN.md §7, §11). The
delivery tools themselves are tested in test_delivery_*.py against a real local
remote; here the concern is the HTTP contract -- which failure maps to which
status code, and that the destructive route cannot fire without its confirmation.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import delivery
from app.api import get_delivery_tools, get_launcher
from app.auth import require_auth
from app.db import get_session
from app.main import app


class _StubDelivery:
    """Stands in for app.delivery.Tools; only identity matters here since the
    module functions are patched per test."""


@pytest.fixture()
def client(session):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_delivery_tools] = lambda: _StubDelivery()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_target(client, app_name="practice-target"):
    project = client.post("/projects", json={"name": "demo"}).json()
    target = client.post(
        f"/projects/{project['id']}/targets", json={"app": app_name, "name": "T"}
    ).json()
    return target["id"]


# --- GET /targets/{id}/bootstrapped ------------------------------------

def test_bootstrapped_reports_state(client, monkeypatch):
    tid = _make_target(client)
    monkeypatch.setattr(
        delivery,
        "is_bootstrapped",
        lambda app, tools=None: (True, delivery.TargetRef("practice-target", "o/r", "master")),
    )
    body = client.get(f"/targets/{tid}/bootstrapped").json()
    assert body == {
        "app": "practice-target",
        "repo": "o/r",
        "branch": "master",
        "bootstrapped": True,
    }


def test_bootstrapped_404s_for_an_unknown_target(client):
    assert client.get("/targets/999/bootstrapped").status_code == 404


def test_bootstrapped_400s_on_a_config_problem(client, monkeypatch):
    tid = _make_target(client)

    def boom(app, tools=None):
        raise delivery.DeliveryError("set a real targetRepo")

    monkeypatch.setattr(delivery, "is_bootstrapped", boom)
    resp = client.get(f"/targets/{tid}/bootstrapped")
    assert resp.status_code == 400
    assert "targetRepo" in resp.json()["detail"]


# --- POST /targets/{id}/deliver ----------------------------------------

def _push_result(**kw):
    defaults = dict(
        app="practice-target",
        story_id="SCRUM-201",
        repo="o/r",
        branch="qa/SCRUM-201-x",
        committed=True,
        pr_url="https://github.com/o/r/pull/1",
        pr_number=1,
        pr_created=True,
        message="PR: https://github.com/o/r/pull/1",
    )
    return delivery.PushResult(**{**defaults, **kw})


def test_deliver_bootstraps_first_then_pushes(client, monkeypatch):
    """Decision 16: one approval means 'set the repo up and deliver this story'."""
    tid = _make_target(client)
    order: list[str] = []
    monkeypatch.setattr(
        delivery, "ensure_bootstrapped", lambda a, tools=None: order.append("bootstrap")
    )
    monkeypatch.setattr(
        delivery,
        "push_artifacts",
        lambda a, s, **kw: (order.append("push"), _push_result())[1],
    )

    resp = client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"})

    assert resp.status_code == 200
    assert order == ["bootstrap", "push"]
    assert resp.json()["pr_url"].endswith("/pull/1")
    assert resp.json()["detail"] == {"branch": "qa/SCRUM-201-x", "committed": True}


def test_deliver_dry_run_does_not_bootstrap(client, monkeypatch):
    tid = _make_target(client)
    calls: list[str] = []
    monkeypatch.setattr(
        delivery, "ensure_bootstrapped", lambda a, tools=None: calls.append("bootstrap")
    )
    monkeypatch.setattr(
        delivery,
        "push_artifacts",
        lambda a, s, **kw: _push_result(committed=False, pr_url="", pr_number=None),
    )

    resp = client.post(
        f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201", "dry_run": True}
    )

    assert resp.status_code == 200
    assert calls == []


def test_deliver_passes_the_run_id_through(client, monkeypatch):
    tid = _make_target(client)
    seen: dict = {}
    monkeypatch.setattr(delivery, "ensure_bootstrapped", lambda a, tools=None: None)

    def capture(a, s, **kw):
        seen.update(kw)
        return _push_result()

    monkeypatch.setattr(delivery, "push_artifacts", capture)
    client.post(
        f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201", "run_id": "run-9"}
    )
    assert seen["run_id"] == "run-9"


def test_deliver_409s_when_the_target_is_not_bootstrapped(client, monkeypatch):
    tid = _make_target(client)
    monkeypatch.setattr(delivery, "ensure_bootstrapped", lambda a, tools=None: None)

    def boom(a, s, **kw):
        raise delivery.NotBootstrapped("o/r", "master", "practice-target")

    monkeypatch.setattr(delivery, "push_artifacts", boom)
    assert client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"}).status_code == 409


def test_deliver_502s_on_a_credential_failure(client, monkeypatch):
    """§8 fail-loud: a bad PAT is surfaced, never silently retried."""
    tid = _make_target(client)

    def boom(a, tools=None):
        raise delivery.CredentialError("GitHub rejected the token (401)")

    monkeypatch.setattr(delivery, "ensure_bootstrapped", boom)
    resp = client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"})
    assert resp.status_code == 502
    assert "401" in resp.json()["detail"]


def test_deliver_400s_when_there_is_no_test_suite(client, monkeypatch):
    tid = _make_target(client)
    monkeypatch.setattr(delivery, "ensure_bootstrapped", lambda a, tools=None: None)

    def boom(a, s, **kw):
        raise delivery.DeliveryError("no test suite at apps/x/tests/y")

    monkeypatch.setattr(delivery, "push_artifacts", boom)
    assert client.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"}).status_code == 400


def test_deliver_requires_a_story_id(client):
    tid = _make_target(client)
    assert client.post(f"/targets/{tid}/deliver", json={}).status_code == 422


# --- POST /targets/{id}/reset ------------------------------------------

def _reset_result(**kw):
    defaults = dict(
        app="practice-target",
        repo="o/r",
        branch="master",
        already_empty=False,
        reset_branch=True,
        deleted_branches=("qa/SCRUM-201-x",),
        failed_branches=(),
        message="reset done",
    )
    return delivery.ResetResult(**{**defaults, **kw})


def test_reset_requires_the_repo_name_echoed_back(client, monkeypatch):
    """The TTY confirmation became an API contract; a wrong name is a 400."""
    tid = _make_target(client)

    def boom(a, *, confirm_repo, dry_run=False, tools=None):
        raise delivery.ConfirmationMismatch("confirmation did not match")

    monkeypatch.setattr(delivery, "reset_target", boom)
    resp = client.post(f"/targets/{tid}/reset", json={"confirm_repo": "o/wrong"})
    assert resp.status_code == 400
    assert "did not match" in resp.json()["detail"]


def test_reset_rejects_a_request_with_no_confirmation_at_all(client):
    tid = _make_target(client)
    assert client.post(f"/targets/{tid}/reset", json={}).status_code == 422


def test_reset_reports_the_branches_it_removed(client, monkeypatch):
    tid = _make_target(client)
    monkeypatch.setattr(
        delivery, "reset_target", lambda a, **kw: _reset_result()
    )
    body = client.post(f"/targets/{tid}/reset", json={"confirm_repo": "o/r"}).json()
    assert body["detail"]["deleted_branches"] == ["qa/SCRUM-201-x"]
    assert body["detail"]["already_empty"] is False


# --- the dependency itself failing -------------------------------------

def test_a_missing_git_or_pat_is_a_503_not_a_bare_500(session, monkeypatch):
    """Dependencies resolve before the handler, so this path bypasses the
    routes' own try/except. It was a 500 until get_delivery_tools caught it."""
    from app.api import get_delivery_tools

    def boom():
        raise delivery.GitError(("--version",), 127, "missing dependency: git")

    monkeypatch.setattr(delivery, "default_tools", boom)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    # Deliberately NOT overriding get_delivery_tools: the real one must run.
    app.dependency_overrides.pop(get_delivery_tools, None)
    try:
        c = TestClient(app)
        tid = _make_target(c)
        resp = c.get(f"/targets/{tid}/bootstrapped")
        assert resp.status_code == 503
        assert "missing dependency: git" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
