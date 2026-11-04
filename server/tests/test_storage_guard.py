"""The guard on the blob-storage seam.

The S3 client is only ever constructed by `storage.from_env()`, and in the dev
stack that reads as "SeaweedFS on localhost", which is up. So a test that forgot
to override the `get_storage` dependency went green locally and failed in CI,
where there is Postgres and no object store -- the one failure mode a local run
cannot see. conftest blocks the seam so the omission fails here instead.
"""

from __future__ import annotations

import pytest

from app import storage


def test_the_suite_cannot_construct_a_real_s3_client():
    """The autouse fixture is installed, and it names the fix."""
    with pytest.raises(AssertionError, match="FakeStorage"):
        storage.from_env()


def test_the_fake_satisfies_the_storage_protocol(tmp_path):
    """What the guard points at has to be a usable substitute: every method the
    protocol declares, or the guard is just a wall."""
    from tests.storage_helpers import FakeStorage

    store = FakeStorage()
    blob = tmp_path / "trace.zip"
    blob.write_bytes(b"zip")

    store.ensure_bucket()
    assert store.exists("trace.zip") is False
    store.put_file("trace.zip", blob)
    assert store.exists("trace.zip") is True

    chunks, content_type = store.get_stream("trace.zip")
    assert b"".join(chunks) == b"zip"
    assert content_type == "application/zip"

    # Derived from the protocol, not listed here, so a method added to Storage
    # (the way P2 added `exists`) fails until the fake grows it too.
    declared = {name for name in vars(storage.Storage) if not name.startswith("_")}
    assert declared and declared <= set(dir(store)), declared - set(dir(store))


# --- delete and list-by-prefix (P5-08 / #40) -----------------------------
#
# A prefactor: "make the change easy, then make the easy change". Tenant purge
# (#47) has to remove objects nobody recorded individually, which means
# enumerating a prefix and deleting what comes back. Nothing in production
# calls either operation yet, so these tests are the only thing holding the
# semantics -- which is why they state them rather than just exercising them.

def test_the_fake_deletes_a_key_and_forgets_it(tmp_path):
    from tests.storage_helpers import FakeStorage

    store = FakeStorage()
    blob = tmp_path / "trace.zip"
    blob.write_bytes(b"zip")
    store.put_file("tenant/1/blobs/abc", blob)

    store.delete("tenant/1/blobs/abc")

    assert store.exists("tenant/1/blobs/abc") is False


def test_deleting_a_key_that_is_not_there_is_not_an_error():
    """Purge must be re-runnable after a partial failure: a delete that raced
    another delete, or a run whose blob was already collected, cannot be the
    thing that stops the rest of a tenant being removed."""
    from tests.storage_helpers import FakeStorage

    FakeStorage().delete("tenant/9/blobs/never-existed")  # no raise


def test_the_fake_lists_only_the_keys_under_the_prefix(tmp_path):
    from tests.storage_helpers import FakeStorage

    store = FakeStorage()
    blob = tmp_path / "b"
    blob.write_bytes(b"x")
    for key in (
        "tenant/1/blobs/aa",
        "tenant/1/runs/r1/trace.zip",
        "tenant/11/blobs/bb",  # a prefix of a prefix: not tenant 1's
        "tenant/2/blobs/cc",
    ):
        store.put_file(key, blob)

    assert set(store.list_keys("tenant/1/")) == {
        "tenant/1/blobs/aa",
        "tenant/1/runs/r1/trace.zip",
    }


def test_listing_a_prefix_with_nothing_under_it_is_empty_rather_than_an_error():
    from tests.storage_helpers import FakeStorage

    assert list(FakeStorage().list_keys("tenant/404/")) == []


# --- the S3 implementation's paging --------------------------------------

class _StubPaginator:
    """`list_objects_v2`'s paginator, as botocore presents it."""

    def __init__(self, pages, calls):
        self._pages = pages
        self._calls = calls

    def paginate(self, **kwargs):
        self._calls.append(kwargs)
        return iter(self._pages)


class _StubClient:
    def __init__(self, pages):
        self.pages = pages
        self.paginate_calls: list[dict] = []
        self.deleted: list[dict] = []

    def get_paginator(self, name):
        assert name == "list_objects_v2", name
        return _StubPaginator(self.pages, self.paginate_calls)

    def delete_object(self, **kwargs):
        self.deleted.append(kwargs)


def _s3_with(client) -> storage.S3Storage:
    """An `S3Storage` whose boto3 client is a stub.

    Constructed for real -- `boto3.client` opens no connection -- and then its
    client replaced, because what is under test is this class's own paging
    loop and there is no other way to drive it without an object store. The
    stub is shaped like botocore's paginator rather than like a convenience,
    so the loop is exercised against the real contract.
    """
    store = storage.S3Storage(
        endpoint="http://stub.invalid",
        access_key="k",
        secret_key="s",
        bucket="qa-artifacts",
    )
    store._client = client
    return store


def test_listing_pages_through_the_whole_result_set():
    """The failure this guards against is silent. `list_objects_v2` returns at
    most 1000 keys, so a purge built on a single call would remove a tenant's
    first thousand objects and report success -- and a tenant with a long run
    history is exactly the one that has more."""
    client = _StubClient(
        [
            {"Contents": [{"Key": f"tenant/1/blobs/{i}"} for i in range(1000)]},
            {"Contents": [{"Key": f"tenant/1/blobs/{i}"} for i in range(1000, 1500)]},
        ]
    )

    keys = list(_s3_with(client).list_keys("tenant/1/"))

    assert len(keys) == 1500
    assert keys[0] == "tenant/1/blobs/0"
    assert keys[-1] == "tenant/1/blobs/1499"
    assert client.paginate_calls == [{"Bucket": "qa-artifacts", "Prefix": "tenant/1/"}]


def test_listing_a_prefix_s3_has_nothing_under_is_empty():
    """A page with no `Contents` at all, which is what S3 returns for a prefix
    that matches nothing -- not an error, and not a missing key."""
    assert list(_s3_with(_StubClient([{"KeyCount": 0}])).list_keys("tenant/404/")) == []


def test_deleting_through_s3_names_the_bucket_and_the_key():
    store = _s3_with(client := _StubClient([]))

    store.delete("tenant/1/blobs/aa")

    assert client.deleted == [{"Bucket": "qa-artifacts", "Key": "tenant/1/blobs/aa"}]
