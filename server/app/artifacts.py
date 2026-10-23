"""Collect a run's on-disk outputs into blob storage + the artifacts index.

After each step the driver asks the collector to sweep the run dir: every file
not already stored for this run is uploaded (key = run_key/relpath) and indexed
with a kind (screenshot/video/trace/report/log/other) and a version. Version is
per (run, key): re-storing the same path in a later attempt bumps it, so history
is kept without a bespoke version graph.

Playwright *code* is NOT collected here — it is delivered to the target repo by
app/delivery. This indexes evidence/reports/logs only.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from .domain.steps import Step
from .models import Artifact, Run
from .storage import Storage, content_type_for

# Files that are never useful as artifacts.
_SKIP = {".DS_Store"}


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def classify(rel_path: str) -> str:
    p = rel_path.lower()
    if "playwright-report" in p or p.endswith(".html"):
        return "report"
    if p.endswith(".png") or p.endswith(".jpg") or p.endswith(".jpeg"):
        return "screenshot"
    if p.endswith(".webm") or p.endswith(".mp4"):
        return "video"
    if p.endswith(".zip"):
        return "trace"
    if p.endswith((".log", ".jsonl", ".txt", ".md")):
        return "log"
    return "other"


class ArtifactCollector:
    def __init__(self, storage: Storage) -> None:
        self.storage = storage

    def collect(self, session: Session, run: Run, run_dir: Path, step: Step) -> list[Artifact]:
        if not run_dir.exists():
            return []

        existing = {
            a.s3_key: a
            for a in session.scalars(select(Artifact).where(Artifact.run_id == run.id))
        }
        stored: list[Artifact] = []
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.name in _SKIP:
                continue
            rel = path.relative_to(run_dir).as_posix()
            key = f"{run.run_key}/{rel}"
            digest = _sha256(path)
            prior = existing.get(key)

            if prior is not None and prior.sha256 == digest:
                continue  # unchanged since last sweep: don't re-upload or bump

            self.storage.put_file(key, path, content_type_for(key))
            if prior is not None:  # content changed (e.g. a retried step): new version
                prior.version += 1
                prior.sha256 = digest
                prior.step = step.value
                stored.append(prior)
            else:
                row = Artifact(
                    run_id=run.id, step=step.value, kind=classify(rel),
                    s3_key=key, sha256=digest, version=1,
                )
                session.add(row)
                stored.append(row)

        session.commit()
        for row in stored:
            session.refresh(row)
        return stored


class NullCollector:
    """Default no-op (driver tests and runs without storage configured)."""

    def collect(self, session: Session, run: Run, run_dir: Path, step: Step) -> list[Artifact]:
        return []
