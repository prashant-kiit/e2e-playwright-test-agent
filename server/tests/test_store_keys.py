"""The layout of the object store (P5-10 / #42).

Pure string rules, tested as such: these decide what story 32's purge will
enumerate, and a purge is the one operation in this system with no undo.

The assertion that matters most is the separator one. `tenant/1` is a prefix of
`tenant/11`, S3's `Prefix` is a byte comparison rather than a path walk, and a
purge of the first spelling would take the second customer's storage with it.
"""

from __future__ import annotations

import pytest

from app.domain import store_keys as keys

# --- one prefix per tenant -----------------------------------------------

def test_a_tenants_prefix_ends_with_a_separator():
    """The whole reason this is a function and not an f-string at each site."""
    assert keys.tenant_prefix(1) == "tenant/1/"


def test_one_tenants_prefix_does_not_match_another_whose_id_starts_the_same():
    """What the separator buys, stated as the failure it prevents."""
    assert not keys.blob_key(11, "abc").startswith(keys.tenant_prefix(1))
    assert not keys.artifact_key(11, "run-1", "a.txt").startswith(
        keys.tenant_prefix(1)
    )


@pytest.mark.parametrize(
    "key",
    (
        "tenant/7/blobs/" + "a" * 64,
        "tenant/7/runs/20261104-120000-demo-abc123/trace.zip",
        "tenant/7/runs/20261104-120000-demo-abc123/nested/dir/log.txt",
    ),
)
def test_everything_a_tenant_owns_is_under_its_one_prefix(key):
    """Story 32's requirement, as a property of the key space."""
    assert key.startswith(keys.tenant_prefix(7))


def test_blobs_and_artifacts_are_told_apart_by_the_segment_after_the_tenant():
    """The discriminator the shared prefix forced. It used to be "does this
    start with the run key?", which only worked while the two shapes had
    nothing in common."""
    blob = keys.blob_key(7, "a" * 64)
    artifact = keys.artifact_key(7, "run-1", "trace.zip")

    assert keys.is_blob_key(blob) is True
    assert keys.is_blob_key(artifact) is False
    assert keys.artifact_run_key(blob) is None
    assert keys.artifact_run_key(artifact) == "run-1"


def test_a_blob_key_with_a_path_in_it_is_not_a_blob_key():
    """Blob keys are exactly one segment deep -- a content hash. Anything
    deeper under `blobs/` is not something ingest wrote, and treating it as a
    blob would apply the weaker of the two authorization rules to it."""
    assert keys.is_blob_key("tenant/7/blobs/aa/bb") is False


# --- the legacy shape still reads ----------------------------------------

def test_the_legacy_artifact_shape_is_still_recognised_as_that_runs():
    """Expand then contract: existing objects keep resolving until the rekey
    command has moved them, so authorization has to know the old shape."""
    legacy = keys.legacy_artifact_key("20261104-120000-demo-abc123", "trace.zip")

    assert legacy == "20261104-120000-demo-abc123/trace.zip"
    assert keys.artifact_run_key(legacy) == "20261104-120000-demo-abc123"


def test_a_bare_run_key_is_that_runs_own_prefix():
    """The sweep never writes it, but `authorize_artifact_key` has always
    accepted a run's prefix itself, and dropping that would be a behaviour
    change smuggled into a re-keying ticket."""
    assert keys.artifact_run_key("20261104-120000-demo-abc123") == (
        "20261104-120000-demo-abc123"
    )


def test_the_new_shape_wins_when_a_key_could_be_read_either_way():
    """A new-shape key's first segment is `tenant`, which the legacy pattern
    would happily call a run key. The order of the two matches is what stops
    every artifact in the system belonging to a run called "tenant"."""
    assert keys.artifact_run_key("tenant/7/runs/run-1/trace.zip") == "run-1"
