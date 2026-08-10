"""Emergency stop and recovery.

Every service that can move something registers itself with the
SafetyController at import time, so this route no longer has to know the list.
That hand-maintained list was how the old `/rearm` ended up clearing two of the
five stop flags.
"""

from fastapi import APIRouter, HTTPException

from app.core.safety import safety_controller
from app.models.safety import (
    AccessDoorOverrideRequest,
    PhysicalStateConfirmRequest,
    SafetyRearmRequest,
    SafetyRearmResponse,
    SafetySnapshot,
    SafetyStopRequest,
    SafetyStopResponse,
)
from app.services.access_door import access_door_sensor
from app.services.physical_state import PhysicalStateError, physical_state_store

# Importing the drivers is what registers them as stoppable actors. Without
# this, an E-Stop arriving before any function had been run would find an empty
# actor list and stop nothing.
import app.services.esp32_builder  # noqa: F401
import app.services.gantry_controller  # noqa: F401
import app.services.hybrid_z_axis  # noqa: F401
import app.services.raspberry_gantry  # noqa: F401
import app.services.syringe_controller  # noqa: F401

router = APIRouter(prefix="/api/safety", tags=["safety"])


@router.get("", response_model=SafetySnapshot)
def get_safety_state() -> SafetySnapshot:
    """Current latch state, registered actors, and anything awaiting confirmation.

    The UI needs this to show a latched stop and to refuse to start work; before
    it existed there was no way to ask whether the machine was blocked.
    """
    return SafetySnapshot.model_validate(_snapshot_with_access_door())


def _snapshot_with_access_door() -> dict:
    """Latch state plus the access-door interlock.

    `run_allowed` folds both together so a caller cannot start a workflow with
    either the stop latched or the door open. It deliberately does NOT gate a
    single block test: bringing hardware up means reaching into the machine,
    and the operator is standing there.
    """
    snapshot = safety_controller.snapshot()
    door = access_door_sensor.read()
    snapshot["access_door"] = door.to_dict()
    snapshot["run_allowed"] = not snapshot.get("motion_blocked", False) and not door.blocks_run
    return snapshot


@router.get("/access-door")
def get_access_door() -> dict:
    """Just the door, for a UI that polls it while showing the Run button."""
    return access_door_sensor.read().to_dict()


@router.post("/access-door/override")
def set_access_door_override(request: AccessDoorOverrideRequest) -> dict:
    """Allow (or stop allowing) runs while the door is open.

    Not persisted, and it does not touch the E-Stop: overriding the door must
    never clear a latched stop. Someone who overrides the door and then hits
    E-Stop still gets a stopped machine.
    """
    state = access_door_sensor.set_override(request.enabled)
    return state.to_dict()


@router.post("/run-session/start")
def start_run_session() -> dict:
    """Mark a workflow run as starting, and watch the door for its duration.

    Refuses when the door blocks a run, so the interlock is enforced by the
    backend rather than only by whichever UI happens to be driving it.
    """
    door = access_door_sensor.read()
    if door.blocks_run:
        raise HTTPException(status_code=409, detail=door.reason)
    if safety_controller.is_blocked():
        raise HTTPException(status_code=409, detail=safety_controller.blocked_reason())

    def _door_opened(state) -> None:
        # Opening the door mid-run is treated exactly like someone hitting the
        # stop: every registered actor is stopped through the one authority.
        safety_controller.stop(
            reason=f"Access door opened during a run (GPIO {state.pin}).",
            source="access-door",
        )

    access_door_sensor.start_watching(_door_opened)
    return {"ok": True, "watching": True, "access_door": door.to_dict()}


@router.post("/run-session/end")
def end_run_session() -> dict:
    """Stop watching the door. Safe to call when no run is in progress."""
    access_door_sensor.stop_watching()
    return {"ok": True, "watching": False}


@router.post("/stop", response_model=SafetyStopResponse)
def stop(request: SafetyStopRequest | None = None) -> SafetyStopResponse:
    payload = request or SafetyStopRequest()
    record = safety_controller.stop(reason=payload.reason, source=payload.source)
    snapshot = safety_controller.snapshot()

    return SafetyStopResponse(
        ok=record.ok,
        state=str(snapshot["state"]),
        message=(
            "Emergency stop engaged."
            if record.ok
            else "Emergency stop engaged, but at least one subsystem did not confirm it stopped."
        ),
        results=[
            {
                "actor_id": report.actor_id,
                "ok": report.ok,
                "message": report.message,
                "duration_ms": round(report.duration_ms, 3),
            }
            for report in record.reports
        ],
        requires_confirmation=list(snapshot["requires_confirmation"]),  # type: ignore[arg-type]
    )


@router.post("/rearm", response_model=SafetyRearmResponse)
def rearm(request: SafetyRearmRequest | None = None) -> SafetyRearmResponse:
    """Clear the latch. Refuses while any physical fact is still unconfirmed.

    This is deliberately an explicit operator action: starting a run or testing
    a block must never clear it as a side effect.
    """
    payload = request or SafetyRearmRequest()
    return SafetyRearmResponse.model_validate(safety_controller.rearm(operator=payload.operator))


@router.post("/confirm-physical-state", response_model=SafetySnapshot)
def confirm_physical_state(request: PhysicalStateConfirmRequest) -> SafetySnapshot:
    """Record what an operator actually observed on the machine."""
    try:
        physical_state_store.confirm(request.fact_id, request.value, operator=request.operator)
    except PhysicalStateError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return SafetySnapshot.model_validate(_snapshot_with_access_door())
