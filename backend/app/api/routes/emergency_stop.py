"""Compatibility shim for the original E-Stop URLs.

The behaviour now lives in `app.api.routes.safety`, which owns the single
latch. These paths are kept so the current frontend keeps working while it is
migrated; new callers should use `/api/safety/*`.

Note the deliberate behaviour change on `/rearm`: it no longer unconditionally
clears the latch. The frontend calls it before every block test, which is
exactly how a pressed E-Stop used to get silently cleared. It now refuses while
any physical fact is unconfirmed, and the caller is told what to confirm.
"""

from fastapi import APIRouter

from app.core.safety import safety_controller
from app.api.routes.safety import rearm as safety_rearm
from app.models.safety import SafetyRearmRequest, SafetyRearmResponse

router = APIRouter(prefix="/api/emergency-stop", tags=["emergency-stop"])


@router.post("")
def emergency_stop() -> dict[str, object]:
    record = safety_controller.stop(reason="Operator pressed emergency stop.", source="operator")
    snapshot = safety_controller.snapshot()

    return {
        "ok": record.ok,
        "state": snapshot["state"],
        "message": "Emergency stop signal sent.",
        "requires_confirmation": snapshot["requires_confirmation"],
        # Kept in the historical shape (`tool`/`tool_port`) so the existing
        # frontend result list keeps rendering.
        "results": [
            {
                "ok": report.ok,
                "tool": report.actor_id,
                "tool_port": report.detail.get("tool_port"),
                "message": report.message,
            }
            for report in record.reports
        ],
    }


@router.post("/rearm", response_model=SafetyRearmResponse)
def rearm() -> SafetyRearmResponse:
    return safety_rearm(SafetyRearmRequest())
