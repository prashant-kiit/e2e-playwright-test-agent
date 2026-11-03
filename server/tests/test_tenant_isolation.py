"""Cross-tenant isolation: what one tenant may read of another's (P5-02, #32).

Two tenants, each with a real logged-in session over HTTP, and the question
asked of every read path there is a route for: **does a row I do not own ever
come back?** Not "is the filter present in the query I happened to read" --
every assertion here goes through the boundary an attacker actually holds, a
session cookie, and the ids of rows belonging to someone else.

The seam is deliberately two-level (agreed before the work started):

* **over HTTP**, because that is the trust boundary, and because a route that
  reads a row by id without going through `repo` -- `/artifacts/{id}/content`
  was one -- is invisible to any test that drives the repository directly;
* **at the repository**, in `test_tenant_isolation_repo.py`, because a read path
  with no route over it still has to be scoped, and enumerating the read
  functions there is what keeps the coverage exhaustive as new ones arrive.

What makes these pass is `tenancy.install_read_guard`: one `do_orm_execute`
listener that adds the `tenant_id` filter to every ORM SELECT. The tests say
nothing about that mechanism, which is the point -- they are the specification a
replacement would have to satisfy too.
"""

from __future__ import annotations

from dataclasses import dataclass

import pytest
from fastapi.testclient import TestClient

from app import apphub
from app.api import get_bootstrap_runner, get_launcher, get_resolver, get_storage
from app.auth import hash_password
from app.db import get_session
from app.domain.roles import UserRole
from app.main import app
from app.models import Artifact, Tenant, User
from tests.storage_helpers import FakeStorage
from tests.target_helpers import public_resolver, target_body

# Tenant A is the one the migration seeds; tenant B is created here. Both users
# are admins so that an admin-gated route is reachable as either -- the question
# in this file is never "was I allowed to do this?" but "whose rows did I see?".
A_SLUG = "default"
A_EMAIL = "a@example.com"
B_ID = 2
B_SLUG = "second"
B_EMAIL = "b@example.com"
PASSWORD = "pw"


@dataclass(frozen=True)
class Estate:
    """One tenant's rows: what the *other* tenant must not be able to reach."""

    project_id: int
    target_id: int
    run_id: int
    run_key: str
    artifact_id: int
    artifact_key: str
    revision_id: int


@pytest.fixture()
def store():
    """One blob store shared by both tenants' clients.

    Deliberately shared: a per-tenant fake would make the artifact-content test
    pass for the wrong reason -- the bytes missing from *this* client's store
    rather than the row being refused. Here the bytes are present and reachable,
    and the only thing standing between tenant B and them is the row filter.
    """
    return FakeStorage()


@pytest.fixture()
def _overrides(session, store, monkeypatch):
    """The app wired to the test session, with real auth left in place."""
    monkeypatch.setenv("QA_SECRET_KEY", "test-key")
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda run_id: None)
    app.dependency_overrides[get_resolver] = lambda: public_resolver
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[get_bootstrap_runner] = lambda: (
        lambda a: apphub.BootstrapOutcome(ok=True, output="synced")
    )
    yield
    app.dependency_overrides.clear()


def _add_user(session, *, email, tenant_id):
    session.add(
        User(
            tenant_id=tenant_id,
            email=email,
            role=UserRole.ADMIN,
            credential=hash_password(PASSWORD),
        )
    )
    session.commit()


def _login(slug: str, email: str) -> TestClient:
    client = TestClient(app)
    r = client.post(
        "/auth/login", json={"tenant": slug, "email": email, "password": PASSWORD}
    )
    assert r.status_code == 200, r.text
    return client


@pytest.fixture()
def client_a(_overrides, session):
    _add_user(session, email=A_EMAIL, tenant_id=1)
    return _login(A_SLUG, A_EMAIL)


@pytest.fixture()
def client_b(_overrides, session):
    session.add(Tenant(id=B_ID, slug=B_SLUG, name="Second"))
    session.commit()
    _add_user(session, email=B_EMAIL, tenant_id=B_ID)
    return _login(B_SLUG, B_EMAIL)


def _build_estate(client: TestClient, session, store, *, tenant_id: int, app_slug: str) -> Estate:
    """A project, target, run, revision and artifact owned by whoever is logged in.

    Built through the API wherever a route exists, so the rows carry the tenant
    the *session* resolves rather than one a fixture asserted. Only the artifact
    is inserted directly: nothing but a run collects those, and a run here is
    never executed.
    """
    project_id = client.post("/projects", json={"name": f"p-{app_slug}"}).json()["id"]
    created = client.post(
        f"/projects/{project_id}/targets",
        json=target_body(app=app_slug, name=app_slug.title()),
    ).json()
    target_id = created["target"]["id"]
    run = client.post(
        f"/targets/{target_id}/runs", json={"story_id": "SCRUM-1", "mode": "full"}
    ).json()

    key = f"{run['run_key']}/report.html"
    store.objects[key] = (f"<html>{app_slug} secrets</html>".encode(), "text/html")
    artifact = Artifact(
        tenant_id=tenant_id,
        run_id=run["id"],
        step="heal",
        kind="report",
        s3_key=key,
        sha256="x" * 64,
        version=1,
    )
    session.add(artifact)
    session.commit()

    revisions = client.get(f"/targets/{target_id}/revisions").json()
    return Estate(
        project_id=project_id,
        target_id=target_id,
        run_id=run["id"],
        run_key=run["run_key"],
        artifact_id=artifact.id,
        artifact_key=key,
        revision_id=revisions[0]["id"],
    )


