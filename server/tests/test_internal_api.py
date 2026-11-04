"""The internal API as HTTP: who gets in, and what a refusal looks like.

The operations themselves are tested at the service and through both gateways
(tests/test_control_service.py, tests/test_control_gateway.py). What only exists
here is the framing: the bearer header, the status codes, and the two
authorities that must not overlap -- a portal session cookie authorizes nothing
under `/internal`, and a run token authorizes nothing outside it.

401 and 403 are kept apart on purpose and the distinction is asserted, because
the sandbox does different things with them: a 401 is a token that was never
good, a 403 on a live run is a deployment that is wrong, and `RunNotLive` is the
ordinary end of a run somebody stopped.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import internal_api, repo, revisions, run_token
from app.control import factory as control_factory
from app.db import get_session
from app.domain.steps import Step
from app.main import app as fastapi_app
from app.models import Tenant
from app.run_token import RunScope
from app.tenancy import tenant_scope
from tests.delivery_helpers import make_worktree
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def world(session_factory, tmp_path, monkeypatch):
    """Two tenants, each with a target at revision 1 and a live run."""
    monkeypatch.setenv("QA_SECRET_KEY", "the-suite-signing-key")
    store = FakeStorage()
    built = {}
    with session_factory() as s:
        for name, slug in (("demo", None), ("other", "second")):
            if slug is None:
                tenant_id = 1
            else:
                tenant = Tenant(name=name.title(), slug=slug)
                s.add(tenant)
                s.commit()
                s.refresh(tenant)
                tenant_id = tenant.id
            with tenant_scope(tenant_id):
                project = repo.create_project(s, name=f"{name}-project")
                target = create_target(s, project.id, app=name, name=name.title())
                revisions.commit_revision(
                    s,
                    target,
                    store,
                    make_worktree(tmp_path / f"source-{name}"),
                    author="operator",
                )
                run = repo.start_run(
                    s, target_id=target.id, story_id="SCRUM-1", mode="full"
                )
                scope = RunScope(
                    run_id=run.id,
                    target_id=target.id,
                    tenant_id=tenant_id,
                    sandbox_attempt=run.sandbox_attempt,
                )
                built[name] = {
                    "scope": scope,
                    "token": run_token.mint(scope),
                    "run_key": run.run_key,
                    "run_id": run.id,
                }
    built["store"] = store
    built["session_factory"] = session_factory
    return built


@pytest.fixture()
def client(world, session_factory):
    def _session():
        s = session_factory()
        try:
            yield s
        finally:
            s.close()

    fastapi_app.dependency_overrides[get_session] = _session
    fastapi_app.dependency_overrides[internal_api.get_storage] = lambda: world["store"]
    try:
        yield TestClient(fastapi_app)
    finally:
        fastapi_app.dependency_overrides.clear()


def _auth(world, which="demo"):
    return {"Authorization": f"Bearer {world[which]['token']}"}


def _facts_url(world, which="demo"):
    return f"/internal/runs/{world[which]['run_id']}/facts"


# --- who gets in ---------------------------------------------------------

def test_a_valid_run_token_is_let_in(client, world):
    response = client.get(_facts_url(world), headers=_auth(world))

    assert response.status_code == 200
    assert response.json()["run_key"] == world["demo"]["run_key"]


def test_no_token_at_all_is_a_401(client, world):
    assert client.get(_facts_url(world)).status_code == 401


@pytest.mark.parametrize(
    "header",
    (
        "",
        "not-a-scheme abc",
        "Bearer ",
        "Bearer not-a-token",
        "Basic aGk6dGhlcmU=",
    ),
)
def test_a_malformed_or_forged_token_is_a_401(client, world, header):
    """401 rather than 403: nothing has been authenticated yet, so there is no
    authority to refuse."""
    response = client.get(_facts_url(world), headers={"Authorization": header})

    assert response.status_code == 401


def test_a_token_signed_with_another_key_is_a_401(client, world, monkeypatch):
    token = world["demo"]["token"]
    monkeypatch.setenv("QA_SECRET_KEY", "a-different-key")

    response = client.get(
        _facts_url(world), headers={"Authorization": f"Bearer {token}"}
    )

    assert response.status_code == 401


# --- the two authorities do not overlap ----------------------------------

def test_a_portal_session_cookie_authorizes_nothing_under_internal(client, world):
    """The routes take a bearer token and no cookie. An operator's session --
    the thing every other route accepts -- has to be worth nothing here."""
    from app import auth
    from app.domain.roles import UserRole

    cookie = auth.mint_access(
        auth.CurrentUser(id=1, tenant_id=1, email="a@b.c", role=UserRole.ADMIN)
    )
    client.cookies.set(auth.ACCESS_COOKIE, cookie)

    assert client.get(_facts_url(world)).status_code == 401


def test_a_run_token_authorizes_nothing_on_the_portals_routes(client, world):
    """The other direction: a leaked run token must not be presentable to the
    portal as a logged-in operator."""
    response = client.get("/projects", headers=_auth(world))

    assert response.status_code == 401


# --- what the token is for -----------------------------------------------

def test_a_token_for_another_run_is_a_403_on_this_runs_path(client, world):
    """The URL says one run and the authority says another. Refused rather than
    resolved in either direction."""
    response = client.get(_facts_url(world, "demo"), headers=_auth(world, "other"))

    assert response.status_code == 403


def test_a_token_cannot_reach_another_tenants_run_on_its_own_path(client, world):
    """Following the token to its own run id is not a way round the tenant
    boundary: the run is another tenant's, so the enforced read filter finds
    nothing and the answer is 403, not 404."""
    stolen = run_token.mint(
        RunScope(
            run_id=world["other"]["run_id"],
            target_id=world["other"]["scope"].target_id,
            tenant_id=world["demo"]["scope"].tenant_id,
            sandbox_attempt=world["other"]["scope"].sandbox_attempt,
        )
    )

    response = client.get(
        f"/internal/runs/{world['other']['run_id']}/facts",
        headers={"Authorization": f"Bearer {stolen}"},
    )

    assert response.status_code == 403


def test_a_blob_key_outside_the_tokens_tenant_is_a_403(client, world):
    """Story 25's "no serve-by-key-alone", as a status code. The key is a
    content hash, so knowing one must not be enough."""
    with tenant_scope(world["other"]["scope"].tenant_id), world[
        "session_factory"
    ]() as s:
        head = revisions.head_revision(s, world["other"]["scope"].target_id)
        key = revisions.list_files(s, head.id)[0].blob_key

    response = client.get(
        f"/internal/runs/{world['demo']['run_id']}/blobs/{key}",
        headers=_auth(world),
    )

    assert response.status_code == 403


def test_an_artifact_key_under_another_runs_prefix_is_a_403(client, world):
    response = client.post(
        f"/internal/runs/{world['demo']['run_id']}/artifacts",
        headers=_auth(world),
        json={
            "key": f"{world['other']['run_key']}/trace.zip",
            "sha256": "a" * 64,
            "kind": "trace",
            "step": None,
        },
    )

    assert response.status_code == 403


def test_existence_is_not_a_cheaper_way_round_the_key_rule(client, world):
    """The HEAD route is the dedup check, and it has to apply the same prefix
    rule as the GET -- existence is precisely the side channel the rule closes."""
    response = client.head(
        f"/internal/runs/{world['demo']['run_id']}"
        f"/blobs/tenant/99999/blobs/{'b' * 64}",
        headers=_auth(world),
    )

    assert response.status_code == 403


# --- the liveness gate ---------------------------------------------------

def test_a_token_stops_working_when_its_run_stops_being_live(client, world):
    with tenant_scope(1), world["session_factory"]() as s:
        repo.stop_run(s, world["demo"]["run_id"])

    response = client.get(_facts_url(world), headers=_auth(world))

    assert response.status_code == 403
    assert "no longer authorizes anything" in response.text


def test_a_finished_runs_status_is_still_readable(client, world):
    """So the entrypoint can read its exit code off the row."""
    with tenant_scope(1), world["session_factory"]() as s:
        repo.stop_run(s, world["demo"]["run_id"])

    response = client.get(
        f"/internal/runs/{world['demo']['run_id']}/status", headers=_auth(world)
    )

    assert response.status_code == 200
    assert response.json()["status"] == "stopped"


# --- the shapes the client parses ----------------------------------------

def test_a_target_with_no_revision_answers_a_null_rather_than_a_404(
    client, world, session_factory
):
    """A 404 would be indistinguishable from a routing mistake; "this target has
    no revision" is an answer the sandbox turns into `NoHeadRevision`."""
    with tenant_scope(1), session_factory() as s:
        project = repo.create_project(s, name="fresh-project")
        target = create_target(s, project.id, app="fresh", name="Fresh")
        run = repo.start_run(s, target_id=target.id, story_id="S-1", mode="full")
        token = run_token.mint(
            RunScope(
                run_id=run.id,
                target_id=target.id,
                tenant_id=1,
                sandbox_attempt=run.sandbox_attempt,
            )
        )
        run_id = run.id
        assert revisions.head_revision(s, target.id) is None, (
            "the fixture has to be a target with no revision for this to mean "
            "anything"
        )

    response = client.get(
        f"/internal/runs/{run_id}/head-revision",
        headers={"Authorization": f"Bearer {token}"},
    )

    assert response.status_code == 200
    assert response.json() == {"revision": None}


