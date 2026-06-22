from datetime import datetime

from pydantic import BaseModel, Field

WORKFLOW_SCHEMA_VERSION = 1
SUPPORTED_WORKFLOW_SCHEMA_VERSIONS = {1}


class WorkflowFileSummary(BaseModel):
    filename: str
    path: str
    updated_at: datetime
    size_bytes: int


class WorkflowListResponse(BaseModel):
    default_filename: str
    workflows: list[WorkflowFileSummary] = Field(default_factory=list)


class WorkflowFileResponse(BaseModel):
    filename: str
    path: str
    workflow: dict[str, object]


class WorkflowSaveRequest(BaseModel):
    workflow: dict[str, object]
    path: str | None = None
    filename: str | None = None


class WorkflowSaveResponse(BaseModel):
    filename: str
    path: str
    saved_at: datetime
