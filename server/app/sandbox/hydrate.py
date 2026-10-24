"""Build a run's worktree from the database, and delete it afterwards.

    hydrate    head revision + target config  ->  a per-run worktree
    run        the agent works in that worktree, and nowhere else
    ingest     at each completed step boundary: upload blobs, commit revision N+1
    teardown   delete the worktree

Three named parts, so P4 can replace them one at a time:

1. **Materialize** -- write every `file_index` row of a revision into a
   directory, streaming each blob through the existing `Storage.get_stream`. The
   blob key *is* the content hash, so every file is verified as it is written:
   a missing or mismatched blob fails the hydrate, and therefore the run, before
   the agent starts and before any tokens are burned. Delivery materializes the
   same way, which is what makes "we pushed the revision we recorded" provable.
2. **Render** -- overwrite the generated entries from the target row. They are
   regenerated on every hydrate and overwrite whatever the revision held, so the
   generated config has exactly one author.
3. **Install** -- dependencies from the revision's lockfile against a shared npm
   cache. One named function, because P4's prebaked image and warm cache replace
   it rather than being threaded through the pipeline.

Decisions that are not incidentals:

- **The worktree lives outside the run directory** (`config.worktree_dir`).
  Artifact collection sweeps the run dir recursively, so a worktree inside it
  would upload the whole source tree and `node_modules` as run artifacts.
- **It is a plain directory, not a git worktree.** Nothing in P3 reads a git
  history -- ingest hashes files, delivery squashes into one commit -- and git
  inside the worktree arrives with P4's bundles. A second history nobody reads
  is a second thing that can be wrong.
- **A failed hydrate leaves no tree at all.** A half-written worktree is worse
  than none: the agent would work in it and ingest would commit the result.
"""

from __future__ import annotations

import hashlib
import shutil
import stat
import subprocess
from dataclasses import dataclass
from pathlib import Path

from sqlalchemy.orm import Session

from .. import config, revisions
from ..delivery.render import write_infra
from ..models import Revision, Target
from ..orchestrator.runner import Emit
from ..storage import Storage
from ..target_config import TargetConfig, config_of

_CHUNK = 1 << 16


class HydrateError(Exception):
    """The worktree could not be built. The run fails, before any step runs."""


class NoHeadRevision(HydrateError):
    """The target has no revision to hydrate from.

    Every target gets revision 1 when it is created, so this is a broken target
    rather than a new one -- and there is no disk left to baseline from, which is
    why the P2 baseline-from-disk hook is gone.
    """


@dataclass(frozen=True)
class HydrateResult:
    """What hydrate built, for the run's log and for the tests."""

    root: Path
    rev: int
    files: int
    installed: bool


def materialize(
    session: Session, revision: Revision, store: Storage, dest: Path
) -> list[str]:
    """Write every file of `revision` into `dest`. Returns the paths written.

    Verification is not an extra step: the blob key is the content hash, so
    hashing the bytes as they stream past and comparing is the whole check. A
    store that hands back the wrong bytes is caught here rather than becoming a
    worktree the agent works in.

    Also what delivery uses, so what we push is provably the revision recorded.
    """
    written: list[str] = []
    for row in revisions.list_files(session, revision.id):
        expected = revisions.sha256_from_blob_key(row.blob_key)
        path = dest / row.path
        path.parent.mkdir(parents=True, exist_ok=True)
        digest = hashlib.sha256()
        try:
            chunks, _ct = store.get_stream(row.blob_key)
            with path.open("wb") as fh:
                for chunk in chunks:
                    digest.update(chunk)
                    fh.write(chunk)
        except HydrateError:
            raise
        except Exception as exc:
            raise HydrateError(
                f"revision {revision.rev}: could not read the blob for {row.path!r} "
                f"({row.blob_key}): {exc}"
            ) from exc
        if digest.hexdigest() != expected:
            raise HydrateError(
                f"revision {revision.rev}: {row.path!r} does not match its content "
                f"hash (blob {row.blob_key} holds something else)"
            )
        written.append(row.path)
    dest.mkdir(parents=True, exist_ok=True)
    return written


