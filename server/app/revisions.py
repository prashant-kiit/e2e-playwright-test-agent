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
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .control.model import HeadRevision, RevisionFile
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
    scan = scan_tracked_tree(root)
    upload_blobs(store, scan, current_tenant_id())
    return record_revision(
        session,
        target,
        [(f.path, f.sha256, f.size) for f in scan.files],
        author=author,
        produced_by_run_id=produced_by_run_id,
    )


def upload_blobs(store: Storage, scan: TreeScan, tenant_id: int) -> None:
    """Put every blob of `scan` in the store, skipping the ones already there.

    Split out of `commit_revision` by P5-05, which is the point at which the two
    halves stopped happening in the same process: a sandbox uploads its blobs
    through the internal API and then asks the control plane to record the row
    (app/control/service.py). Keeping this a named function is what makes those
    two paths the same upload rather than two that agree today.

    `tenant_id` is a parameter rather than `current_tenant_id()` precisely
    because of that split: the control plane's callers are inside a tenant scope
    and a sandbox is not -- it has no resolver, no session and no ambient tenant,
    only the one its token names. Taking it explicitly is what makes the key a
    sandbox builds and the key the control plane authorizes the same key.

    Blob before row, always. Identical bytes at two paths upload once, and a
    blob the store already holds is not uploaded at all -- that is what `exists`
    buys.
    """
    uploaded: set[str] = set()
    for file in scan.files:
        key = blob_key(tenant_id, file.sha256)
        if key in uploaded:
            continue
        uploaded.add(key)
        if not store.exists(key):
            store.put_file(key, file.on_disk, BLOB_CONTENT_TYPE)


def record_revision(
    session: Session,
    target: Target,
    manifest: Sequence[tuple[str, str, int]],
    *,
    author: str,
    produced_by_run_id: int | None = None,
) -> Revision | None:
    """Record revision N+1 from a manifest of (path, sha256, size). No store.

    The database half of `commit_revision`, and the half the internal control
    plane performs on a sandbox's behalf: the blobs are already up by the time
    this runs, so all that is left is deriving the tree hash, comparing it to
    the head, and writing the rows.

    **The tree hash is derived here rather than passed in.** That is what makes
    it a fact about the file list rather than a claim about it -- the property
    delivery's "we pushed the revision we recorded" rests on -- and it is why
    there is no `tree_hash` parameter for a caller to get wrong.

    Returns None when the tree is unchanged, for the reason `commit_revision`
    states.
    """
    tenant_id = current_tenant_id()
    digest = tree_hash({path: sha for path, sha, _size in manifest})

    head = head_revision(session, target.id)
    if head is not None and head.tree_hash == digest:
        return None

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
            path=path,
            tenant_id=tenant_id,
            blob_key=blob_key(tenant_id, sha),
            size=size,
        )
        for path, sha, size in manifest
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


def blob_is_referenced_by_target(
    session: Session, target_id: int, blob_key: str
) -> bool:
    """Whether any revision of `target_id` references `blob_key`.

    The row that authorizes a blob read (#30: "every blob read authorized
    through a Postgres row belonging to the requesting tenant -- no
    serve-by-key-alone"). A blob key is a content hash, so it is guessable and
    shareable; the tenant prefix alone would let one target's run read another
    target's tree, which is a smaller leak than a cross-tenant one and still not
    one the token is supposed to permit.

    Tenant-filtered by the read guard like every other ORM select, so this
    answers within the acting tenant and a key belonging to another tenant's
    target is simply not found.
    """
    found = session.scalar(
        select(FileIndex.revision_id)
        .join(Revision, Revision.id == FileIndex.revision_id)
        .where(Revision.target_id == target_id, FileIndex.blob_key == blob_key)
        .limit(1)
    )
    return found is not None


def revision_view(session: Session, revision: Revision) -> HeadRevision:
    """One revision as the value `hydrate.materialize` takes.

    P5-05 gave `materialize` a single signature for two worlds. A run in a
    sandbox is handed a `HeadRevision` over the internal API because it has no
    session and no row; the control plane's own callers -- authoring's temporary
    tree and delivery's materialized head -- have both, and this is how they
    reach the same function rather than a second copy of it that happens to
    agree. "We pushed the revision we recorded" is provable precisely because
    delivery and hydrate materialize the same way.
    """
    return HeadRevision(
        rev=revision.rev,
        tree_hash=revision.tree_hash,
        files=tuple(
            RevisionFile(path=row.path, blob_key=row.blob_key, size=row.size)
            for row in list_files(session, revision.id)
        ),
    )


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
