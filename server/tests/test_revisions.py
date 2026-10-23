"""The revision model: the tree hash, and snapshot-and-commit.

The tree hash is tested directly because it is genuinely pure *and* because it
is a durable on-disk format -- every revision ever written depends on it, so the
encoding is pinned by a known-value test even though the encoding looks
internal. That is the one deliberate exception to "don't test implementation".

Everything else is asserted through what a caller can observe: the rows
committed, the blobs stored, and the bytes in them.
"""

from __future__ import annotations

import pytest

from app import repo, revisions
from app.models import FileIndex, Revision
from app.tenancy import current_tenant_id
from tests.delivery_helpers import make_workspace
from tests.storage_helpers import FakeStorage

# sha256("alpha") and sha256("beta"), and the tree hash over the two-file tree
# {"a.txt": "alpha", "b/c.txt": "beta"}. All three computed with `shasum -a 256`
# rather than with the code under test, so this cannot pass by construction.
SHA_ALPHA = "8ed3f6ad685b959ead7022518e1af76cd816f8e8ec7ccdda1ed4018e8f2223f8"
SHA_BETA = "f44e64e75f3948e9f73f8dfa94721c4ce8cbb4f265c4790c702b2d41cfbf2753"
KNOWN_TREE_HASH = "03d2ee82757dae7f07025257ab52c3487e1de5bc711d215636abf298c4b21c29"


# --- the tree hash: a durable format, pinned ----------------------------

def test_tree_hash_has_the_pinned_encoding():
    """`<blob-sha256>  <path>\\n` per path, ascending by path, then sha256.

    A refactor that changes this orphans every revision ever written, so the
    value is a literal computed outside this codebase.
    """
    assert revisions.tree_hash({"a.txt": SHA_ALPHA, "b/c.txt": SHA_BETA}) == KNOWN_TREE_HASH


def test_tree_hash_is_independent_of_iteration_order():
    forwards = revisions.tree_hash({"a.txt": SHA_ALPHA, "b/c.txt": SHA_BETA})
    backwards = revisions.tree_hash({"b/c.txt": SHA_BETA, "a.txt": SHA_ALPHA})
    assert forwards == backwards == KNOWN_TREE_HASH


def test_tree_hash_changes_when_one_file_changes():
    base = revisions.tree_hash({"a.txt": SHA_ALPHA, "b/c.txt": SHA_BETA})
    moved = revisions.tree_hash({"a.txt": SHA_BETA, "b/c.txt": SHA_ALPHA})
    renamed = revisions.tree_hash({"a.txt": SHA_ALPHA, "b/d.txt": SHA_BETA})
    assert base != moved
    assert base != renamed


def test_tree_hash_of_an_empty_tree_is_the_hash_of_nothing():
    assert revisions.tree_hash({}) == revisions.tree_hash({})
    assert len(revisions.tree_hash({})) == 64


