from typing import Literal

from pydantic import BaseModel, Field, model_validator

FUNCTION_MANIFEST_SCHEMA_VERSION = 1
SUPPORTED_FUNCTION_MANIFEST_SCHEMA_VERSIONS = {1}

FunctionInputType = Literal["string", "number", "boolean", "select", "file/path"]
FunctionHardwareDeviceKind = Literal["stepper_motor", "servo", "sensor"]
FunctionHardwareSensorKind = Literal["position_limit_switch", "aht20_temperature_humidity"]
FunctionFirmwareControllerRole = Literal["builder_board", "device_board", "raspberry_pi", "any_controller"]


class FunctionInputOption(BaseModel):
    label: str
    value: str


class FunctionInputDefinition(BaseModel):
    key: str
    label: str
    type: FunctionInputType
    description: str | None = None
    required: bool = True
    default: str | float | bool | None = None
    placeholder: str | None = None
    advanced: bool = False
    min: float | None = None
    max: float | None = None
    options: list[FunctionInputOption] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_select_options(self) -> "FunctionInputDefinition":
        if self.type == "select" and not self.options:
            raise ValueError("Select inputs must declare at least one option.")
        return self


class FunctionOutputDefinition(BaseModel):
    key: str
    label: str
    type: str
    description: str | None = None


class FunctionHardwarePinReference(BaseModel):
    id: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    gpio: str | float | None = None
    function_input_key: str | None = None
    notes: str | None = None


class FunctionHardwareDeviceReference(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    kind: FunctionHardwareDeviceKind
    board_id: str | None = None
    sensor_kind: FunctionHardwareSensorKind | None = None
    rotation_min_deg: float | None = None
    rotation_max_deg: float | None = None
    calibration_ml_per_200_steps: float | None = None
    pins: list[FunctionHardwarePinReference] = Field(default_factory=list)
    basic_block_id: str | None = None
    notes: str | None = None


class FunctionFirmwareRequirement(BaseModel):
    routine_id: str = Field(min_length=1)
    controller_role: FunctionFirmwareControllerRole = "builder_board"
    source: str | None = None
    protocol: str | None = None
    entry_point: str | None = None
    required_device_ids: list[str] = Field(default_factory=list)
    description: str | None = None


class FunctionManifest(BaseModel):
    schema_version: int = Field(default=FUNCTION_MANIFEST_SCHEMA_VERSION, ge=1)
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    version: str = Field(min_length=1)
    inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    advanced_inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    outputs: list[FunctionOutputDefinition] = Field(default_factory=list)
    hardware_devices: list[FunctionHardwareDeviceReference] = Field(default_factory=list)
    firmware_requirements: list[FunctionFirmwareRequirement] = Field(default_factory=list)
    builder_board_id: str | None = None
    builder_source_path: str | None = None
    builder_workspace_path: str | None = None
    builder_firmware_entry_file: str | None = None
    builder_base_function_id: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_schema_version(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        normalized_data = dict(data)
        normalized_data.setdefault("schema_version", FUNCTION_MANIFEST_SCHEMA_VERSION)
        return normalized_data

    @model_validator(mode="after")
    def validate_schema_version(self) -> "FunctionManifest":
        if self.schema_version not in SUPPORTED_FUNCTION_MANIFEST_SCHEMA_VERSIONS:
            supported_versions = ", ".join(str(version) for version in sorted(SUPPORTED_FUNCTION_MANIFEST_SCHEMA_VERSIONS))
            raise ValueError(
                f"Unsupported function manifest schema_version {self.schema_version}. "
                f"Supported versions: {supported_versions}."
            )
        return self


class DiscoveredFunctionDefinition(BaseModel):
    manifest: FunctionManifest
    folder_name: str
    manifest_path: str
    handler_path: str
    requirements_path: str


class FunctionDiscoveryError(BaseModel):
    folder_name: str
    message: str


class FunctionDiscoveryResponse(BaseModel):
    functions: list[DiscoveredFunctionDefinition]
    errors: list[FunctionDiscoveryError] = Field(default_factory=list)


class FunctionTestRequest(BaseModel):
    inputs: dict[str, str | float | bool | None] = Field(default_factory=dict)
    input_data: dict[str, object] | None = None


class FunctionTestResponse(BaseModel):
    function_id: str
    ok: bool
    inputs: dict[str, str | float | bool | None] = Field(default_factory=dict)
    input_data: dict[str, object] | None = None
    result: dict[str, object] | None = None
    error: str | None = None


class FunctionCancelRequest(BaseModel):
    inputs: dict[str, str | float | bool | None] = Field(default_factory=dict)


class FunctionCancelResponse(BaseModel):
    function_id: str
    ok: bool
    message: str
    result: dict[str, object] | None = None
