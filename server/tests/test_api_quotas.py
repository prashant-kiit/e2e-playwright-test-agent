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
