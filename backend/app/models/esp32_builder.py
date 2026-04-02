from datetime import datetime

from pydantic import BaseModel, Field

from app.models.function_manifest import FunctionInputDefinition, FunctionManifest


class Esp32BuilderFile(BaseModel):
    relative_path: str
    absolute_path: str
    language: str
    editable: bool = True
    size_bytes: int
    content: str


class Esp32FunctionBlueprint(BaseModel):
    manifest: FunctionManifest
    advanced_builder_inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    firmware_entry_file: str
    protocol: str = Field(min_length=1)
    notes: str | None = None
    source_path: str | None = None


class Esp32BoardSummary(BaseModel):
    board_id: str
    display_name: str
    port: str | None = None
    connected: bool
    description: str | None = None
    hardware_id: str | None = None
    serial_number: str | None = None
    workspace_path: str
    generated_function_ids: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)


class Esp32BoardDetail(Esp32BoardSummary):
    files: list[Esp32BuilderFile] = Field(default_factory=list)
    blueprints: list[Esp32FunctionBlueprint] = Field(default_factory=list)
    instructions_path: str | None = None


class Esp32BoardListResponse(BaseModel):
    boards: list[Esp32BoardSummary] = Field(default_factory=list)


class Esp32FileSaveRequest(BaseModel):
    relative_path: str
    content: str


class Esp32FileSaveResponse(BaseModel):
    board_id: str
    relative_path: str
    saved_at: datetime

