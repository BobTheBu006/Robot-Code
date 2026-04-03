from typing import Literal

from pydantic import BaseModel, Field, model_validator

GantrySpeedProfile = Literal["slow", "normal", "fast"]
GantryCalibrationSpeedProfile = Literal["safe", "normal"]
GantryLimitMode = Literal["2", "4"]


def _validate_distinct_pins(assignments: dict[str, int], message_prefix: str) -> None:
    pins_to_labels: dict[int, list[str]] = {}
    for label, pin in assignments.items():
        pins_to_labels.setdefault(pin, []).append(label)

    duplicates = [
        f"GPIO {pin}: {', '.join(labels)}"
        for pin, labels in pins_to_labels.items()
        if len(labels) > 1
    ]
    if duplicates:
        raise ValueError(f"{message_prefix}: " + "; ".join(duplicates))


class GantryXYMoveRequest(BaseModel):
    tool_port: str | None = None
    x_cm: float = Field(default=0.0)
    y_cm: float = Field(default=0.0)
    speed_profile: GantrySpeedProfile = "normal"
    x_step_pin: int = Field(default=16, ge=0)
    x_dir_pin: int = Field(default=17, ge=0)
    y_step_pin: int = Field(default=18, ge=0)
    y_dir_pin: int = Field(default=19, ge=0)
    limit_switch_mode: GantryLimitMode = "4"
    x_min_limit_pin: int = Field(default=21, ge=0)
    x_max_limit_pin: int = Field(default=22, ge=0)
    y_min_limit_pin: int = Field(default=23, ge=0)
    y_max_limit_pin: int = Field(default=25, ge=0)
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_pin_assignments(self) -> "GantryXYMoveRequest":
        assigned_pins = {
            "x_step_pin": self.x_step_pin,
            "x_dir_pin": self.x_dir_pin,
            "y_step_pin": self.y_step_pin,
            "y_dir_pin": self.y_dir_pin,
            "x_min_limit_pin": self.x_min_limit_pin,
            "y_min_limit_pin": self.y_min_limit_pin,
        }
        if self.limit_switch_mode == "4":
            assigned_pins["x_max_limit_pin"] = self.x_max_limit_pin
            assigned_pins["y_max_limit_pin"] = self.y_max_limit_pin

        _validate_distinct_pins(
            assigned_pins,
            "Each active XY driver/limit input must use a distinct GPIO pin. Conflicts",
        )
        return self


class GantryXYMoveResponse(BaseModel):
    port: str
    baud_rate: int
    speed_profile: GantrySpeedProfile
    pin_command_sent: str
    pin_reply: str | None = None
    pins_applied: bool = False
    limit_command_sent: str
    limit_reply: str | None = None
    limits_applied: bool = False
    move_command_sent: str
    move_reply: str | None = None
    move_applied: bool = False
    target: dict[str, float]
    configured_pins: dict[str, int]
    configured_limits: dict[str, int | str]


class GantryXYCalibrationRequest(BaseModel):
    tool_port: str | None = None
    x_track_length_cm: float = Field(default=100.0, gt=0)
    y_track_length_cm: float = Field(default=100.0, gt=0)
    calibration_speed_profile: GantryCalibrationSpeedProfile = "safe"
    x_step_pin: int = Field(default=16, ge=0)
    x_dir_pin: int = Field(default=17, ge=0)
    y_step_pin: int = Field(default=18, ge=0)
    y_dir_pin: int = Field(default=19, ge=0)
    limit_switch_mode: GantryLimitMode = "4"
    x_min_limit_pin: int = Field(default=21, ge=0)
    x_max_limit_pin: int = Field(default=22, ge=0)
    y_min_limit_pin: int = Field(default=23, ge=0)
    y_max_limit_pin: int = Field(default=25, ge=0)
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_pin_assignments(self) -> "GantryXYCalibrationRequest":
        GantryXYMoveRequest.model_validate(self.model_dump())
        return self


