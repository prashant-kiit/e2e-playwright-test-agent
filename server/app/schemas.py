"""Pydantic request/response schemas for the API."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from .domain.status import RunStatus
from .domain.steps import Step


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    name: str
    created_at: datetime


class TargetConfigBody(BaseModel):
    """A target's configuration, as the portal's form sends it.

    Only the format checks Pydantic can do cheaply live here; what a *valid*
    base URL or target repo is belongs to app/target_config.py, which is the
    one definition the write path and the cutover both use.
    """

    base_url: str = Field(min_length=1, max_length=500)
    target_repo: str = Field(min_length=1, max_length=200)
    target_branch: str = Field(default="", max_length=200)
    locators: str = ""
    agent_notes: list[str] = Field(default_factory=list)


class TargetCreate(TargetConfigBody):
    app: str = Field(min_length=1, max_length=100)  # the target's slug
    name: str = Field(min_length=1, max_length=200)


class TargetConfigUpdate(BaseModel):
    """A config edit. Every field is optional: the form sends what changed."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    base_url: str | None = Field(default=None, max_length=500)
    target_repo: str | None = Field(default=None, max_length=200)
    target_branch: str | None = Field(default=None, max_length=200)
    locators: str | None = None
    agent_notes: list[str] | None = None


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    app: str
    name: str
    base_url: str
    locators: str
    agent_notes: list[str]
    target_repo: str
    target_branch: str
    created_at: datetime


class RunCreate(BaseModel):
    story_id: str = Field(min_length=1, max_length=40)
    mode: str = Field(pattern="^(changed|full)$")


class StepOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    step: Step
    status: str
    attempt: int
    started_at: datetime | None
    finished_at: datetime | None


class AppOut(BaseModel):
    app: str
    name: str
    baseURL: str
    targetRepo: str
    targetBranch: str
    repoUrl: str | None
    storyCount: int


class StoryOut(BaseModel):
    story_id: str
    slug: str
    title: str
    file: str


class BootstrapBody(BaseModel):
    app: str = Field(min_length=1, max_length=100)
    name: str = Field(min_length=1, max_length=200)
    baseURL: str = ""
    targetRepo: str = ""
    targetBranch: str = "master"
    locators: str = ""
    agentNotes: list[str] = Field(default_factory=list)
    do_bootstrap: bool = True


class BootstrapOutcomeOut(BaseModel):
    """The target-repo step's outcome. `ok=False` with the reason in `output` is
    a normal response: apps/<app>/ was created even if the sync did not land."""

    model_config = ConfigDict(from_attributes=True)
    ok: bool
    output: str


class BootstrapAppOut(BaseModel):
    app: str
    created: bool
    bootstrap: BootstrapOutcomeOut | None = None


class PromptOut(BaseModel):
    name: str
    content: str


class ArtifactOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_id: int
    step: str | None
    kind: str
    s3_key: str
    sha256: str
    version: int
    created_at: datetime


class RunOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    run_key: str
    target_id: int
    story_id: str
    mode: str
    status: RunStatus
    current_step: Step | None
    last_completed_step: Step | None
    pause_requested: bool
    stop_requested: bool
    lease_expires_at: datetime | None
    error: str | None
    created_at: datetime


# --- delivery (P1: the shell tools became portal actions) ----------------

class DeliverBody(BaseModel):
    story_id: str = Field(min_length=1, max_length=40)
    run_id: str | None = None
    dry_run: bool = False


class ResetBody(BaseModel):
    """`confirm_repo` must echo the target repo name: reset-target.sh read that
    confirmation from a TTY, and a portal action has none."""

    confirm_repo: str = Field(min_length=1, max_length=200)
    dry_run: bool = False


class DeliveryStateOut(BaseModel):
    """"Is this delivered?", answered from Postgres (invariant 5).

    `delivered` and `revisions_ahead` are the two states the portal shows. They
    cost one query and no network call, so the answer is the same for everyone
    and does not depend on GitHub being reachable.
    """

    app: str
    repo: str
    branch: str
    bootstrapped: bool
    delivered: bool
    rev: int | None
    delivered_sha: str | None
    revisions_ahead: int
    summary: str


class DeliveryOut(BaseModel):
    ok: bool
    message: str
    pr_url: str = ""
    pr_number: int | None = None
    detail: dict = {}


# --- revisions / file_index / parity (P2) --------------------------------
#
# All read-only except the snapshot action. These describe the dual-written
# revision model; nothing in the system reads them to make a decision in P2.

class RevisionOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    rev: int
    parent_rev: int | None
    tree_hash: str
    produced_by_run_id: int | None
    author: str
    created_at: datetime
    file_count: int


class SnapshotOut(BaseModel):
    """The outcome of a manual snapshot.

    `created=False` with the unchanged head in `revision` is a normal response,
    not a failure: a tree whose hash already matches the head commits nothing,
    because `rev` counts real changes rather than counting attempts.
    """

    created: bool
    revision: RevisionOut


class FileIndexOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    path: str
    blob_key: str
    size: int


class ParityOut(BaseModel):
    """Whether a target's head revision agrees with the files on disk.

    `has_revision=False` is its own state: a never-snapshotted target is not
    "in sync", and is not an error either.
    """

    has_revision: bool
    in_sync: bool
    rev: int | None
    tree_hash: str | None
    only_in_db: list[str]
    only_on_disk: list[str]
    modified: list[str]
