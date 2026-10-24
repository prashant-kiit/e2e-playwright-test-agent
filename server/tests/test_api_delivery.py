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
from app.api import get_catalog, get_delivery_tools, get_launcher
from app.auth import require_auth
from app.db import get_session
from app.main import app
from tests.target_helpers import target_body


class _StubCatalog:
    """The catalog field of the delivery seam, for routes that read it directly.

    `/targets/{id}/delivery` asks the catalog rather than a module function, so
    unlike the push and reset routes it needs more than an identity stub.
    """

    def __init__(self, state=None, cfg=None):
        from app.delivery.catalog import DeliveryState
        from app.target_config import TargetConfig

        self._state = state or DeliveryState(
            rev=3,
            tree_hash="f" * 64,
            delivered_sha="a" * 40,
            revisions_ahead=0,
            ever_delivered=True,
        )
        self._cfg = cfg or TargetConfig(
            app="practice-target",
            name="T",
            base_url="https://t.example.com",
            locators="",
            agent_notes=(),
            target_repo="o/r",
            target_branch="master",
        )

    def config(self, app):
        return self._cfg

    def state(self, app):
        return self._state


class _StubDelivery:
    """Stands in for app.delivery.Tools; the module functions are patched per
    test, so only the catalog it carries has to behave."""

    def __init__(self, catalog=None):
        self.catalog = catalog or _StubCatalog()


@pytest.fixture()
def client(session):
    from app.api import get_storage
    from tests.storage_helpers import FakeStorage

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_delivery_tools] = lambda: _StubDelivery()
    app.dependency_overrides[get_catalog] = lambda: _StubCatalog()
    # Creating a target commits its revision 1.
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    yield TestClient(app)
    app.dependency_overrides.clear()


def _make_target(client, app_name="practice-target"):
    project = client.post("/projects", json={"name": "demo"}).json()
    created = client.post(
        f"/projects/{project['id']}/targets", json=target_body(app=app_name, name="T")
    ).json()
    return created["target"]["id"]


# --- GET /targets/{id}/delivery ----------------------------------------
#
# The answer the portal shows, from one Postgres query. No `ls-remote`, no
# worktree diff, no fetch.

def test_delivery_state_reports_delivered(client):
    tid = _make_target(client)

    body = client.get(f"/targets/{tid}/delivery").json()

    assert body["repo"] == "o/r"
    assert body["branch"] == "master"
    assert body["delivered"] is True
    assert body["bootstrapped"] is True
    assert body["rev"] == 3
    assert body["delivered_sha"] == "a" * 40
    assert body["revisions_ahead"] == 0
    assert "delivered" in body["summary"]


def test_delivery_state_reports_n_revisions_ahead(client):
    from app.delivery.catalog import DeliveryState

    tid = _make_target(client)
    ahead = DeliveryState(
        rev=5,
        tree_hash="e" * 64,
        delivered_sha=None,
        revisions_ahead=2,
        ever_delivered=True,
    )
    app.dependency_overrides[get_catalog] = lambda: _StubCatalog(state=ahead)

    body = client.get(f"/targets/{tid}/delivery").json()

    assert body["delivered"] is False
    assert body["revisions_ahead"] == 2
    assert body["bootstrapped"] is True
    assert "2 revision(s) ahead" in body["summary"]


def test_delivery_state_needs_no_credential(session):
    """It is a Postgres question, so it must not need a GitHub client or a PAT.

    Found in a real browser: the route hung off the full delivery seam, whose
    construction reads GITHUB_PAT, so an operator with no PAT configured got a
    503 and the portal could not show the badge at all -- for an answer that
    never leaves the database.
    """
    from app.api import get_catalog, get_storage
    from tests.storage_helpers import FakeStorage

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_catalog] = lambda: _StubCatalog()
    # Deliberately NOT overriding get_delivery_tools, and making it fail the way
    # a missing PAT does.
    app.dependency_overrides.pop(get_delivery_tools, None)

    def no_pat():
        raise delivery.CredentialError("no GitHub token: set GITHUB_PAT in the environment")

    try:
        monkey = delivery.default_tools
        delivery.default_tools = no_pat
        c = TestClient(app)
        tid = _make_target(c)
        resp = c.get(f"/targets/{tid}/delivery")
        assert resp.status_code == 200, resp.text
        assert resp.json()["delivered"] is True
    finally:
        delivery.default_tools = monkey
        app.dependency_overrides.clear()


def test_delivery_state_404s_for_an_unknown_target(client):
    assert client.get("/targets/999/delivery").status_code == 404


def test_delivery_state_400s_on_a_config_problem(client):
    class Broken(_StubCatalog):
        def config(self, app):
            raise delivery.DeliveryError("no such target: 'ghost'")

    tid = _make_target(client)
    app.dependency_overrides[get_catalog] = lambda: Broken()

    resp = client.get(f"/targets/{tid}/delivery")
    assert resp.status_code == 400
    assert "ghost" in resp.json()["detail"]


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
        delivered_sha="a" * 40,
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
    assert resp.json()["detail"] == {
        "branch": "qa/SCRUM-201-x",
        "committed": True,
        "delivered_sha": "a" * 40,
    }


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
        raise delivery.DeliveryError("no test suite at tests/y in the head revision")

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

    from app.api import get_delivery_tools, get_storage
    from tests.storage_helpers import FakeStorage

    def boom():
        raise delivery.GitError(("--version",), 127, "missing dependency: git")

    monkeypatch.setattr(delivery, "default_tools", boom)
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[require_auth] = lambda: None
    # Creating a target commits its revision 1.
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    # Deliberately NOT overriding get_delivery_tools: the real one must run.
    app.dependency_overrides.pop(get_delivery_tools, None)
    try:
        c = TestClient(app)
        tid = _make_target(c)
        # A route that genuinely needs git and the PAT. The state query
        # deliberately does not -- see test_delivery_state_needs_no_credential.
        resp = c.post(f"/targets/{tid}/deliver", json={"story_id": "SCRUM-201"})
        assert resp.status_code == 503
        assert "missing dependency: git" in resp.json()["detail"]
    finally:
        app.dependency_overrides.clear()