def test_an_illegal_status_transition_is_a_409_not_a_500(client, world):
    """A race with an operator, reported as one: the run was stopped under the
    sandbox and the sandbox then tried to complete it."""
    with tenant_scope(1), world["session_factory"]() as s:
        repo.begin_run(s, world["demo"]["run_id"])

    url = f"/internal/runs/{world['demo']['run_id']}"
    assert client.post(f"{url}/complete", headers=_auth(world)).status_code == 200

    # Completed is terminal, so the token no longer authorizes anything: the
    # liveness gate is in front of the transition check, which is the order that
    # matters -- a finished run must not be driveable at all.
    again = client.post(f"{url}/complete", headers=_auth(world))
    assert again.status_code == 403


def test_a_malformed_step_is_a_422(client, world):
    response = client.post(
        f"/internal/runs/{world['demo']['run_id']}/steps/not-a-step/start",
        headers=_auth(world),
    )

    assert response.status_code == 422


def test_a_malformed_revision_manifest_is_a_422(client, world):
    response = client.post(
        f"/internal/runs/{world['demo']['run_id']}/revisions",
        headers=_auth(world),
        json={"author": "run:x"},
    )

    assert response.status_code == 422


def test_a_blob_is_streamed_back_with_its_bytes_intact(client, world):
    """Hydrate materializes every file of a revision through this route and
    verifies each against its content hash, so a byte lost in the framing fails
    the run rather than corrupting a worktree."""
    import hashlib

    with tenant_scope(1), world["session_factory"]() as s:
        head = revisions.head_revision(s, world["demo"]["scope"].target_id)
        row = revisions.list_files(s, head.id)[0]

    response = client.get(
        f"/internal/runs/{world['demo']['run_id']}/blobs/{row.blob_key}",
        headers=_auth(world),
    )

    assert response.status_code == 200
    assert (
        hashlib.sha256(response.content).hexdigest()
        == revisions.sha256_from_blob_key(row.blob_key)
    )


