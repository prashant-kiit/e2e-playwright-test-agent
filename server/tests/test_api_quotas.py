"""Quota breaches over HTTP: the status code, the reason, and the dispatch that
must not happen.

The seam the ticket names: `POST /targets/{id}/runs` with `get_launcher`
overridden to a recording no-op, so both breaches can be driven without a real
sandbox. What `tests/test_quotas.py` proves about `repo.start_run`, this proves
about the surface the operator actually presses -- and adds the half that only
exists here: **a refused run is never dispatched.** A breach that still handed
the run to a launcher would have spent the sandbox it was refused for.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.api import get_launcher, get_resolver, get_storage
from app.auth import require_auth
from app.db import get_session
from app.main import app
from app.tenancy import DEFAULT_TENANT_ID, tenant_scope
from tests.storage_helpers import FakeStorage
from tests.target_helpers import public_resolver, target_body


class RecordingLauncher:
    """A no-op launcher that remembers what it was asked to start."""

    def __init__(self) -> None:
        self.launched: list[int] = []

    def __call__(self, run_id: int) -> None:
        self.launched.append(run_id)


@pytest.fixture()
def launcher():
    return RecordingLauncher()


@pytest.fixture()
def client(session, launcher):
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_launcher] = lambda: launcher
    c = TestClient(app)
    yield c
    app.dependency_overrides.clear()


# The migration seeds this operator; tests/test_auth.py names it too.
SEED_ADMIN_EMAIL = "admin@example.com"
SEED_ADMIN_PASSWORD = "admin"
SEED_TENANT_SLUG = "default"


def _login_as_admin(c):
    r = c.post(
        "/auth/login",
        json={
            "tenant": SEED_TENANT_SLUG,
            "email": SEED_ADMIN_EMAIL,
            "password": SEED_ADMIN_PASSWORD,
        },
    )
    assert r.status_code == 200, r.text
    return c


@pytest.fixture()
def admin_client(session, launcher, monkeypatch):
    """The quota write, as a real logged-in admin.

    `require_auth` is **not** overridden, unlike the `client` fixture above:
    the acting user is what the audit row names, and an overridden dependency
    binds no actor, so a test on the `client` fixture would assert `system`
    did it. The role gate is driven here for free as a consequence.
    """
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_launcher] = lambda: launcher
    with TestClient(app) as c:
        yield _login_as_admin(c)
    app.dependency_overrides.clear()


@pytest.fixture()
def admin_client_per_request(session_factory, launcher, monkeypatch):
    """`admin_client`, but a **session per request**, as production has.

    Deliberately not built on the `session` fixture: proving a commit needs a
    second connection, and a test that took both fixtures would get two
    teardowns whose `TRUNCATE`s wait on each other for ever (see
    `tests/control_helpers.py`). So this one takes `session_factory` alone, and
    is the only fixture here that can see a missing commit.
    """
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")

    def _session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    app.dependency_overrides[get_session] = _session
    app.dependency_overrides[get_storage] = lambda: FakeStorage()
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_launcher] = lambda: launcher
    with TestClient(app) as c:
        yield _login_as_admin(c)
    app.dependency_overrides.clear()


def _targets(client, count):
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    ids = []
    for i in range(count):
        created = client.post(
            f"/projects/{pid}/targets", json=target_body(app=f"app-{i}", name=f"App {i}")
        )
        assert created.status_code == 201, created.text
        ids.append(created.json()["target"]["id"])
    return ids


def _start(client, target_id, story="SCRUM-1"):
    return client.post(
        f"/targets/{target_id}/runs", json={"story_id": story, "mode": "full"}
    )


def test_a_concurrency_breach_is_429_with_its_reason(session, client, launcher):
    a, b = _targets(client, 2)
    repo.set_tenant_caps(session, max_concurrent_runs=1, monthly_run_quota=None)

    assert _start(client, a).status_code == 201
    refused = _start(client, b, story="SCRUM-2")

    assert refused.status_code == 429
    assert "1 of 1 runs going at once" in refused.json()["detail"]


def test_a_monthly_quota_breach_is_429_with_its_own_reason(session, client, launcher):
    a, b = _targets(client, 2)
    repo.set_tenant_caps(session, max_concurrent_runs=None, monthly_run_quota=1)

    assert _start(client, a).status_code == 201
    refused = _start(client, b, story="SCRUM-2")

    assert refused.status_code == 429
    detail = refused.json()["detail"]
    assert "1 of its 1 runs for this calendar month" in detail
    assert "resets at the start of next month" in detail


def test_a_refused_run_is_never_dispatched(session, client, launcher):
    """The half that only exists at this seam. A breach that still reached the
    launcher would have spent the sandbox it was refused for."""
    a, b = _targets(client, 2)
    repo.set_tenant_caps(session, max_concurrent_runs=1)

    allowed = _start(client, a).json()
    assert _start(client, b, story="SCRUM-2").status_code == 429

    assert launcher.launched == [allowed["id"]]


def test_a_breach_is_429_and_a_busy_app_is_still_409(session, client, launcher):
    """The two refusals stay distinguishable to the operator: one says "this app
    is busy", the other "your tenant is out of allowance", and they are
    different remedies."""
    (only,) = _targets(client, 1)
    repo.set_tenant_caps(session, max_concurrent_runs=5)

    assert _start(client, only).status_code == 201
    assert _start(client, only, story="SCRUM-2").status_code == 409

    repo.set_tenant_caps(session, max_concurrent_runs=1)
    assert _start(client, only, story="SCRUM-3").status_code == 429


# --- what the portal reads to show usage against caps ---------------------

def test_the_usage_endpoint_reports_usage_against_the_caps(session, client):
    a, b = _targets(client, 2)
    repo.set_tenant_caps(session, max_concurrent_runs=3, monthly_run_quota=10)

    assert _start(client, a).status_code == 201
    assert _start(client, b, story="SCRUM-2").status_code == 201

    usage = client.get("/usage")

    assert usage.status_code == 200
    assert usage.json() == {
        "live_runs": 2,
        "runs_this_month": 2,
        "max_concurrent_runs": 3,
        "monthly_run_quota": 10,
        "at_concurrency_cap": False,
        "at_monthly_quota": False,
    }


def test_the_usage_endpoint_says_when_a_cap_is_reached(session, client):
    """What the portal needs to disable the Start button and say why, rather
    than letting the operator press it to find out."""
    (only,) = _targets(client, 1)
    repo.set_tenant_caps(session, max_concurrent_runs=1, monthly_run_quota=1)

    assert _start(client, only).status_code == 201

    body = client.get("/usage").json()

    assert body["at_concurrency_cap"] is True
    assert body["at_monthly_quota"] is True


def test_an_unmetered_tenant_reports_null_caps_and_is_never_at_one(session, client):
    """`None` is no cap, so "at the cap" is false however much it has run --
    the portal shows a count with no denominator rather than "1 of 0"."""
    (only,) = _targets(client, 1)
    repo.set_tenant_caps(session, max_concurrent_runs=None, monthly_run_quota=None)

    assert _start(client, only).status_code == 201

    body = client.get("/usage").json()

    assert body["max_concurrent_runs"] is None
    assert body["monthly_run_quota"] is None
    assert body["at_concurrency_cap"] is False
    assert body["at_monthly_quota"] is False


# --- the write half of that surface (P5-13 / #45) ------------------------
#
# The gate itself is driven through real auth and real roles in
# tests/test_auth.py, which is where the role tests live. What is here is the
# behaviour of the write once the gate has passed: which caps move, which are
# left alone, what gets audited, and that the row is really committed.

def _set_caps(client, body):
    return client.put("/usage/caps", json=body)


def test_only_the_caps_in_the_body_are_changed(session, admin_client):
    """An omitted cap is left exactly as it was.

    The failure this prevents has already happened once at the function:
    raising a concurrency cap silently deleted the monthly quota, because
    `None` was both the default and the way to say "unmetered". This is the
    surface that would have reintroduced it.
    """
    repo.set_tenant_caps(session, max_concurrent_runs=3, monthly_run_quota=10)

    body = _set_caps(admin_client, {"max_concurrent_runs": 9}).json()

    assert body["max_concurrent_runs"] == 9
    assert body["monthly_run_quota"] == 10, "the cap nobody mentioned is untouched"


def test_an_explicit_null_clears_a_cap_to_unmetered(session, admin_client):
    """The other half of the same distinction: `null` is a value an admin may
    choose on purpose, and has to be expressible over HTTP or "unmetered" is
    a state only SQL can reach."""
    repo.set_tenant_caps(session, max_concurrent_runs=3, monthly_run_quota=10)

    body = _set_caps(admin_client, {"monthly_run_quota": None}).json()

    assert body["monthly_run_quota"] is None
    assert body["at_monthly_quota"] is False, "an unmetered cap is never full"
    assert body["max_concurrent_runs"] == 3


def test_a_negative_cap_is_refused(session, admin_client):
    repo.set_tenant_caps(session, max_concurrent_runs=3)

    assert _set_caps(admin_client, {"max_concurrent_runs": -1}).status_code == 422
    assert repo.tenant_caps(session).max_concurrent_runs == 3, "nothing was written"


def test_the_change_is_audited_with_both_caps_on_both_sides(session, admin_client):
    """Story 5's audit half. Both caps on both sides, not just the one that
    moved, so "what were this tenant's limits afterwards?" is answerable from
    one row rather than by replaying every earlier one."""
    from app import audit
    from app.domain.audit import Action

    repo.set_tenant_caps(session, max_concurrent_runs=3, monthly_run_quota=10)

    _set_caps(admin_client, {"max_concurrent_runs": 9})

    changes = [e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE]
    latest = changes[0]
    assert latest.before == {"max_concurrent_runs": 3, "monthly_run_quota": 10}
    assert latest.after == {"max_concurrent_runs": 9, "monthly_run_quota": 10}
    assert latest.actor == SEED_ADMIN_EMAIL, "the acting admin, not `system`"


def test_the_caps_are_committed_rather_than_only_flushed(session_factory, admin_client_per_request):
    """Two sessions, because one cannot see a missing commit.

    `db.get_session` only closes; every write commits in the module below the
    route. A route that merely flushed would answer 200 and discard the row in
    production, and the single-session `client` fixture would still pass --
    which is how P5-06's prompt override shipped. So the read is taken through
    a *second* session, which only a committed row reaches.
    """
    client = admin_client_per_request

    assert client.put("/usage/caps", json={"monthly_run_quota": 42}).status_code == 200

    with session_factory() as s, tenant_scope(DEFAULT_TENANT_ID):
        assert repo.tenant_caps(s).monthly_run_quota == 42


def test_a_quota_change_cannot_reach_another_tenants_caps(session, admin_client):
    """"By id or otherwise": there is no id to pass, and passing one anyway
    changes nothing.

    The route takes no tenant in its path because there is no tenant to name
    but your own -- `repo.set_tenant_caps` writes to `current_tenant_id()`,
    which `require_auth` bound from the session. So this is not a check the
    surface performs, it is a request the surface cannot express, and the test
    says so by trying the only two ways it could be expressed.
    """
    from app.models import Tenant

    second = Tenant(name="Second", slug="second")
    session.add(second)
    session.commit()
    session.refresh(second)
    with tenant_scope(second.id):
        repo.set_tenant_caps(session, max_concurrent_runs=1, monthly_run_quota=2)

    # An id smuggled into the body is ignored, not honoured and not an error:
    # it is simply not part of the request's vocabulary.
    assert _set_caps(
        admin_client, {"tenant_id": second.id, "max_concurrent_runs": 50}
    ).status_code == 200

    with tenant_scope(second.id):
        theirs = repo.tenant_caps(session)
    assert (theirs.max_concurrent_runs, theirs.monthly_run_quota) == (1, 2)
    with tenant_scope(DEFAULT_TENANT_ID):
        assert repo.tenant_caps(session).max_concurrent_runs == 50


def test_a_change_that_changes_nothing_writes_no_audit_row(session, admin_client):
    """The spec asks that "each change" be audited, and this is not one.

    A row whose `before` equals its `after` says nothing happened, in the one
    column a compliance reader filters on. Two shapes of no-op: a body with no
    caps in it at all, and a body repeating what is already stored.
    """
    from app import audit
    from app.domain.audit import Action

    repo.set_tenant_caps(session, max_concurrent_runs=3, monthly_run_quota=10)
    before = len([e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE])

    assert _set_caps(admin_client, {}).status_code == 200
    assert _set_caps(admin_client, {"max_concurrent_runs": 3}).status_code == 200

    after = len([e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE])
    assert after == before, "neither no-op is in the trail"
    # And a real change still is, so the rule has not swallowed the feature.
    _set_caps(admin_client, {"max_concurrent_runs": 4})
    assert len(
        [e for e in audit.entries(session) if e.action is Action.QUOTA_CHANGE]
    ) == before + 1
