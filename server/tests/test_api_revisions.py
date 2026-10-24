"""The revisions read surface, and the manual snapshot action.

Prior art: test_api.py -- a TestClient with the session and the blob store
overridden. Every read here must resolve through a row and filter by tenant, so
a blob is never served by key alone (DESIGN.md §9); the tests for that are at
the bottom.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app import repo
from app.api import get_launcher, get_storage
from app.auth import require_auth
from app.db import get_session
from app.delivery import render
from app.main import app
from app.models import FileIndex, Revision, Tenant
from app.tenancy import current_tenant_id
from tests.delivery_helpers import make_workspace
from tests.storage_helpers import FakeStorage
from tests.target_helpers import create_target


@pytest.fixture()
def client(session, tmp_path, monkeypatch):
    """A client over a real temp workspace with one app, `demo`."""
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    store = FakeStorage()

    app.dependency_overrides[get_session] = lambda: session
    app.dependency_overrides[get_launcher] = lambda: (lambda _id: None)
    app.dependency_overrides[get_storage] = lambda: store
    app.dependency_overrides[require_auth] = lambda: None
    c = TestClient(app)
    c.store = store
    c.workspace = workspace
    yield c
    app.dependency_overrides.clear()


@pytest.fixture()
def target(session):
    project = repo.create_project(session, name="demo")
    return create_target(session, project.id, app="demo", name="Demo")


# --- the snapshot action (P2-only scaffolding) --------------------------

def test_snapshot_creates_a_baseline_for_a_never_run_target(client, target):
    r = client.post(f"/targets/{target.id}/revisions/snapshot")
    assert r.status_code == 201
    assert r.json()["created"] is True
    body = r.json()["revision"]
    assert body["rev"] == 1
    assert body["parent_rev"] is None
    assert body["produced_by_run_id"] is None
    assert len(body["tree_hash"]) == 64
    assert body["file_count"] == 10


def test_snapshotting_an_unchanged_tree_commits_nothing_and_says_so(client, target):
    client.post(f"/targets/{target.id}/revisions/snapshot")
    r = client.post(f"/targets/{target.id}/revisions/snapshot")
    assert r.status_code == 200  # not 201: nothing was created
    assert r.json()["created"] is False
    assert r.json()["revision"]["rev"] == 1


def test_snapshot_of_a_missing_target_is_404(client):
    assert client.post("/targets/999/revisions/snapshot").status_code == 404


def test_the_revision_list_carries_what_the_portal_shows(client, target):
    client.post(f"/targets/{target.id}/revisions/snapshot")
    (client.workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts").write_text("//2\n")
    client.post(f"/targets/{target.id}/revisions/snapshot")

    r = client.get(f"/targets/{target.id}/revisions")
    assert r.status_code == 200
    rows = r.json()
    assert [row["rev"] for row in rows] == [2, 1]  # newest first
    assert rows[0]["parent_rev"] == 1
    for row in rows:
        assert row["author"]
        assert row["created_at"]
        assert row["file_count"] == 10


def test_the_revision_list_is_empty_for_a_target_with_no_history(client, target):
    assert client.get(f"/targets/{target.id}/revisions").json() == []


# --- a revision's files (ticket 04) -------------------------------------

def test_the_file_list_matches_what_the_snapshot_committed(client, target):
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]

    r = client.get(f"/revisions/{rev['id']}/files")
    assert r.status_code == 200
    rows = r.json()
    assert [row["path"] for row in rows] == sorted(row["path"] for row in rows)
    assert "tests/checkout/cart.spec.ts" in [row["path"] for row in rows]
    for row in rows:
        assert row["size"] > 0
        assert row["blob_key"].startswith(f"tenant/{current_tenant_id()}/blobs/")


def test_a_file_is_served_byte_identical_out_of_blob_storage(client, target):
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]
    on_disk = client.workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts"

    r = client.get(
        f"/revisions/{rev['id']}/file", params={"path": "tests/checkout/cart.spec.ts"}
    )
    assert r.status_code == 200
    assert r.content == on_disk.read_bytes()


def test_a_json_tracked_file_survives_the_round_trip_byte_identical(client, target):
    """A tracked file is source text to display, never a document to re-encode.

    Served as application/json, package.json gets parsed and re-serialised by
    the browser before it reaches the viewer -- different whitespace, different
    key order, not the bytes that were stored. The route therefore declares a
    text media type for every tracked path.
    """
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]
    # package.json is an infra entry, so its bytes come from the template that
    # delivery pushes -- the same bytes the snapshot stored.
    source = render.TEMPLATES_DIR / "package.json"

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})
    assert r.status_code == 200
    assert r.content == source.read_bytes()
    assert r.headers["content-type"].startswith("text/plain")


def test_every_tracked_path_is_served_as_text(client, target):
    """Including .ts, which mimetypes otherwise guesses as video/mp2t."""
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]
    for path in ("playwright.config.ts", ".gitignore", "user-stories/SCRUM-1-checkout.md"):
        r = client.get(f"/revisions/{rev['id']}/file", params={"path": path})
        assert r.status_code == 200, path
        assert r.headers["content-type"].startswith("text/plain"), path


def test_a_path_the_revision_does_not_contain_is_refused(client, target):
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "app.json"})
    assert r.status_code == 404
    # app.json is on disk and in the blob store is not -- but even so, nothing
    # of it is streamed: the refusal is an error document, not the file.
    assert b"targetRepo" not in r.content
    assert r.headers["content-type"].startswith("application/json")


def test_a_file_route_on_a_missing_revision_is_404(client):
    assert client.get("/revisions/999/file", params={"path": "package.json"}).status_code == 404
    assert client.get("/revisions/999/files").status_code == 404


def test_another_tenants_revision_is_not_readable(client, target, session):
    """Asserted with a second tenant row, so the filter is doing real work."""
    session.add(Tenant(id=2, name="other"))
    session.commit()
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]

    # Reassign the revision and its files to the other tenant.
    session.query(Revision).filter(Revision.id == rev["id"]).update({"tenant_id": 2})
    session.query(FileIndex).filter(FileIndex.revision_id == rev["id"]).update({"tenant_id": 2})
    session.commit()

    assert client.get(f"/revisions/{rev['id']}/files").status_code == 404
    assert (
        client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"}).status_code
        == 404
    )
    assert client.get(f"/targets/{target.id}/revisions").json() == []


def test_a_blob_missing_from_the_store_is_a_502_not_a_crash(client, target):
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]
    client.store.objects.clear()

    r = client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})
    assert r.status_code == 502


def test_no_revision_route_writes_anything_but_the_snapshot_action(client, target):
    """The whole read surface is read-only: nothing here may make the database
    disagree with the authoritative filesystem."""
    rev = client.post(f"/targets/{target.id}/revisions/snapshot").json()["revision"]
    before = dict(client.store.objects)

    client.get(f"/targets/{target.id}/revisions")
    client.get(f"/revisions/{rev['id']}/files")
    client.get(f"/revisions/{rev['id']}/file", params={"path": "package.json"})
    client.get(f"/targets/{target.id}/parity")

    assert client.store.objects == before
    assert len(list(client_revisions(client, target))) == 1


def client_revisions(client, target):
    return client.get(f"/targets/{target.id}/revisions").json()


# --- parity (ticket 05) -------------------------------------------------

def test_parity_is_green_for_a_freshly_snapshotted_target(client, target):
    client.post(f"/targets/{target.id}/revisions/snapshot")

    r = client.get(f"/targets/{target.id}/parity")
    assert r.status_code == 200
    body = r.json()
    assert body["in_sync"] is True
    assert body["has_revision"] is True
    assert body["rev"] == 1
    assert body["only_in_db"] == []
    assert body["only_on_disk"] == []
    assert body["modified"] == []


def test_parity_names_every_kind_of_difference_by_exact_path(client, target):
    client.post(f"/targets/{target.id}/revisions/snapshot")
    app_dir = client.workspace / "apps" / "demo"
    (app_dir / "tests" / "checkout" / "new.spec.ts").write_text("// new\n")      # extra
    (app_dir / "tests" / "checkout" / "pay.spec.ts").unlink()                    # missing
    (app_dir / "tests" / "checkout" / "cart.spec.ts").write_text("// edited\n")  # modified

    body = client.get(f"/targets/{target.id}/parity").json()
    assert body["in_sync"] is False
    assert body["only_on_disk"] == ["tests/checkout/new.spec.ts"]
    assert body["only_in_db"] == ["tests/checkout/pay.spec.ts"]
    assert body["modified"] == ["tests/checkout/cart.spec.ts"]


def test_parity_for_a_target_with_no_revisions_is_distinguishable(client, target):
    """Not a false "in sync" and not a server error."""
    r = client.get(f"/targets/{target.id}/parity")
    assert r.status_code == 200
    body = r.json()
    assert body["has_revision"] is False
    assert body["in_sync"] is False
    assert body["rev"] is None


def test_parity_of_a_missing_target_is_404(client):
    assert client.get("/targets/999/parity").status_code == 404