def render_generated(root: Path, cfg: TargetConfig) -> None:
    """Overwrite the generated entries from the target row.

    Run on every hydrate and again before every ingest scan. That pairing is
    what gives the generated config exactly one author: hydrate puts the row's
    version in the worktree, and ingest puts it back before deciding what the
    tree is, so an agent's edit to it is discarded rather than committed.
    """
    write_infra(root, cfg, only_generated=True)


def install_dependencies(
    root: Path, emit: Emit, *, runner_kind: str | None = None
) -> bool:
    """`npm ci` from the revision's lockfile, against a shared cache.

    **Skipped for the fake runner**: there is nothing to install for synthetic
    steps and the API image has no node. For the real runner a missing `npm` is
    a hard error -- the agent's step 4 runs `npx playwright test`, so a run that
    got that far without dependencies would fail later and more confusingly.

    P4 replaces this function with a prebaked image and a warm cache.
    """
    kind = runner_kind if runner_kind is not None else config.runner_kind()
    if kind == "fake":
        emit("=== hydrate: dependency install skipped (fake runner) ===")
        return False

    if shutil.which("npm") is None:
        raise HydrateError(
            "npm is not available, so the worktree's dependencies cannot be "
            "installed; the real runner needs it to run the generated suite"
        )
    if not (root / "package-lock.json").is_file():
        raise HydrateError(
            "the revision has no package-lock.json, so there is no lockfile to "
            "install from"
        )

    cache = config.npm_cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    emit("=== hydrate: installing dependencies (npm ci) ===")
    proc = subprocess.run(
        ["npm", "ci", "--cache", str(cache), "--no-audit", "--no-fund"],
        cwd=str(root),
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        raise HydrateError(
            f"npm ci failed in the worktree (rc={proc.returncode}): "
            f"{proc.stderr.strip()[-500:]}"
        )
    return True


def hydrate(
    session: Session,
    target: Target,
    store: Storage,
    dest: Path,
    *,
    emit: Emit,
    install: bool = True,
) -> HydrateResult:
    """Build `target`'s head revision into `dest`: materialize, render, install.

    Raises rather than returning a partial tree, and removes `dest` on the way
    out when it does. The run fails on that exception, which is the point: a run
    that cannot be given a tree must not burn tokens against a corrupt one.
    """
    head = revisions.head_revision(session, target.id)
    if head is None:
        raise NoHeadRevision(
            f"target {target.app!r} has no head revision to hydrate from"
        )

    cfg = config_of(target)
    try:
        files = materialize(session, head, store, dest)
        render_generated(dest, cfg)
        installed = install_dependencies(dest, emit) if install else False
    except Exception:
        teardown(dest)
        raise

    emit(
        f"=== hydrate: worktree built from revision {head.rev} "
        f"({len(files)} files) at {dest} ==="
    )
    return HydrateResult(root=dest, rev=head.rev, files=len(files), installed=installed)


def teardown(root: Path) -> None:
    """Delete the worktree.

    Runs at every terminal state and on pause, including states reached before
    hydrate ever ran, so a worktree that is not there is not an error. Mid-step
    work is lost, which is invariant 4 (a crash commits nothing) rather than a
    regression.

    `onexc` matters: `node_modules` arrives with read-only directories, and a
    teardown that gave up on the first of them would leave the largest
    directory in the worktree behind -- which is precisely the disk the phase
    promises to bound by live runs. The retry chmods the *parent*, because what
    refuses an unlink is the directory's write bit, not the file's.
    """

    def _force(func, path, _exc):
        path = Path(path)
        for target in (path.parent, path):
            try:
                target.chmod(target.stat().st_mode | stat.S_IRWXU)
            except OSError:
                pass
        try:
            func(path)
        except OSError:
            pass

    shutil.rmtree(root, onexc=_force)