class GantryXYCalibrationResponse(BaseModel):
    port: str
    baud_rate: int
    calibration_speed_profile: GantryCalibrationSpeedProfile
    pin_command_sent: str
    pin_reply: str | None = None
    pins_applied: bool = False
    limit_command_sent: str
    limit_reply: str | None = None
    limits_applied: bool = False
    calibration_command_sent: str
    calibration_reply: str | None = None
    calibrated: bool = False
    workspace: dict[str, float]
    configured_pins: dict[str, int]
    configured_limits: dict[str, int | str]


class GantryZMoveRequest(BaseModel):
    tool_port: str | None = None
    z_left_cm: float = Field(default=0.0)
    z_right_cm: float = Field(default=0.0)
    speed_profile: GantrySpeedProfile = "normal"
    z_left_step_pin: int = Field(default=32, ge=0)
    z_left_dir_pin: int = Field(default=33, ge=0)
    z_right_step_pin: int = Field(default=4, ge=0)
    z_right_dir_pin: int = Field(default=5, ge=0)
    limit_switch_mode: GantryLimitMode = "4"
    z_left_min_limit_pin: int = Field(default=12, ge=0)
    z_left_max_limit_pin: int = Field(default=13, ge=0)
    z_right_min_limit_pin: int = Field(default=14, ge=0)
    z_right_max_limit_pin: int = Field(default=15, ge=0)
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_pin_assignments(self) -> "GantryZMoveRequest":
        assigned_pins = {
            "z_left_step_pin": self.z_left_step_pin,
            "z_left_dir_pin": self.z_left_dir_pin,
            "z_right_step_pin": self.z_right_step_pin,
            "z_right_dir_pin": self.z_right_dir_pin,
            "z_left_min_limit_pin": self.z_left_min_limit_pin,
            "z_right_min_limit_pin": self.z_right_min_limit_pin,
        }
        if self.limit_switch_mode == "4":
            assigned_pins["z_left_max_limit_pin"] = self.z_left_max_limit_pin
            assigned_pins["z_right_max_limit_pin"] = self.z_right_max_limit_pin

        _validate_distinct_pins(
            assigned_pins,
            "Each active Z driver/limit input must use a distinct GPIO pin. Conflicts",
        )
        return self


class GantryZMoveResponse(BaseModel):
    port: str
    baud_rate: int
    speed_profile: GantrySpeedProfile
    pin_command_sent: str
    pin_reply: str | None = None
    pins_applied: bool = False
    limit_command_sent: str
    limit_reply: str | None = None
    limits_applied: bool = False
    move_command_sent: str
    move_reply: str | None = None
    move_applied: bool = False
    target: dict[str, float]
    configured_pins: dict[str, int]
    configured_limits: dict[str, int | str]


class GantryZCalibrationRequest(BaseModel):
    tool_port: str | None = None
    z_left_track_length_cm: float = Field(default=40.0, gt=0)
    z_right_track_length_cm: float = Field(default=40.0, gt=0)
    calibration_speed_profile: GantryCalibrationSpeedProfile = "safe"
    z_left_step_pin: int = Field(default=32, ge=0)
    z_left_dir_pin: int = Field(default=33, ge=0)
    z_right_step_pin: int = Field(default=4, ge=0)
    z_right_dir_pin: int = Field(default=5, ge=0)
    limit_switch_mode: GantryLimitMode = "4"
    z_left_min_limit_pin: int = Field(default=12, ge=0)
    z_left_max_limit_pin: int = Field(default=13, ge=0)
    z_right_min_limit_pin: int = Field(default=14, ge=0)
    z_right_max_limit_pin: int = Field(default=15, ge=0)
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_pin_assignments(self) -> "GantryZCalibrationRequest":
        GantryZMoveRequest.model_validate(self.model_dump())
        return self


class GantryZCalibrationResponse(BaseModel):
    port: str
    baud_rate: int
    calibration_speed_profile: GantryCalibrationSpeedProfile
    pin_command_sent: str
    pin_reply: str | None = None
    pins_applied: bool = False
    limit_command_sent: str
    limit_reply: str | None = None
    limits_applied: bool = False
    calibration_command_sent: str
    calibration_reply: str | None = None
    calibrated: bool = False
    workspace: dict[str, float]
    configured_pins: dict[str, int]
    configured_limits: dict[str, int | str]