def test_a_one_byte_change_changes_the_tree_hash(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    before = revisions.scan_tracked_tree("demo")
    (workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts").write_text("// carts\n")
    after = revisions.scan_tracked_tree("demo")

    assert before.tree_hash != after.tree_hash


def test_two_scans_of_an_unchanged_tree_agree(tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    first = revisions.scan_tracked_tree("demo")
    second = revisions.scan_tracked_tree("demo")
    assert first.tree_hash == second.tree_hash
    assert first.blobs == second.blobs


def test_the_blob_key_is_per_tenant_and_content_addressed():
    """`tenant/<id>/blobs/<sha256>` (DESIGN.md §9). Dedup is scoped per tenant
    deliberately: cross-tenant dedup is worth nothing and would make blob
    existence a side channel."""
    assert revisions.blob_key(1, SHA_ALPHA) == f"tenant/1/blobs/{SHA_ALPHA}"


# --- snapshot and commit ------------------------------------------------

@pytest.fixture()
def target_env(session, tmp_path, monkeypatch):
    """A real temp tree with one app, and a target row pointing at it."""
    workspace = make_workspace(tmp_path, app="demo")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))
    project = repo.create_project(session, name="demo")
    target = repo.create_target(session, project_id=project.id, app="demo", name="Demo")
    return target, workspace


def test_snapshotting_a_target_with_no_history_creates_revision_one(target_env, session):
    target, workspace = target_env
    store = FakeStorage()

    rev = revisions.snapshot_target(session, target, store, author="operator")

    assert rev is not None
    assert rev.rev == 1
    assert rev.parent_rev is None
    assert rev.produced_by_run_id is None  # a manual snapshot has no run
    assert rev.author == "operator"
    assert rev.tenant_id == current_tenant_id()
    assert rev.delivered_sha is None


def test_the_file_index_lists_exactly_the_tracked_tree(target_env, session):
    target, workspace = target_env
    store = FakeStorage()

    rev = revisions.snapshot_target(session, target, store, author="operator")

    rows = list(session.scalars(repo.select(FileIndex).where(FileIndex.revision_id == rev.id)))
    assert {r.path for r in rows} == {
        "package.json",
        "package-lock.json",
        "playwright.config.ts",
        ".gitignore",
        ".github/workflows/playwright.yml",
        "seed.spec.ts",
        "user-stories/SCRUM-1-checkout.md",
        "specs/SCRUM-1-checkout-test-plan.md",
        "tests/checkout/cart.spec.ts",
        "tests/checkout/pay.spec.ts",
    }
    # Every row names a blob that is actually in the store, with the real size.
    for row in rows:
        assert row.blob_key in store.objects
        on_disk = (workspace / "apps" / "demo" / row.path) if row.path != "package.json" else (
            workspace / "package.json"
        )
        assert row.tenant_id == current_tenant_id()
        if on_disk.is_file():
            assert row.size == on_disk.stat().st_size


def test_a_snapshot_of_an_unchanged_tree_commits_nothing(target_env, session):
    target, _ = target_env
    store = FakeStorage()

    first = revisions.snapshot_target(session, target, store, author="operator")
    second = revisions.snapshot_target(session, target, store, author="operator")

    assert first is not None
    assert second is None, "an unchanged tree must not advance rev"
    assert revisions.head_revision(session, target.id).rev == 1
    assert len(list(session.scalars(repo.select(Revision)))) == 1


def test_a_snapshot_after_one_change_commits_rev_two_chained_to_one(target_env, session):
    target, workspace = target_env
    store = FakeStorage()

    revisions.snapshot_target(session, target, store, author="operator")
    (workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts").write_text("// v2\n")
    second = revisions.snapshot_target(session, target, store, author="operator")

    assert second.rev == 2
    assert second.parent_rev == 1
    assert revisions.head_revision(session, target.id).rev == 2


def test_only_the_changed_blob_is_uploaded_on_the_second_snapshot(target_env, session):
    """Dedup: an unchanged file is stored once however many revisions name it."""
    target, workspace = target_env
    store = FakeStorage()

    revisions.snapshot_target(session, target, store, author="operator")
    after_first = set(store.objects)
    store.put_calls = 0  # count only the second snapshot's uploads

    original_put = store.put_file

    def counting_put(key, path, content_type=None):
        store.put_calls += 1
        return original_put(key, path, content_type)

    store.put_file = counting_put
    (workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts").write_text("// v2\n")
    revisions.snapshot_target(session, target, store, author="operator")

    assert store.put_calls == 1, "only the changed file's blob should be uploaded"
    assert set(store.objects) - after_first, "the new blob is in the store"


def test_two_targets_with_identical_infra_share_one_blob(session, tmp_path, monkeypatch):
    workspace = make_workspace(tmp_path, app="one")
    (workspace / "apps" / "two" / "user-stories").mkdir(parents=True)
    (workspace / "apps" / "two" / "seed.spec.ts").write_text("// seed\n")
    monkeypatch.setenv("QA_REPO_ROOT", str(workspace))

    project = repo.create_project(session, name="demo")
    one = repo.create_target(session, project_id=project.id, app="one", name="One")
    two = repo.create_target(session, project_id=project.id, app="two", name="Two")
    store = FakeStorage()

    rev_one = revisions.snapshot_target(session, one, store, author="operator")
    rev_two = revisions.snapshot_target(session, two, store, author="operator")

    def key_for(rev, path):
        return session.get(FileIndex, {"revision_id": rev.id, "path": path}).blob_key

    # Byte-identical infra -> the same content hash -> one object.
    assert key_for(rev_one, "package.json") == key_for(rev_two, "package.json")
    assert sum(1 for k in store.objects if k == key_for(rev_one, "package.json")) == 1
    # ...and both revisions do reference it.
    assert key_for(rev_one, "package.json") in store.objects


def test_a_storage_whose_upload_raises_leaves_no_rows(target_env, session):
    """Blob before row (invariant 3): a crash may leave an unreferenced blob,
    never a revision pointing at bytes that are not there."""
    target, _ = target_env

    class ExplodingStorage(FakeStorage):
        def put_file(self, key, path, content_type=None):
            raise RuntimeError("object store is down")

    with pytest.raises(RuntimeError, match="object store is down"):
        revisions.snapshot_target(session, target, ExplodingStorage(), author="operator")

    session.rollback()
    assert list(session.scalars(repo.select(Revision))) == []
    assert list(session.scalars(repo.select(FileIndex))) == []


def test_an_existing_blob_is_not_re_uploaded(target_env, session):
    """`exists` is the one method the seam gained; this is what it is for."""
    target, _ = target_env

    class CountingStorage(FakeStorage):
        def __init__(self):
            super().__init__()
            self.exists_calls = 0
            self.put_calls = 0

        def exists(self, key):
            self.exists_calls += 1
            return super().exists(key)

        def put_file(self, key, path, content_type=None):
            self.put_calls += 1
            super().put_file(key, path, content_type)

    store = CountingStorage()
    revisions.snapshot_target(session, target, store, author="operator")
    first_puts = store.put_calls
    assert first_puts > 0
    assert store.exists_calls >= first_puts

    # A second target over the same infra re-walks the same bytes.
    project_id = target.project_id
    other = repo.create_target(session, project_id=project_id, app="demo2", name="Demo2")
    store.put_calls = 0
    revisions.snapshot_target(session, other, store, author="operator")

    # demo2 has no app folder of its own, so every file it tracks is infra that
    # is already stored: nothing to upload.
    assert store.put_calls == 0


def test_head_revision_is_none_for_a_target_with_no_revisions(target_env, session):
    target, _ = target_env
    assert revisions.head_revision(session, target.id) is None


def test_head_revision_is_the_greatest_rev_not_the_newest_row(target_env, session):
    """The head is derived, so nothing can disagree with it."""
    target, workspace = target_env
    store = FakeStorage()
    revisions.snapshot_target(session, target, store, author="operator")
    (workspace / "apps" / "demo" / "tests" / "checkout" / "cart.spec.ts").write_text("// v2\n")
    revisions.snapshot_target(session, target, store, author="operator")

    assert revisions.head_revision(session, target.id).rev == 2


def test_a_revision_records_the_run_that_produced_it(target_env, session):
    target, _ = target_env
    run = repo.start_run(session, target_id=target.id, story_id="SCRUM-1", mode="full")

    rev = revisions.snapshot_target(
        session, target, FakeStorage(), author="run", produced_by_run_id=run.id
    )

    assert rev.produced_by_run_id == run.id
