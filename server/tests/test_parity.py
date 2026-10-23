"""The parity comparison, tested as the pure function it is.

No database and no filesystem here on purpose: the comparison takes two
mappings, so the hard part of "is the database in sync with the disk?" is
testable without standing either of them up. The I/O'd version is covered
through the route in test_api_revisions.py.
"""

from __future__ import annotations

from app.parity import compare_trees, no_revision

A = "a" * 64
B = "b" * 64
C = "c" * 64


def test_identical_trees_are_in_sync():
    diff = compare_trees({"x.ts": A, "y/z.ts": B}, {"x.ts": A, "y/z.ts": B})
    assert diff.in_sync
    assert diff.only_in_db == ()
    assert diff.only_on_disk == ()
    assert diff.modified == ()


def test_two_empty_trees_are_in_sync():
    assert compare_trees({}, {}).in_sync


def test_a_path_only_on_disk_is_reported_as_on_disk_only():
    diff = compare_trees({"x.ts": A}, {"x.ts": A, "new.ts": B})
    assert diff.only_on_disk == ("new.ts",)
    assert diff.only_in_db == ()
    assert diff.modified == ()
    assert not diff.in_sync


def test_a_path_only_in_the_database_is_reported_as_database_only():
    diff = compare_trees({"x.ts": A, "gone.ts": B}, {"x.ts": A})
    assert diff.only_in_db == ("gone.ts",)
    assert diff.only_on_disk == ()
    assert diff.modified == ()
    assert not diff.in_sync


def test_a_path_whose_content_differs_is_reported_as_modified_only():
    """And not also as missing or extra -- a mismatch should read as one fault."""
    diff = compare_trees({"x.ts": A}, {"x.ts": B})
    assert diff.modified == ("x.ts",)
    assert diff.only_in_db == ()
    assert diff.only_on_disk == ()


def test_all_three_kinds_are_reported_together():
    diff = compare_trees(
        {"same.ts": A, "gone.ts": B, "edited.ts": C},
        {"same.ts": A, "edited.ts": B, "new.ts": C},
    )
    assert diff.only_in_db == ("gone.ts",)
    assert diff.only_on_disk == ("new.ts",)
    assert diff.modified == ("edited.ts",)
    assert not diff.in_sync


def test_every_bucket_is_sorted_by_path():
    diff = compare_trees(
        {"b.ts": A, "a.ts": A, "z/y.ts": B, "z/x.ts": B},
        {},
    )
    assert diff.only_in_db == ("a.ts", "b.ts", "z/x.ts", "z/y.ts")


def test_a_target_with_no_revision_is_neither_in_sync_nor_an_error():
    parity = no_revision()
    assert parity.has_revision is False
    assert parity.in_sync is False
    assert parity.rev is None
    assert parity.diff.in_sync, "the diff itself is empty; the *parity* is not green"
