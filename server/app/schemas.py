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


class TargetCreate(BaseModel):
    app: str = Field(min_length=1, max_length=100)  # apps/<app> folder name
    name: str = Field(min_length=1, max_length=200)


class TargetOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)
    id: int
    project_id: int
    app: str
    name: str
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


class BootstrappedOut(BaseModel):
    app: str
    repo: str
    branch: str
    bootstrapped: bool


class DeliveryOut(BaseModel):
    ok: bool
    message: str
    pr_url: str = ""
    pr_number: int | None = None
    detail: dict = {}
