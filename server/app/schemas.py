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