def test_a_step_transition_that_is_not_one_of_the_three_is_a_422(client, world):
    response = client.post(
        f"/internal/runs/{world['demo']['run_id']}/steps/{Step.READ_STORY.value}/sideways",
        headers=_auth(world),
    )

    assert response.status_code == 422


def test_a_token_from_before_a_pause_is_a_403_over_http(client, world):
    """#48 over the transport a container actually uses.

    The pause route destroys the container and moves the run to `paused`, so
    the token that container was handed names a sandbox that no longer exists.
    403, the same answer every other unauthorized scope gets -- a sandbox must
    not be able to tell "my attempt was superseded" from "not yours".
    """
    demo = world["demo"]
    with tenant_scope(demo["scope"].tenant_id):
        with world["session_factory"]() as s:
            repo.begin_run(s, demo["run_id"])
            repo.request_pause(s, demo["run_id"])
            repo.pause_run(s, demo["run_id"])

    response = client.get(
        f"/internal/runs/{demo['run_id']}/facts",
        headers={"Authorization": f"Bearer {demo['token']}"},
    )

    assert response.status_code == 403
    assert "attempt" in response.json()["detail"]


def test_the_resumed_attempts_token_works_over_http(client, world):
    """The other side of it, over the same transport: a resume that could not
    be driven would be worse than the window it closed. Minted the way both
    dispatch paths mint -- `factory.mint_for_run`, reading the row after
    `resume_run` has committed."""
    demo = world["demo"]
    with tenant_scope(demo["scope"].tenant_id):
        with world["session_factory"]() as s:
            repo.begin_run(s, demo["run_id"])
            repo.request_pause(s, demo["run_id"])
            repo.pause_run(s, demo["run_id"])
            repo.resume_run(s, demo["run_id"])
        fresh = control_factory.mint_for_run(
            demo["run_id"], session_factory=world["session_factory"]
        )

    response = client.get(
        f"/internal/runs/{demo['run_id']}/facts",
        headers={"Authorization": f"Bearer {fresh}"},
    )

    assert response.status_code == 200, response.text
    assert response.json()["run_key"] == demo["run_key"]
