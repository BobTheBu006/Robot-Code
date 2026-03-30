from fastapi import APIRouter

from app.models.robot import RobotState, RobotStateUpdate
from app.services.robot_state import robot_state_store

router = APIRouter(prefix="/api/robot", tags=["robot"])


@router.get("/state", response_model=RobotState)
def get_robot_state() -> RobotState:
    return robot_state_store.get_state()


@router.post("/state/mock-update", response_model=RobotState)
def update_mock_robot_state(update: RobotStateUpdate) -> RobotState:
    return robot_state_store.update_state(update)
