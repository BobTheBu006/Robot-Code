from typing import Literal

from pydantic import BaseModel, Field

MachineState = Literal["idle", "running", "paused", "alarm"]
AlarmSeverity = Literal["info", "warning", "critical"]
SensorValueType = float | int | str


class GantryState(BaseModel):
    x: float
    y: float
    z: float


class GantryStateUpdate(BaseModel):
    x: float | None = None
    y: float | None = None
    z: float | None = None


class SensorState(BaseModel):
    name: str
    value: SensorValueType
    unit: str | None = None


class AlarmState(BaseModel):
    code: str
    message: str
    severity: AlarmSeverity = "warning"
    active: bool = True


class RobotState(BaseModel):
    machine_state: MachineState
    current_workflow: str | None = None
    current_step: int | None = Field(default=None, ge=0)
    gantry: GantryState
    sensor_values: list[SensorState]
    alarms: list[AlarmState]


class RobotStateUpdate(BaseModel):
    machine_state: MachineState | None = None
    current_workflow: str | None = None
    current_step: int | None = Field(default=None, ge=0)
    gantry: GantryStateUpdate | None = None
    sensor_values: list[SensorState] | None = None
    alarms: list[AlarmState] | None = None
