"""Does the database agree with the authoritative filesystem?

P2 dual-writes the revision model while `apps/` stays the source of truth, and
dual-write is only worth a whole phase if someone checks the two copies agree.
Without this, a revision write that silently stopped working would look exactly
like one that was working, and the phase would prove nothing. With it, "a run
finished and parity is green" is the evidence that P3's read-flip is safe.

The comparison is **pure** -- two mappings of path to content hash in, a diff
out. No database and no filesystem, so it tests without either.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass


@dataclass(frozen=True)
class TreeDiff:
    """Where the database's idea of a tree and the disk's differ.

    A path is reported in exactly one bucket: present on one side only, or
    present on both with different content. "Modified" is therefore never also
    "missing" or "extra", which is what makes a mismatch a bug report rather
    than a puzzle.
    """

    only_in_db: tuple[str, ...]
    only_on_disk: tuple[str, ...]
    modified: tuple[str, ...]

    @property
    def in_sync(self) -> bool:
        return not (self.only_in_db or self.only_on_disk or self.modified)


def compare_trees(in_db: Mapping[str, str], on_disk: Mapping[str, str]) -> TreeDiff:
    """Diff {path: content sha256} against {path: content sha256}.

    Both sides are content hashes, so equality is a string comparison rather
    than a byte-for-byte read -- which is the point of hashing the tree in the
    first place.
    """
    db_paths, disk_paths = set(in_db), set(on_disk)
    return TreeDiff(
        only_in_db=tuple(sorted(db_paths - disk_paths)),
        only_on_disk=tuple(sorted(disk_paths - db_paths)),
        modified=tuple(
            sorted(path for path in db_paths & disk_paths if in_db[path] != on_disk[path])
        ),
    )


@dataclass(frozen=True)
class Parity:
    """A target's parity report.

    `has_revision` is false for a target that has never been snapshotted. That
    is reported as its own state rather than as "in sync" (which would be a lie)
    or as an error (it is a normal state for a new target) -- the operator's next
    move is to take a snapshot.
    """

    has_revision: bool
    rev: int | None
    tree_hash: str | None
    diff: TreeDiff

    @property
    def in_sync(self) -> bool:
        return self.has_revision and self.diff.in_sync


EMPTY_DIFF = TreeDiff(only_in_db=(), only_on_disk=(), modified=())


def no_revision() -> Parity:
    return Parity(has_revision=False, rev=None, tree_hash=None, diff=EMPTY_DIFF)
