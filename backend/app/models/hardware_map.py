from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

HardwareDeviceKind = Literal["stepper_motor", "servo", "sensor"]
HardwareSensorKind = Literal["position_limit_switch", "aht20_temperature_humidity"]


class HardwareBoardMapping(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    usb_port: str = Field(min_length=1)
    enabled: bool = True
    notes: str | None = None
    # A "dynamic" controller isn't permanently wired to usb_port — it's
    # physically swapped in/out of that port during a workflow run (e.g. the
    # 7-syringe-pump ESP32 today, a USB camera in the future). expected_serial_number
    # is the real USB descriptor serial number captured from whichever board was
    # on usb_port when the user confirmed "this is the one", used to verify the
    # right physical device is connected before a workflow acts on it.
    dynamic: bool = False
    expected_serial_number: str | None = None
    expected_hardware_id: str | None = None
    expected_device_label: str | None = None


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
    enabled: bool = True
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
    enabled: bool = True
    notes: str | None = None


class FunctionHardwareAssignment(BaseModel):
    function_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    hardware_device_id: str = ""


class HardwareNodePosition(BaseModel):
    node_id: str = Field(min_length=1)
    x: float
    y: float


class HardwareMap(BaseModel):
    version: int = 1
    boards: list[HardwareBoardMapping] = Field(default_factory=list)
    devices: list[HardwareDeviceMapping] = Field(default_factory=list)
    groups: list[HardwareGroupMapping] = Field(default_factory=list)
    function_assignments: list[FunctionHardwareAssignment] = Field(default_factory=list)
    node_positions: list[HardwareNodePosition] = Field(default_factory=list)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_unique_node_ids(self) -> "HardwareMap":
        seen_ids: set[str] = {"raspberry-pi"}
        duplicates: list[str] = []
        for item_id in [
            *(board.id for board in self.boards),
            *(device.id for device in self.devices),
            *(group.id for group in self.groups),
        ]:
            if item_id in seen_ids:
                duplicates.append(item_id)
            seen_ids.add(item_id)

        if duplicates:
            raise ValueError("Hardware map IDs must be unique: " + ", ".join(sorted(set(duplicates))))

        return self


class HardwareMapSaveResponse(BaseModel):
    path: str
    saved_at: datetime
    hardware_map: HardwareMap


class HardwareBoardConnectionStatus(BaseModel):
    board_id: str
    label: str
    usb_port: str
    dynamic: bool
    expected_serial_number: str | None
    detected_serial_number: str | None
    detected_hardware_id: str | None
    connected: bool
    matched: bool
    message: str
