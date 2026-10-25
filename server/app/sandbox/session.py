"""The agent's session, carried between containers as a run artifact.

What a paused run must not lose is the **agent session**. `--resume <id>` works
today only because the CLI's session store happens to sit on the host that
started the run; the moment a run executes in a container destroyed on pause,
that store is gone and step 4 generates tests from an exploration it cannot
remember.

So the session directory is archived under a **reserved artifact name** at the
end of every run -- which includes every pause, because a paused run's container
exits -- and restored into the next container before the CLI is invoked.

    <run_key>/agent-session.tar.gz        kind "session", versioned per run

A run artifact rather than a new store: the artifacts table already keys blobs
by run, already streams them back through the API, and is already garbage
collected with the run. Its own reserved name, so the artifact sweep's
classification and an operator's eye both have one thing to recognise.

**Only where a sandbox put the session.** `CLAUDE_CONFIG_DIR` is set by
app/sandbox/env.py and by nothing else, so an unset one means there is no
per-run session store -- and a developer's own `~/.claude` is emphatically not
one to upload. Everything here is a no-op in that case.

**Nothing here may fail a run.** If the archive cannot be written, the work is
still committed; if it cannot be restored, the run continues **without session
continuity and says so in the log**. The tree is the carrier of the work and it
is intact; the exploration is context, and losing context loudly is better than
failing a run that can still finish.
"""

from __future__ import annotations

import hashlib
import logging
import os
import tarfile
import tempfile
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Artifact, Run
from ..orchestrator.runner import Emit
from ..storage import Storage
from ..tenancy import current_tenant_id

log = logging.getLogger(__name__)

# The reserved name. One per run, rewritten (as a new version) on each pause.
ARCHIVE_NAME = "agent-session.tar.gz"
ARCHIVE_KIND = "session"

_CHUNK = 1 << 16


def config_dir() -> Path | None:
    """The sandbox's CLI state directory, or None if this is not a sandbox."""
    raw = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    return Path(raw) if raw else None


def archive_key(run_key: str) -> str:
    return f"{run_key}/{ARCHIVE_NAME}"


def save(session: Session, run: Run, store: Storage, *, emit: Emit) -> bool:
    """Archive the agent's session as this run's reserved artifact.

    Best effort, and silent about the ordinary cases: a run on the thread path
    has no session directory, and a run that failed before the agent ever spoke
    has nothing in it.
    """
    source = config_dir()
    if source is None or not source.is_dir() or not any(source.iterdir()):
        return False

    key = archive_key(run.run_key)
    try:
        with tempfile.TemporaryDirectory(prefix="qa-session-") as tmp:
            # Built outside the run directory on purpose: anything in there is
            # swept up as an artifact at the next step boundary, and the session
            # archive is one artifact written deliberately rather than twice by
            # accident.
            path = Path(tmp) / ARCHIVE_NAME
            with tarfile.open(path, "w:gz") as tar:
                tar.add(source, arcname=".")
            digest = _sha256(path)
            store.put_file(key, path, "application/gzip")
        _index(session, run, key, digest)
    except Exception:
        emit("=== session: could not be saved; a resume will start without it ===")
        log.warning("archiving the session of run %s failed", run.id, exc_info=True)
        return False
    emit("=== session: saved for a resume ===")
    return True


def restore(session: Session, run: Run, store: Storage, *, emit: Emit) -> bool:
    """Put this run's archived session back, before the CLI is invoked.

    Returns whether the session is there. A false answer is the caller's cue to
    continue without continuity -- and to stop telling the CLI to `--resume` a
    session that no longer exists, which would be a failed step rather than a
    forgotten exploration.
    """
    dest = config_dir()
    if dest is None:
        return False
    row = _existing(session, run, archive_key(run.run_key))
    if row is None:
        return False

    try:
        with tempfile.TemporaryDirectory(prefix="qa-session-") as tmp:
            path = Path(tmp) / ARCHIVE_NAME
            chunks, _ct = store.get_stream(row.s3_key)
            with path.open("wb") as fh:
                for chunk in chunks:
                    fh.write(chunk)
            dest.mkdir(parents=True, exist_ok=True)
            with tarfile.open(path) as tar:
                # `data` refuses absolute paths, parent traversal, links and
                # device files. The archive is ours, but it is read back out of
                # a store, and an archive extracted as root is the last place
                # to trust a path.
                tar.extractall(dest, filter="data")
    except Exception as exc:
        emit(
            "=== session: restore failed, continuing without session continuity "
            f"({exc}) ==="
        )
        log.warning("restoring the session of run %s failed", run.id, exc_info=True)
        return False
    emit("=== session: restored; the agent remembers what it explored ===")
    return True


def _index(session: Session, run: Run, key: str, digest: str) -> None:
    """Record the archive in the artifacts table, versioning the reserved name.

    The same rule the artifact collector uses: one row per (run, key), its
    version bumped when the content changes. A paused run resumed three times
    has one session artifact at version three, not three artifacts.
    """
    row = _existing(session, run, key)
    if row is None:
        session.add(
            Artifact(
                tenant_id=current_tenant_id(),
                run_id=run.id,
                step=None,
                kind=ARCHIVE_KIND,
                s3_key=key,
                sha256=digest,
                version=1,
            )
        )
    elif row.sha256 != digest:
        row.version += 1
        row.sha256 = digest
    session.commit()


def _existing(session: Session, run: Run, key: str) -> Artifact | None:
    return session.scalars(
        select(Artifact).where(Artifact.run_id == run.id, Artifact.s3_key == key)
    ).one_or_none()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()
