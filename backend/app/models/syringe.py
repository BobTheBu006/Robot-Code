from typing import Literal

from pydantic import BaseModel, Field, model_validator

SyringeHead = Literal["A", "B", "C", "D", "E", "F", "G"]


class SyringeCalibrationEntry(BaseModel):
    a: float
    b: float = 0.0


class SyringeDispenseRequest(BaseModel):
    A: float = Field(default=0.0, ge=0)
    B: float = Field(default=0.0, ge=0)
    C: float = Field(default=0.0, ge=0)
    D: float = Field(default=0.0, ge=0)
    E: float = Field(default=0.0, ge=0)
    F: float = Field(default=0.0, ge=0)
    G: float = Field(default=0.0, ge=0)
    port: str | None = None
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_non_empty(self) -> "SyringeDispenseRequest":
        if not any(getattr(self, head) > 0 for head in ("A", "B", "C", "D", "E", "F", "G")):
            raise ValueError("At least one syringe head must be given a positive dispense amount.")
        return self


class SyringeStatusResponse(BaseModel):
    connected: bool
    selected_port: str | None = None
    available_ports: list[str]
    calibration_file: str
    calibration_loaded: bool
    command_format: str
    error: str | None = None


class SyringeDispenseResponse(BaseModel):
    port: str
    baud_rate: int
    command_format: str
    requested_amounts: dict[SyringeHead, float]
    calculated_steps: dict[SyringeHead, int]
    command_sent: str
    reply: str | None = None
