"""Collect a run's on-disk outputs into blob storage + the artifacts index.

After each step the driver asks the collector to sweep the run dir: every file
not already stored for this run is uploaded (key =
tenant/<id>/runs/<run_key>/<relpath>, see app/domain/store_keys.py) and indexed
with a kind (screenshot/video/trace/report/log/other) and a version. Version is
per (run, key): re-storing the same path in a later attempt bumps it, so history
is kept without a bespoke version graph.

Playwright *code* is NOT collected here -- it is delivered to the target repo by
app/delivery. This indexes evidence/reports/logs only.

**P5-05 split the sweep from the index.** The collector used to take a session
and write `Artifact` rows itself; a run in a sandbox has no database, so it
uploads through the run's gateway and asks the control plane to record each row
(`index_artifact`). The versioning rule moved with the row -- it is in
app/control/service.py now, in one place, shared with the session archive that
follows the same rule for its own reserved name.

What stayed here is what belongs to the sweep: which files are worth uploading,
what to call them, how to classify them, and the dedup that stops an unchanged
file being re-uploaded at every one of the five step boundaries.
"""

from __future__ import annotations

import hashlib
from pathlib import Path

from ..control.gateway import RunGateway
from ..domain import store_keys
from ..domain.steps import Step
from ..storage import Storage, content_type_for

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
    """Sweep a run's directory into the store and the index, through a gateway."""

    def __init__(self, storage: Storage, control: RunGateway) -> None:
        self.storage = storage
        self.control = control

    def collect(self, run_key: str, run_dir: Path, step: Step) -> list[str]:
        """Upload and index everything new under `run_dir`. Returns the keys.

        The dedup is read once per sweep rather than per file: the index is one
        round trip on the container path, and a sweep after a late step is
        comparing against dozens of keys it is about to skip.

        **Blob before row, as everywhere else.** A row naming a blob that is not
        there would make the artifact unreadable from the portal with no way to
        tell it from a store outage; a blob with no row is invisible and is
        collected by the next sweep.
        """
        if not run_dir.exists():
            return []

        existing = {row.key: row.sha256 for row in self.control.artifacts()}
        stored: list[str] = []
        for path in sorted(run_dir.rglob("*")):
            if not path.is_file() or path.name in _SKIP:
                continue
            rel = path.relative_to(run_dir).as_posix()
            # Under the tenant prefix since P5-10, so that "this tenant's
            # storage" is one prefix an operator can list and story 32's purge
            # can delete. The tenant comes from the run's own scope rather than
            # from an argument: the collector is built per run and a tenant it
            # could be told would be a tenant it could be told wrongly.
            key = store_keys.artifact_key(
                self.control.scope.tenant_id, run_key, rel
            )
            digest = _sha256(path)

            if existing.get(key) == digest:
                continue  # unchanged since last sweep: don't re-upload or bump

            self.storage.put_file(key, path, content_type_for(key))
            self.control.index_artifact(
                key=key, sha256=digest, kind=classify(rel), step=step
            )
            stored.append(key)
        return stored


class NullCollector:
    """Default no-op (driver tests and runs without storage configured)."""

    def collect(self, run_key: str, run_dir: Path, step: Step) -> list[str]:
        return []
