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
    speed: int | None = Field(default=None, gt=0)
    intake_speed: int | None = Field(default=None, gt=0)
    outtake_speed: int | None = Field(default=None, gt=0)
    head_a_step_pin: int | None = Field(default=None, ge=0)
    head_a_dir_pin: int | None = Field(default=None, ge=0)
    head_b_step_pin: int | None = Field(default=None, ge=0)
    head_b_dir_pin: int | None = Field(default=None, ge=0)
    head_c_step_pin: int | None = Field(default=None, ge=0)
    head_c_dir_pin: int | None = Field(default=None, ge=0)
    head_d_step_pin: int | None = Field(default=None, ge=0)
    head_d_dir_pin: int | None = Field(default=None, ge=0)
    head_e_step_pin: int | None = Field(default=None, ge=0)
    head_e_dir_pin: int | None = Field(default=None, ge=0)
    head_f_step_pin: int | None = Field(default=None, ge=0)
    head_f_dir_pin: int | None = Field(default=None, ge=0)
    head_g_step_pin: int | None = Field(default=None, ge=0)
    head_g_dir_pin: int | None = Field(default=None, ge=0)
    calibration_file: str | None = None
    port: str | None = None
    baud_rate: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def validate_non_empty(self) -> "SyringeDispenseRequest":
        if not any(getattr(self, head) > 0 for head in ("A", "B", "C", "D", "E", "F", "G")):
            raise ValueError("At least one syringe head must be given a positive dispense amount.")
        return self


class SyringePrimeRequest(BaseModel):
    """Home the plungers against the bottom hard stop, then prime with
    draw/push cycles. The plungers have no position feedback, so the hard stop
    is the only way to establish a known zero."""

    prime_volume_ul: float = Field(default=1000.0, gt=0)
    prime_cycles: int = Field(default=3, ge=1)
    home_overtravel_ul: float = Field(default=1000.0, gt=0)
    final_draw_ul: float = Field(default=1000.0, ge=0)
    speed: int = Field(default=60, gt=0)
    head_a_step_pin: int | None = Field(default=None, ge=0)
    head_a_dir_pin: int | None = Field(default=None, ge=0)
    head_b_step_pin: int | None = Field(default=None, ge=0)
    head_b_dir_pin: int | None = Field(default=None, ge=0)
    head_c_step_pin: int | None = Field(default=None, ge=0)
    head_c_dir_pin: int | None = Field(default=None, ge=0)
    head_d_step_pin: int | None = Field(default=None, ge=0)
    head_d_dir_pin: int | None = Field(default=None, ge=0)
    head_e_step_pin: int | None = Field(default=None, ge=0)
    head_e_dir_pin: int | None = Field(default=None, ge=0)
    head_f_step_pin: int | None = Field(default=None, ge=0)
    head_f_dir_pin: int | None = Field(default=None, ge=0)
    head_g_step_pin: int | None = Field(default=None, ge=0)
    head_g_dir_pin: int | None = Field(default=None, ge=0)
    calibration_file: str | None = None
    port: str | None = None
    baud_rate: int | None = Field(default=None, gt=0)


class SyringePrimeResponse(BaseModel):
    port: str
    baud_rate: int
    calibration_file: str
    speed: int
    prime_volume_ul: float
    prime_cycles: int
    home_overtravel_ul: float
    final_draw_ul: float
    final_draw_steps: dict[SyringeHead, int]
    home_steps: dict[SyringeHead, int]
    prime_steps: dict[SyringeHead, int]
    pin_config_commands_sent: list[str] = Field(default_factory=list)
    pin_config_replies: list[str] = Field(default_factory=list)
    pin_config_applied: bool = False
    configured_pins: dict[str, dict[str, int]]
    commands_sent: list[str] = Field(default_factory=list)
    replies: list[str] = Field(default_factory=list)


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
    calibration_file: str
    command_format: str
    speed: int | None = None
    intake_speed: int | None = None
    outtake_speed: int | None = None
    speed_command_sent: str | None = None
    speed_reply: str | None = None
    speed_applied: bool = False
    intake_speed_command_sent: str | None = None
    intake_speed_reply: str | None = None
    intake_speed_applied: bool = False
    outtake_speed_command_sent: str | None = None
    outtake_speed_reply: str | None = None
    outtake_speed_applied: bool = False
    pin_config_commands_sent: list[str] = Field(default_factory=list)
    pin_config_replies: list[str] = Field(default_factory=list)
    pin_config_applied: bool = False
    configured_pins: dict[str, dict[str, int]]
    requested_amounts: dict[SyringeHead, float]
    calculated_steps: dict[SyringeHead, int]
    command_sent: str
    reply: str | None = None
