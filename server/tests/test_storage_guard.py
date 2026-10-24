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
