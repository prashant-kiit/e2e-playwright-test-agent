"""The values that cross the control-plane boundary.

Plain frozen dataclasses with explicit `as_dict`/`from_dict`, rather than ORM
rows or pydantic models, for three reasons:

- **An ORM row cannot cross it.** A `Run` is bound to a session, and on the
  container path there is no session on the far side. What a run needs are the
  handful of fields it actually reads, which is a much smaller and much more
  reviewable surface than "the row".
- **The serialization is symmetric and visible.** `from_dict(as_dict(x)) == x`
  is a property a test can state, and tests/test_control_gateway.py states it by
  running one suite through both transports. A field added to one half and
  forgotten in the other fails there rather than in a container.
- **Nothing here is a schema for a public API.** These routes are internal, on
  an internal network, and their only client ships in the same package.

`TargetConfig` is reused rather than restated: it is already the target's row
minus its credential (app/target_config.py), which is already exactly what a
sandbox is allowed to know about a target, and restating it here would be a
second list of fields to keep in step with that one.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..domain.status import RunStatus
from ..domain.steps import Step
from ..target_config import TargetConfig


def _step(value: str | None) -> Step | None:
    return Step(value) if value else None


@dataclass(frozen=True)
class RunFacts:
    """A run's immutable facts, read once at the top of the pipeline.

    The driver reads these in one call and then does not ask again, which is
    what makes the read cheap enough to be a round trip: the fields that *do*
    change during a run are in `RunState`.
    """

    run_id: int
    run_key: str
    app: str
    story_id: str
    mode: str
    status: RunStatus
    last_completed_step: Step | None
    claude_session_id: str | None
    target: TargetConfig

    def as_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "run_key": self.run_key,
            "app": self.app,
            "story_id": self.story_id,
            "mode": self.mode,
            "status": self.status.value,
            "last_completed_step": (
                self.last_completed_step.value if self.last_completed_step else None
            ),
            "claude_session_id": self.claude_session_id,
            "target": {
                "app": self.target.app,
                "name": self.target.name,
                "base_url": self.target.base_url,
                "locators": self.target.locators,
                "agent_notes": list(self.target.agent_notes),
                "target_repo": self.target.target_repo,
                "target_branch": self.target.target_branch,
            },
        }

    @classmethod
    def from_dict(cls, raw: dict) -> RunFacts:
        target = raw["target"]
        return cls(
            run_id=raw["run_id"],
            run_key=raw["run_key"],
            app=raw["app"],
            story_id=raw["story_id"],
            mode=raw["mode"],
            status=RunStatus(raw["status"]),
            last_completed_step=_step(raw["last_completed_step"]),
            claude_session_id=raw["claude_session_id"],
            target=TargetConfig(
                app=target["app"],
                name=target["name"],
                base_url=target["base_url"],
                locators=target["locators"],
                agent_notes=tuple(target["agent_notes"]),
                target_repo=target["target_repo"],
                target_branch=target["target_branch"],
            ),
        )


@dataclass(frozen=True)
class RunState:
    """What the driver re-reads at every step boundary.

    Separate from `RunFacts` because these are the fields an *operator* changes
    under a running run -- a pause, a stop -- and the boundary is where the run
    is required to notice. Keeping them apart is what lets the facts be read
    once.
    """

    status: RunStatus
    stop_requested: bool
    pause_requested: bool
    claude_session_id: str | None

    def as_dict(self) -> dict:
        return {
            "status": self.status.value,
            "stop_requested": self.stop_requested,
            "pause_requested": self.pause_requested,
            "claude_session_id": self.claude_session_id,
        }

    @classmethod
    def from_dict(cls, raw: dict) -> RunState:
        return cls(
            status=RunStatus(raw["status"]),
            stop_requested=raw["stop_requested"],
            pause_requested=raw["pause_requested"],
            claude_session_id=raw["claude_session_id"],
        )


@dataclass(frozen=True)
class RevisionFile:
    """One `file_index` row, as hydrate needs it: where to write, what to fetch."""

    path: str
    blob_key: str
    size: int

    def as_dict(self) -> dict:
        return {"path": self.path, "blob_key": self.blob_key, "size": self.size}

    @classmethod
    def from_dict(cls, raw: dict) -> RevisionFile:
        return cls(path=raw["path"], blob_key=raw["blob_key"], size=raw["size"])


@dataclass(frozen=True)
class HeadRevision:
    """The revision hydrate builds a worktree from."""

    rev: int
    tree_hash: str
    files: tuple[RevisionFile, ...]

    def as_dict(self) -> dict:
        return {
            "rev": self.rev,
            "tree_hash": self.tree_hash,
            "files": [f.as_dict() for f in self.files],
        }

    @classmethod
    def from_dict(cls, raw: dict) -> HeadRevision:
        return cls(
            rev=raw["rev"],
            tree_hash=raw["tree_hash"],
            files=tuple(RevisionFile.from_dict(f) for f in raw["files"]),
        )


@dataclass(frozen=True)
class TrackedBlob:
    """One tracked file a run is committing: its path, its hash, its size.

    What ingest sends instead of a tree. The blob itself goes up separately and
    is content-addressed, so this is the *manifest* -- and the service recomputes
    the tree hash from it rather than being told what it is, which is why a
    sandbox cannot commit a revision whose recorded hash does not describe its
    own contents.
    """

    path: str
    sha256: str
    size: int

    def as_dict(self) -> dict:
        return {"path": self.path, "sha256": self.sha256, "size": self.size}

    @classmethod
    def from_dict(cls, raw: dict) -> TrackedBlob:
        return cls(path=raw["path"], sha256=raw["sha256"], size=raw["size"])


@dataclass(frozen=True)
class StoredArtifact:
    """One row of this run's artifact index, as the collector needs to read it.

    The collector's dedup rule is "one row per (run, key), version bumped when
    the content changes", so what it has to know before a sweep is which keys
    this run already has and what was in them.
    """

    key: str
    sha256: str
    version: int

    def as_dict(self) -> dict:
        return {"key": self.key, "sha256": self.sha256, "version": self.version}

    @classmethod
    def from_dict(cls, raw: dict) -> StoredArtifact:
        return cls(key=raw["key"], sha256=raw["sha256"], version=raw["version"])
