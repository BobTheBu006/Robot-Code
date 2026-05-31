from threading import Lock

from app.models.robot import (
    AlarmState,
    GantryState,
    RobotState,
    RobotStateUpdate,
    SensorState,
)


def build_default_robot_state() -> RobotState:
    return RobotState(
        machine_state="idle",
        current_workflow="demo_pick_and_place",
        current_step=2,
        gantry=GantryState(x=125.0, y=48.5, z=12.0),
        sensor_values=[
            SensorState(name="gantry_limit_x", value=0),
            SensorState(name="gantry_limit_y", value=0),
        ],
        alarms=[
            AlarmState(
                code="mock_mode",
                message="No active hardware connection. Running in mock mode.",
                severity="info",
                active=True,
            )
        ],
    )


class RobotStateStore:
    def __init__(self) -> None:
        self._lock = Lock()
        self._state = build_default_robot_state()

    def get_state(self) -> RobotState:
        with self._lock:
            return self._state.model_copy(deep=True)

    def update_state(self, update: RobotStateUpdate) -> RobotState:
        with self._lock:
            next_state = self._state.model_copy(deep=True)

            if update.machine_state is not None:
                next_state.machine_state = update.machine_state

            if update.current_workflow is not None:
                next_state.current_workflow = update.current_workflow

            if update.current_step is not None:
                next_state.current_step = update.current_step

            if update.gantry is not None:
                if update.gantry.x is not None:
                    next_state.gantry.x = update.gantry.x
                if update.gantry.y is not None:
                    next_state.gantry.y = update.gantry.y
                if update.gantry.z is not None:
                    next_state.gantry.z = update.gantry.z

            if update.sensor_values is not None:
                next_state.sensor_values = update.sensor_values

            if update.alarms is not None:
                next_state.alarms = update.alarms

            self._state = next_state
            return self._state.model_copy(deep=True)


robot_state_store = RobotStateStore()
