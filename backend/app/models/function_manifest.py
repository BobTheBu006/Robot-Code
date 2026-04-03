from typing import Literal

from pydantic import BaseModel, Field, model_validator

FunctionInputType = Literal["string", "number", "boolean", "select", "file/path"]


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


class FunctionManifest(BaseModel):
    id: str = Field(min_length=1)
    display_name: str = Field(min_length=1)
    category: str = Field(min_length=1)
    description: str = Field(min_length=1)
    version: str = Field(min_length=1)
    inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    advanced_inputs: list[FunctionInputDefinition] = Field(default_factory=list)
    outputs: list[FunctionOutputDefinition] = Field(default_factory=list)
    builder_board_id: str | None = None
    builder_source_path: str | None = None
    builder_workspace_path: str | None = None
    builder_firmware_entry_file: str | None = None
    builder_base_function_id: str | None = None


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
