"""Commit a tracked tree into content-addressed blobs + a revision, and read it back.

P2 built this and never read it; P3 moved truth into it. A target's head
revision plus its configuration row are what hydrate builds a worktree from,
what ingest commits to, and what delivery pushes. There is no second copy to
compare against -- the property parity used to check by comparison is checked by
construction instead, by materializing a revision and re-scanning the result
(app/sandbox/hydrate.py).

The ordering is the invariant (DESIGN.md §5, "blob before row"):

    1. walk the tracked tree, hashing each file
    2. if the tree hash equals the head revision's, commit nothing
    3. upload each blob the store does not already hold
    4. in one transaction, insert the revision row and all its file_index rows

A crash between 3 and 4 leaves unreferenced blobs, which is the harmless
direction and what §9's mark-and-sweep is for. A crash before 3 leaves nothing.
Either way the previous head is intact and a retry converges, because a tree's
hash does not depend on when it was taken.
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .delivery.render import tracked_tree
from .models import FileIndex, Revision, Target
from .storage import Storage
from .tenancy import current_tenant_id

_CHUNK = 1 << 16

# Blobs are stored without a meaningful content type on purpose: a blob key is a
# content hash with no extension, and the same bytes can be referenced from
# paths with different extensions. The content type belongs to the *reference*,
# so the read route derives it from the requested tracked path instead.
BLOB_CONTENT_TYPE = "application/octet-stream"


def blob_key(tenant_id: int, sha256: str) -> str:
    """`tenant/<tenant_id>/blobs/<sha256>` (DESIGN.md §9).

    Content addressing is scoped per tenant deliberately: cross-tenant dedup is
    worth nothing (different customers' tests do not collide) and would make
    blob existence a side channel.
    """
    return f"tenant/{tenant_id}/blobs/{sha256}"


def sha256_from_blob_key(key: str) -> str:
    """The content hash a blob key names.

    Content addressing means the key *is* the hash, so file_index does not carry
    a redundant sha column for parity to read.
    """
    return key.rsplit("/", 1)[-1]


def file_sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            h.update(chunk)
    return h.hexdigest()


def tree_hash(blobs: Mapping[str, str]) -> str:
    """Hash a {target-relative path: content sha256} mapping.

    The encoding is `<blob-sha256>  <path>\\n` (two spaces) per path, in
    ascending byte order of the path, concatenated and sha256'd. It deliberately
    resembles a stripped-down git tree: sorted, content-only, and independent of
    directory iteration order, file mtimes and file modes.

    **This is a durable on-disk format.** Every revision ever written depends on
    it, so it is pinned by a known-value test; changing it orphans them all.
    """
    manifest = "".join(
        f"{blobs[path]}  {path}\n" for path in sorted(blobs, key=str.encode)
    )
    return hashlib.sha256(manifest.encode()).hexdigest()


@dataclass(frozen=True)
class TrackedFile:
    path: str      # target-relative, the shape P3's hydrate builds
    on_disk: Path
    sha256: str
    size: int


@dataclass(frozen=True)
class TreeScan:
    """One walk of a target's tracked tree. No database, no blob store."""

    files: tuple[TrackedFile, ...]

    @property
    def blobs(self) -> dict[str, str]:
        return {f.path: f.sha256 for f in self.files}

    @property
    def tree_hash(self) -> str:
        return tree_hash(self.blobs)


def scan_tracked_tree(root: Path) -> TreeScan:
    """Hash every tracked file under `root`, in sorted path order.

    `root` is a worktree: the shape hydrate builds and ingest reads. There is no
    app argument, because a worktree holds exactly one target.
    """
    return TreeScan(
        files=tuple(
            TrackedFile(
                path=path,
                on_disk=on_disk,
                sha256=file_sha256(on_disk),
                size=on_disk.stat().st_size,
            )
            for path, on_disk in tracked_tree(root)
        )
    )


def head_revision(session: Session, target_id: int) -> Revision | None:
    """The target's current revision: the row with the greatest `rev`.

    Derived, never stored. Revisions are append-only, and a mutable
    `targets.head_revision_id` would be a second place recording "which is
    current" -- i.e. a second thing that can be wrong.
    """
    return session.scalars(
        select(Revision)
        .where(
            Revision.target_id == target_id,
            Revision.tenant_id == current_tenant_id(),
        )
        .order_by(Revision.rev.desc())
        .limit(1)
    ).one_or_none()


def commit_revision(
    session: Session,
    target: Target,
    store: Storage,
    root: Path,
    *,
    author: str,
    produced_by_run_id: int | None = None,
) -> Revision | None:
    """Commit a revision of the tracked tree under `root`, or None if unchanged.

    Returns None when the tree hash already matches the head: three of the five
    pipeline steps (read-story, plan, explore) routinely change no tracked file,
    and a revision per step would make `rev` a step counter rather than a count
    of real changes.

    Raises whatever the blob store raises. Who catches that is the caller's
    decision and it changed in P3: a failed ingest now fails the run.
    """
    tenant_id = current_tenant_id()
    scan = scan_tracked_tree(root)
    digest = scan.tree_hash

    head = head_revision(session, target.id)
    if head is not None and head.tree_hash == digest:
        return None

    # Blob before row. Identical bytes at two paths upload once, and a blob the
    # store already holds is not uploaded at all -- that is what `exists` buys.
    uploaded: set[str] = set()
    for file in scan.files:
        key = blob_key(tenant_id, file.sha256)
        if key in uploaded:
            continue
        uploaded.add(key)
        if not store.exists(key):
            store.put_file(key, file.on_disk, BLOB_CONTENT_TYPE)

    revision = Revision(
        tenant_id=tenant_id,
        target_id=target.id,
        rev=1 if head is None else head.rev + 1,
        # Null for a baseline. A concurrent committer of the same rev loses on
        # unique(target_id, rev), which is this phase's OCC point.
        parent_rev=None if head is None else head.rev,
        tree_hash=digest,
        produced_by_run_id=produced_by_run_id,
        author=author,
    )
    session.add(revision)
    session.flush()  # assign revision.id

    session.add_all(
        FileIndex(
            revision_id=revision.id,
            path=file.path,
            tenant_id=tenant_id,
            blob_key=blob_key(tenant_id, file.sha256),
            size=file.size,
        )
        for file in scan.files
    )
    session.commit()
    session.refresh(revision)
    return revision


def list_revisions_with_file_counts(
    session: Session, target_id: int
) -> list[tuple[Revision, int]]:
    """A target's history with each revision's file count, newest first.

    The count comes from one aggregate rather than from `revision.files`, which
    would lazy-load the whole file index of every revision in the list -- 41
    rows per revision on a real target, to display one number.
    """
    rows = session.execute(
        select(Revision, func.count(FileIndex.path))
        .outerjoin(FileIndex, FileIndex.revision_id == Revision.id)
        .where(
            Revision.target_id == target_id,
            Revision.tenant_id == current_tenant_id(),
        )
        .group_by(Revision.id)
        .order_by(Revision.rev.desc())
    ).all()
    return [(rev, count) for rev, count in rows]


def count_files(session: Session, revision_id: int) -> int:
    """How many files a revision holds. Tenant-filtered like every other read:
    the count of another tenant's revision is not ours to report."""
    return session.scalar(
        select(func.count(FileIndex.path)).where(
            FileIndex.revision_id == revision_id,
            FileIndex.tenant_id == current_tenant_id(),
        )
    ) or 0


def get_revision(session: Session, revision_id: int) -> Revision | None:
    """One revision, filtered by the request's tenant.

    The filter is what makes a blob read authorized by a row rather than by
    knowledge of a key (DESIGN.md §9). That the tenant is always 1 today is not
    a reason to leave it out -- it is the structural half of P5.
    """
    return session.scalars(
        select(Revision).where(
            Revision.id == revision_id,
            Revision.tenant_id == current_tenant_id(),
        )
    ).one_or_none()


def list_files(session: Session, revision_id: int) -> list[FileIndex]:
    return list(
        session.scalars(
            select(FileIndex)
            .where(
                FileIndex.revision_id == revision_id,
                FileIndex.tenant_id == current_tenant_id(),
            )
            .order_by(FileIndex.path)
        )
    )


def get_file(session: Session, revision_id: int, path: str) -> FileIndex | None:
    return session.scalars(
        select(FileIndex).where(
            FileIndex.revision_id == revision_id,
            FileIndex.path == path,
            FileIndex.tenant_id == current_tenant_id(),
        )
    ).one_or_none()
