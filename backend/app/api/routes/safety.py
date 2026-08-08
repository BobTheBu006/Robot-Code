"""Emergency stop and recovery.

Every service that can move something registers itself with the
SafetyController at import time, so this route no longer has to know the list.
That hand-maintained list was how the old `/rearm` ended up clearing two of the
five stop flags.
"""

from fastapi import APIRouter, HTTPException

from app.core.safety import safety_controller
from app.models.safety import (
    PhysicalStateConfirmRequest,
    SafetyRearmRequest,
    SafetyRearmResponse,
    SafetySnapshot,
    SafetyStopRequest,
    SafetyStopResponse,
)
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
    return SafetySnapshot.model_validate(safety_controller.snapshot())


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

    return SafetySnapshot.model_validate(safety_controller.snapshot())
