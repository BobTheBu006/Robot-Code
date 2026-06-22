from datetime import datetime

from pydantic import BaseModel, Field

from app.models.function_manifest import FunctionInputDefinition, FunctionManifest

ESP32_FUNCTION_BLUEPRINT_SCHEMA_VERSION = 1


class Esp32BuilderFile(BaseModel):
    relative_path: str
    absolute_path: str
    language: str
    editable: bool = True
    size_bytes: int
    content: str


class Esp32FunctionBlueprint(BaseModel):
    schema_version: int = Field(default=ESP32_FUNCTION_BLUEPRINT_SCHEMA_VERSION, ge=1)
    manifest: FunctionManifest
    advanced_builder_inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    firmware_entry_file: str
    protocol: str = Field(min_length=1)
    notes: str | None = None
    source_path: str | None = None
    base_function_id: str | None = None


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


class Esp32ToolchainStatus(BaseModel):
    arduino_cli_available: bool
    arduino_cli_path: str | None = None
    config_file: str | None = None
    package_index_url: str
    fqbn_default: str
    auto_reset_note: str


class Esp32BoardDetail(Esp32BoardSummary):
    files: list[Esp32BuilderFile] = Field(default_factory=list)
    blueprints: list[Esp32FunctionBlueprint] = Field(default_factory=list)
    instructions_path: str | None = None
    firmware_entry_file: str | None = None
    fqbn: str | None = None
    toolchain: Esp32ToolchainStatus | None = None


class Esp32BoardListResponse(BaseModel):
    boards: list[Esp32BoardSummary] = Field(default_factory=list)


class Esp32FirmwareActionResponse(BaseModel):
    board_id: str
    action: str
    ok: bool
    fqbn: str
    port: str | None = None
    sketch_entry_file: str
    command: list[str] = Field(default_factory=list)
    log: str
    auto_reset_attempted: bool = False
    auto_reset_note: str


class Esp32FileSaveRequest(BaseModel):
    relative_path: str
    content: str


class Esp32FileSaveResponse(BaseModel):
    board_id: str
    relative_path: str
    saved_at: datetime


class Esp32CustomBlockSaveRequest(BaseModel):
    source_function_id: str
    display_name: str = Field(min_length=1)
    description: str | None = None
    defaults: dict[str, str | float | bool | None] = Field(default_factory=dict)


class Esp32CustomBlockSaveResponse(BaseModel):
    board_id: str
    function_id: str
    display_name: str
    blueprint_path: str
    saved_at: datetime


class Esp32CustomBlockDeleteResponse(BaseModel):
    board_id: str
    function_id: str
    display_name: str
    blueprint_path: str
    deleted_at: datetime
