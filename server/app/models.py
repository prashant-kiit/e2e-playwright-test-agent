"""SQLAlchemy ORM models: the portal's authoritative state (replaces .qa-state.json).

One owner per concern: Postgres owns run *status* and history, a target's
*configuration* and -- via `Revision` + `FileIndex` -- the index of its tracked
tree; SeaweedFS owns the *blobs* those rows name, both tree content and run
artifacts; the customer's git repo holds the *delivered* copy of the tests.

P3 moved truth here. `Revision` + `FileIndex` are no longer dual-written
scaffolding: the head revision plus the target's config row are what hydrate
builds a worktree from, what ingest commits to, and what delivery pushes.

`tenant_id` is on every table from P2 (DESIGN.md §13), always written from
`tenancy.current_tenant_id()`, so P5 is a backfill rather than a migration
across every model.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum as _Enum

from sqlalchemy import (
    JSON,
    BigInteger,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy import (
    Enum as SAEnum,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base
from .domain.status import RunStatus
from .domain.steps import Step


def _enum_col(enum_cls: type[_Enum]) -> SAEnum:
    """A VARCHAR-backed enum column that stores member .value and reads back the
    enum member (so RunStatus/Step round-trip instead of degrading to bare str)."""
    return SAEnum(
        enum_cls,
        native_enum=False,
        length=20,
        values_callable=lambda e: [m.value for m in e],
        validate_strings=True,
    )


def _tenant_col() -> Mapped[int]:
    """`tenant_id`, non-null, with no server default.

    The default lives in the migration (so existing rows backfill) and is
    dropped there in the same revision: application code must set the column
    from tenancy.current_tenant_id() rather than letting the database guess.
    """
    return mapped_column(
        Integer, ForeignKey("tenants.id", ondelete="RESTRICT"), nullable=False, index=True
    )


class Tenant(Base):
    """One customer. There is exactly one, seeded by the migration, until P5."""

    __tablename__ = "tenants"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    name: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    targets: Mapped[list[Target]] = relationship(
        back_populates="project", cascade="all, delete-orphan"
    )


class Target(Base):
    """A test-target application under test, and its configuration.

    P3 moved the configuration here from apps/<app>/app.json (DESIGN.md §4):
    `base_url`, `locators`, `agent_notes`, `target_repo` and `target_branch` are
    columns, SaaS-internal, and never delivered to a customer repo. What a valid
    value is lives in app/target_config.py, which validates on the write path.

    The columns are non-null with no server default, like `tenant_id`: the
    backfill default exists in the migration and is dropped there, so a target
    cannot be created with a configuration the database guessed.
    """

    __tablename__ = "targets"
    __table_args__ = (UniqueConstraint("app", name="uq_targets_app"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"), nullable=False
    )
    app: Mapped[str] = mapped_column(String(100), nullable=False)  # the target's slug
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    base_url: Mapped[str] = mapped_column(String(500), nullable=False)
    locators: Mapped[str] = mapped_column(Text, nullable=False)
    # A JSON array: it is a list in app.json today and is injected into the
    # agent's prompt context as a list.
    agent_notes: Mapped[list] = mapped_column(JSON, nullable=False)
    target_repo: Mapped[str] = mapped_column(String(200), nullable=False)
    target_branch: Mapped[str] = mapped_column(String(200), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    project: Mapped[Project] = relationship(back_populates="targets")
    runs: Mapped[list[Run]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )
    revisions: Mapped[list[Revision]] = relationship(
        back_populates="target", cascade="all, delete-orphan"
    )


class Run(Base):
    __tablename__ = "runs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    run_key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
    )
    story_id: Mapped[str] = mapped_column(String(40), nullable=False)  # e.g. SCRUM-201
    mode: Mapped[str] = mapped_column(String(10), nullable=False)      # "changed" | "full"
    status: Mapped[RunStatus] = mapped_column(
        _enum_col(RunStatus), default=RunStatus.PENDING, nullable=False
    )
    current_step: Mapped[Step | None] = mapped_column(_enum_col(Step), nullable=True)
    last_completed_step: Mapped[Step | None] = mapped_column(_enum_col(Step), nullable=True)
    pause_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    stop_requested: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    claude_session_id: Mapped[str | None] = mapped_column(String(80), nullable=True)
    # The sandbox executing this run, as its scheduler names it: a container id,
    # a job name, a task ARN. Opaque to the control plane, which records it so an
    # SRE can find the sandbox behind a live run and the stop path has something
    # to kill. Null for a run on the thread path: there is no sandbox to find,
    # and the column says so rather than guessing (P4).
    sandbox_handle: Mapped[str | None] = mapped_column(String(200), nullable=True)
    # What the run cost: the agent's reported spend and how long its sandbox
    # existed. Recorded so cost is attributable per run before per-tenant
    # quotas exist (P5's), and written by the launcher at the end of a run --
    # null for a run whose sandbox vanished without recording anything, which
    # the lease reaper is what reconciles (P4).
    spend_usd: Mapped[float | None] = mapped_column(Numeric(10, 4), nullable=True)
    sandbox_seconds: Mapped[int | None] = mapped_column(Integer, nullable=True)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )

    target: Mapped[Target] = relationship(back_populates="runs")
    steps: Mapped[list[RunStep]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    artifacts: Mapped[list[Artifact]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class RunStep(Base):
    __tablename__ = "run_steps"
    __table_args__ = (UniqueConstraint("run_id", "step", name="uq_run_steps_run_step"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[Step] = mapped_column(_enum_col(Step), nullable=False)
    status: Mapped[str] = mapped_column(String(12), default="pending", nullable=False)
    attempt: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    run: Mapped[Run] = relationship(back_populates="steps")


class Artifact(Base):
    __tablename__ = "artifacts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    step: Mapped[str | None] = mapped_column(String(20), nullable=True)
    kind: Mapped[str] = mapped_column(String(30), nullable=False)  # trace|video|screenshot|report
    s3_key: Mapped[str] = mapped_column(String(500), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    run: Mapped[Run] = relationship(back_populates="artifacts")


class RunLog(Base):
    """One live log line of one run: the stream the portal reads by cursor.

    P4 moved the run into a container, so the lines have to land somewhere both
    the writer and the API can reach. Append-only, `(run_id, seq)` as the primary
    key, and `seq` counted by the one writer that executes the run.

    **The live view and its recent history, not the archive.** `session.jsonl`
    remains the durable per-run record (DESIGN.md §10) and these rows are pruned
    past a retention window (`orchestrator.bus.prune_run_logs`), so the
    convenience of a readable stream does not become unbounded growth.
    """

    __tablename__ = "run_log"

    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), primary_key=True
    )
    seq: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=False)
    tenant_id: Mapped[int] = _tenant_col()
    line: Mapped[str] = mapped_column(Text, nullable=False)
    at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False, index=True
    )


class AppLock(Base):
    """One row per app that currently has a live run. The PK enforces the
    'no two live runs per app' rule; the lease lets a reaper free a dead run."""

    __tablename__ = "app_locks"

    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), primary_key=True
    )
    tenant_id: Mapped[int] = _tenant_col()
    run_id: Mapped[int] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    lease_expires_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )


class Revision(Base):
    """An immutable snapshot of one target's tracked tree at a step boundary.

    Append-only and content-addressed: `tree_hash` names the tree, `FileIndex`
    names each file's blob, and nothing ever updates a committed row. A target's
    **head is derived** -- the greatest `rev` -- rather than stored, because a
    second place recording "which is current" is a second thing that can be
    wrong.

    `unique(target_id, rev)` is this phase's optimistic-concurrency check
    (amending DESIGN.md §3, which listed an `occ_version` column): committing
    rev N+1 with parent N means a concurrent committer loses the insert. An
    extra column would misdescribe where the check happens.
    """

    __tablename__ = "revisions"
    __table_args__ = (
        UniqueConstraint("target_id", "rev", name="uq_revisions_target_rev"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    target_id: Mapped[int] = mapped_column(
        ForeignKey("targets.id", ondelete="CASCADE"), nullable=False
    )
    rev: Mapped[int] = mapped_column(Integer, nullable=False)  # monotonic per target, from 1
    parent_rev: Mapped[int | None] = mapped_column(Integer, nullable=True)  # null = baseline
    tree_hash: Mapped[str] = mapped_column(String(64), nullable=False)
    # Null for a manual snapshot: an operator can snapshot without a run.
    produced_by_run_id: Mapped[int | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL"), nullable=True
    )
    author: Mapped[str] = mapped_column(String(100), nullable=False)
    # Added by P2 and NEVER written by it: delivery still works off the
    # filesystem, so invariant 5 ("'in sync?' is a Postgres query") is
    # deliberately not satisfied yet. Recording an approval-time sha is P3/P7.
    delivered_sha: Mapped[str | None] = mapped_column(String(40), nullable=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    target: Mapped[Target] = relationship(back_populates="revisions")
    files: Mapped[list[FileIndex]] = relationship(
        back_populates="revision",
        cascade="all, delete-orphan",
        order_by="FileIndex.path",
    )


class FileIndex(Base):
    """One tracked file inside one revision: its path and the blob holding it.

    **Derived data** (DESIGN.md decision 1). It exists so the portal can list
    and display files without walking a tree; nothing may treat it as
    authoritative. `path` is target-relative -- the shape P3's hydrate builds,
    not this repo's apps/<app>/ layout.
    """

    __tablename__ = "file_index"

    revision_id: Mapped[int] = mapped_column(
        ForeignKey("revisions.id", ondelete="CASCADE"), primary_key=True
    )
    path: Mapped[str] = mapped_column(String(500), primary_key=True)
    tenant_id: Mapped[int] = _tenant_col()
    blob_key: Mapped[str] = mapped_column(String(500), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)

    revision: Mapped[Revision] = relationship(back_populates="files")
