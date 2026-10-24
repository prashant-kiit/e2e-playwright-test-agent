"""The revisions read surface: the operator's window into a target's tree.

Prior art: test_api.py -- a TestClient with the session and the blob store
overridden. Every read must resolve through a row and filter by tenant, so a
blob is never served by key alone (DESIGN.md §9); the tests for that are at the
bottom.

P3 removed two routes from this surface. There is **no snapshot action**: the
filesystem is not authoritative, so "snapshot the disk" stopped meaning
anything. And there is **no parity route**: with one copy of the truth left there
is nothing to compare it against, and the property parity checked by comparison
is now checked by construction (test_hydrate.py's round trip).

What writes a revision instead: creating a target, an operator's story or config
edit (test_authoring.py), and a run's ingest at a step boundary
(test_step_boundary_revisions.py).
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError

from app import api
from app.api import get_bootstrap_runner, get_launcher, get_storage
from app.auth import require_auth
from app.db import get_session
from app.delivery import render
from app.main import app
from app.models import FileIndex, Revision, Tenant
from app.tenancy import current_tenant_id
from tests.storage_helpers import FakeStorage
from tests.target_helpers import target_body


@pytest.fixture()
def client(session):
    store = FakeStorage()
    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda _id: None)
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[require_auth] = lambda: None
    app.dependency_overrides[get_bootstrap_runner] = lambda: (lambda a: None)
    c = TestClient(app)
    c.store = store
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def target(client):
    """A target created through the portal, so it has its revision 1."""
    pid = client.post("/projects", json={"name": "demo"}).json()["id"]
    created = client.post(
        f"/projects/{pid}/targets", json=target_body(app="demo", name="Demo")
    ).json()
    return created["target"]["id"]


def _write_story(client, target_id, story_id="SCRUM-1", slug="checkout", content=None):
    return client.put(
        f"/targets/{target_id}/stories/{story_id}",
        json={
            "story_id": story_id,
            "slug": slug,
            "content": content or f"# User Story: {story_id} - Checkout Flow\n",
        },
    )


# --- the revision list ----------------------------------------------------

def test_a_new_target_has_exactly_one_revision(client, target):
    rows = client.get(f"/targets/{target}/revisions").json()

    assert [row["rev"] for row in rows] == [1]
    assert rows[0]["author"] == "operator"
    assert rows[0]["parent_rev"] is None


def test_the_revision_list_carries_what_the_portal_shows(client, target):
    _write_story(client, target)
    _write_story(client, target, content="# User Story: SCRUM-1 - Checkout Flow v2\n")

    r = client.get(f"/targets/{target}/revisions")

    assert r.status_code == 200
    rows = r.json()
    assert [row["rev"] for row in rows] == [3, 2, 1]  # newest first
    assert rows[0]["parent_rev"] == 2
    for row in rows:
        assert row["author"]
        assert row["created_at"]
        assert row["file_count"] > 0


def test_the_revision_list_is_empty_for_an_unknown_target(client):
    assert client.get("/targets/999/revisions").status_code == 404


# --- a revision's files ---------------------------------------------------

def test_the_file_list_matches_what_the_revision_committed(client, target):
    rev = _write_story(client, target).json()["revision"]

    r = client.get(f"/revisions/{rev['id']}/files")

    assert r.status_code == 200
    rows = r.json()
    paths = [row["path"] for row in rows]
    assert paths == sorted(paths)
    assert "user-stories/SCRUM-1-checkout.md" in paths
    assert "playwright.config.ts" in paths
    for row in rows:
        assert row["size"] > 0
        assert row["blob_key"].startswith(f"tenant/{current_tenant_id()}/blobs/")


def test_a_file_is_served_byte_identical_out_of_blob_storage(client, target):
    content = "# User Story: SCRUM-1 - Checkout Flow\n\nAs a user...\n"
    rev = _write_story(client, target, content=content).json()["revision"]

    r = client.get(
        f"/revisions/{rev['id']}/file", params={"path": "user-stories/SCRUM-1-checkout.md"}
    )

    assert r.status_code == 200
    assert r.content == content.encode()


def test_a_json_tracked_file_survives_the_round_trip_byte_identical(client, target):
    """A tracked file is source text to display, never a document to re-encode.

    Served as application/json, package.json gets parsed and re-serialised by
    the browser before it reaches the viewer -- different whitespace, different
    key order, not the bytes that were stored. The route therefore declares a
    text media type for every tracked path.
    """
    rev = client.get(f"/targets/{target}/revisions").json()[0]
    source = render.TEMPLATES_DIR / "package.json"

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})

    assert r.status_code == 200
    assert r.content == source.read_bytes()
    assert r.headers["content-type"].startswith("text/plain")


def test_every_tracked_path_is_served_as_text(client, target):
    """Including .ts, which mimetypes otherwise guesses as video/mp2t."""
    rev = client.get(f"/targets/{target}/revisions").json()[0]

    for path in ("playwright.config.ts", ".gitignore", "seed.spec.ts"):
        r = client.get(f"/revisions/{rev['id']}/file", params={"path": path})
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/plain"), path


def test_a_path_the_revision_does_not_contain_is_refused(client, target):
    rev = client.get(f"/targets/{target}/revisions").json()[0]

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "app.json"})

    assert r.status_code == 404
    assert r.headers["content-type"].startswith("application/json")


def test_a_file_route_on_a_missing_revision_is_404(client):
    assert client.get("/revisions/999/file", params={"path": "package.json"}).status_code == 404
    assert client.get("/revisions/999/files").status_code == 404


def test_another_tenants_revision_is_not_readable(client, target, session):
    """Asserted with a second tenant row, so the filter is doing real work."""
    session.add(Tenant(id=2, name="other"))
    session.commit()
    rev = client.get(f"/targets/{target}/revisions").json()[0]

    session.query(Revision).filter(Revision.id == rev["id"]).update({"tenant_id": 2})
    session.query(FileIndex).filter(FileIndex.revision_id == rev["id"]).update({"tenant_id": 2})
    session.commit()

    assert client.get(f"/revisions/{rev['id']}/files").status_code == 404
    assert (
        client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"}).status_code
        == 404
    )
    assert client.get(f"/targets/{target}/revisions").json() == []


def test_a_blob_missing_from_the_store_is_a_502_not_a_crash(client, target):
    rev = client.get(f"/targets/{target}/revisions").json()[0]
    client.store.objects.clear()

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})

    assert r.status_code == 502


def test_the_whole_revision_surface_is_read_only(client, target):
    """Displaying a tree must not be able to change one."""
    rev = client.get(f"/targets/{target}/revisions").json()[0]
    before = dict(client.store.objects)

    client.get(f"/targets/{target}/revisions")
    client.get(f"/revisions/{rev['id']}/files")
    client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})

    assert client.store.objects == before
    assert [row["rev"] for row in client.get(f"/targets/{target}/revisions").json()] == [1]


# --- the two routes that are gone -----------------------------------------

def test_there_is_no_snapshot_route(client, target):
    """No endpoint claims to snapshot a filesystem that is not authoritative."""
    assert client.post(f"/targets/{target}/revisions/snapshot").status_code == 404


def test_there_is_no_parity_route(client, target):
    """With one copy of the truth left there is nothing to compare against; the
    property is checked by construction instead (test_hydrate.py)."""
    assert client.get(f"/targets/{target}/parity").status_code == 404


# --- losing the revision race --------------------------------------------

def _lose_the_race(*_args, **_kwargs):
    """What a concurrent writer looks like from inside a write route."""
    raise IntegrityError(
        "INSERT INTO revisions", {}, Exception("unique(target_id, rev)")
    )


@pytest.mark.parametrize(
    "write",
    [
        pytest.param(lambda c, t: _write_story(c, t), id="story-write"),
        pytest.param(
            lambda c, t: c.delete(f"/targets/{t}/stories/SCRUM-1"), id="story-delete"
        ),
        pytest.param(
            lambda c, t: c.patch(
                f"/targets/{t}/config", json={"base_url": "https://other.example.com"}
            ),
            id="config-edit",
        ),
    ],
)
def test_losing_the_revision_race_is_a_409_on_every_write_route(
    client, target, monkeypatch, write
):
    """`unique(target_id, rev)` is the OCC point, and every write can lose it.

    So every write route owes the operator a 409 and not a 500. Only the story
    write used to say it; this is the test that stops the next route from being
    added without it.
    """
    for name in ("write_story", "delete_story", "update_config"):
        monkeypatch.setattr(api.authoring, name, _lose_the_race)

    response = write(client, target)

    assert response.status_code == 409
    assert "reload" in response.json()["detail"]
