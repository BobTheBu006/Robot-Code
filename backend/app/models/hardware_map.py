from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

HardwareDeviceKind = Literal["stepper_motor", "servo", "sensor"]
HardwareSensorKind = Literal["position_limit_switch", "aht20_temperature_humidity"]


class HardwareBoardMapping(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    usb_port: str = Field(min_length=1)
    notes: str | None = None


class HardwarePinMapping(BaseModel):
    id: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    gpio: str = Field(min_length=1)
    function_input_key: str | None = None
    notes: str | None = None


class HardwareDeviceMapping(BaseModel):
    id: str = Field(min_length=1)
    board_id: str = ""
    name: str = Field(min_length=1)
    kind: HardwareDeviceKind = "stepper_motor"
    sensor_kind: HardwareSensorKind | None = None
    rotation_min_deg: float | None = None
    rotation_max_deg: float | None = None
    calibration_ml_per_200_steps: float | None = None
    pins: list[HardwarePinMapping] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_kind(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        normalized_data = dict(data)
        legacy_kind = normalized_data.get("kind")
        if legacy_kind == "motor":
            normalized_data["kind"] = "stepper_motor"
        elif legacy_kind in {"actuator", "other"}:
            normalized_data["kind"] = "servo"

        if normalized_data.get("kind") == "sensor" and not normalized_data.get("sensor_kind"):
            normalized_data["sensor_kind"] = "position_limit_switch"

        return normalized_data


class HardwareGroupMapping(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    member_ids: list[str] = Field(default_factory=list)
    notes: str | None = None


class HardwareMap(BaseModel):
    version: int = 1
    boards: list[HardwareBoardMapping] = Field(default_factory=list)
    devices: list[HardwareDeviceMapping] = Field(default_factory=list)
    groups: list[HardwareGroupMapping] = Field(default_factory=list)
    updated_at: datetime | None = None


class HardwareMapSaveResponse(BaseModel):
    path: str
    saved_at: datetime
    hardware_map: HardwareMap