@pytest.fixture()
def estate_a(client_a, session, store) -> Estate:
    return _build_estate(client_a, session, store, tenant_id=1, app_slug="alpha")


# --- a row owned by someone else, asked for by id -------------------------

def test_another_tenants_artifact_bytes_are_not_served(client_b, estate_a, store):
    """The sharpest version of the hole this ticket closes.

    `/artifacts/{id}/content` streamed the blob behind any artifact row it could
    `session.get`, and the id is a small integer. Auth gated *whether* you were
    logged in, never *whose* artifact you asked for -- so any logged-in user of
    any tenant could walk the ids and download every other tenant's reports,
    screenshots and traces.

    The bytes are in the store and reachable (the fake is shared), so nothing
    but the row filter is refusing this.
    """
    r = client_b.get(f"/artifacts/{estate_a.artifact_id}/content")
    assert r.status_code == 404
    assert b"alpha secrets" not in r.content


def test_another_tenants_run_is_not_readable_by_id(client_b, estate_a):
    """A run row carries the story under test and the target it ran against."""
    assert client_b.get(f"/runs/{estate_a.run_id}").status_code == 404


def test_every_route_that_takes_someone_elses_id_is_a_404(client_b, estate_a):
    """The direct-id surface, swept in one test.

    Each of these is a route whose only argument is an integer id belonging to
    another tenant. 404 rather than 403 deliberately: a reader who does not own
    the row must not be able to tell "exists, not yours" from "does not exist",
    or walking the ids becomes an inventory of what other tenants have.

    Swept together because the risk is uniform and the list is the valuable
    part -- a route added later with an id in its path belongs here, and an
    empty-list assertion would not have caught `/artifacts/{id}/content`.
    """
    target, run, revision = estate_a.target_id, estate_a.run_id, estate_a.revision_id
    for method, path in (
        ("get", f"/runs/{run}"),
        ("get", f"/runs/{run}/steps"),
        ("get", f"/runs/{run}/artifacts"),
        ("get", f"/runs/{run}/events"),
        ("get", f"/artifacts/{estate_a.artifact_id}/content"),
        ("get", f"/targets/{target}/stories"),
        ("get", f"/targets/{target}/stories/SCRUM-1"),
        ("get", f"/targets/{target}/revisions"),
        ("get", f"/targets/{target}/delivery"),
        ("get", f"/revisions/{revision}/files"),
        ("get", f"/revisions/{revision}/file?path=README.md"),
    ):
        r = getattr(client_b, method)(path)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code}"


def test_a_write_to_another_tenants_target_is_a_404(client_b, estate_a):
    """Not only reads. Every write route resolves its row through a filtered
    read first, so a foreign id is refused before anything is written -- a
    story saved into another tenant's tree would be the worst version of this
    bug, because it would also be delivered to their repository."""
    target, run = estate_a.target_id, estate_a.run_id
    for method, path, body in (
        (
            "put",
            f"/targets/{target}/stories/SCRUM-1",
            {"story_id": "SCRUM-1", "slug": "theirs-now", "content": "# theirs now"},
        ),
        ("delete", f"/targets/{target}/stories/SCRUM-1", None),
        ("patch", f"/targets/{target}/config", {"name": "renamed by B"}),
        ("post", f"/targets/{target}/runs", {"story_id": "SCRUM-1", "mode": "full"}),
        ("post", f"/runs/{run}/stop", None),
        ("post", f"/runs/{run}/pause", None),
        ("post", f"/runs/{run}/resume", None),
    ):
        call = getattr(client_b, method)
        r = call(path, json=body) if body is not None else call(path)
        assert r.status_code == 404, f"{method.upper()} {path} -> {r.status_code}"


def test_the_listings_show_each_tenant_only_its_own(client_a, client_b, estate_a, session, store):
    """Two populated tenants, so emptiness cannot be what makes this pass.

    The other tests give tenant B nothing; here it has an estate of its own and
    the listings must still separate them. That is the difference between "the
    filter is applied" and "the filter has the right value" -- a guard pinned
    to one tenant would pass every test above.
    """
    estate_b = _build_estate(client_b, session, store, tenant_id=B_ID, app_slug="bravo")

    assert [p["name"] for p in client_a.get("/projects").json()] == ["p-alpha"]
    assert [p["name"] for p in client_b.get("/projects").json()] == ["p-bravo"]
    assert [t["app"] for t in client_a.get("/targets").json()] == ["alpha"]
    assert [t["app"] for t in client_b.get("/targets").json()] == ["bravo"]
    assert [r["id"] for r in client_a.get("/runs").json()] == [estate_a.run_id]
    assert [r["id"] for r in client_b.get("/runs").json()] == [estate_b.run_id]

    # ...and each still reaches its own artifact bytes, which is the control:
    # a filter that refused everyone would satisfy every assertion above.
    mine = client_b.get(f"/artifacts/{estate_b.artifact_id}/content")
    assert mine.status_code == 200
    assert mine.content == b"<html>bravo secrets</html>"


def test_a_project_id_from_another_tenant_cannot_be_built_under(client_b, estate_a):
    """A foreign *parent* id, which is the other shape of this bug.

    `POST /projects/{id}/targets` checks the project exists before inserting,
    and that check is now filtered -- so tenant B cannot hang a target off
    tenant A's project, which would have put a row with B's tenant_id inside
    A's project and shown up in neither tenant's listing correctly.
    """
    r = client_b.post(
        f"/projects/{estate_a.project_id}/targets",
        json=target_body(app="smuggled", name="Smuggled"),
    )
    assert r.status_code == 404
