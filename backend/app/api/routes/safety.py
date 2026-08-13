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
from app.services.motor_power import Z_PUMP_DOMAIN, motor_power_service
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
    # The run is over, so there is no next block to keep the drivers warm for.
    # Cutting power here rather than waiting out the linger timer means the
    # motors are cold the moment a workflow finishes.
    motor_power_service.power_down_now()
    return {"ok": True, "watching": False, "motors": motor_power_service.snapshot()}


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


@router.get("/motor-power")
def get_motor_power() -> dict:
    """Which driver enable lines are powered right now."""
    return motor_power_service.snapshot()


@router.post("/motor-power/enable-test")
def motor_power_enable_test(domain: str = "z", seconds: float = 5.0) -> dict:
    """Assert a driver enable line, hold it, then drop it. Sends no steps.

    Diagnostic for exactly one question: does the enable line reach the
    drivers, the right way round? It drives the same line a real move drives,
    so a failure here is the failure a move would hit - but nothing turns, so
    it is safe to run with the machine powered and someone watching the motors.

    `domain` selects "z" (the Z/pump ESP32, GPIO 4, enabled high) or "gantry"
    (the CoreXY TB6600s on Pi GPIO, enabled LOW - energising a TB6600's opto
    disables it).
    """
    import time

    from app.services.hardware_map import hardware_map_service

    context = {"hardware_map": hardware_map_service.load_map().model_dump(mode="json")}
    steps: list[str] = []
    hold = max(0.0, min(float(seconds), 30.0))

    if domain == "gantry":
        from app.services.gpio_backend import load_gpio_backend
        from app.services.motor_power import GANTRY_XY_DOMAIN
        from app.services.raspberry_gantry import (
            _enable_pin_from_hardware_map,
            raspberry_gantry_gpio_service,
        )

        enable_pin = _enable_pin_from_hardware_map(context)
        if enable_pin is None:
            return {"ok": False, "error": "No CoreXY enable pin is recorded in the Hardware Map."}

        gpio, gpio_error = load_gpio_backend()
        if gpio is None:
            return {"ok": False, "error": f"No usable GPIO backend: {gpio_error}"}

        try:
            gpio.setwarnings(False)
            gpio.setmode(gpio.BCM)
            # Claim it already disabled, so this cannot energise the drivers
            # merely by taking the pin.
            raspberry_gantry_gpio_service._register_power_domain(gpio, enable_pin)
            domain_state = motor_power_service.snapshot()["domains"]
            active_low = next((d["active_low"] for d in domain_state if d["domain_id"] == GANTRY_XY_DOMAIN), None)
            gpio.setup(enable_pin, gpio.OUT, initial=gpio.HIGH if active_low else gpio.LOW)
            steps.append(
                f"claimed Pi GPIO {enable_pin} as an output, disabled "
                f"({'HIGH' if active_low else 'LOW'} = off for these drivers)"
            )

            motor_power_service.acquire(GANTRY_XY_DOMAIN)
            steps.append(
                f"enabled - GPIO {enable_pin} driven {'LOW' if active_low else 'HIGH'}; "
                "the CoreXY motors should be holding now"
            )
            time.sleep(hold)

            motor_power_service.power_down_now(GANTRY_XY_DOMAIN)
            steps.append("disabled - the motors should be free to turn by hand again")
            return {"ok": True, "domain": "gantry", "enable_pin": enable_pin,
                    "active_low": active_low, "steps": steps}
        except Exception as exc:
            motor_power_service.power_down_now(GANTRY_XY_DOMAIN)
            return {"ok": False, "domain": "gantry", "enable_pin": enable_pin,
                    "steps": steps, "error": f"{type(exc).__name__}: {exc}"}

    from app.services.hybrid_z_axis import hybrid_z_axis_service

    enable_pin = hybrid_z_axis_service.enable_pin_from_hardware_map(context)
    if enable_pin is None:
        return {"ok": False, "error": "No enable pin is recorded for this board in the Hardware Map."}

    try:
        port = hybrid_z_axis_service._resolve_port(context, None)
    except Exception as exc:
        return {"ok": False, "error": f"Could not resolve the controller port: {exc}"}

    try:
        hybrid_z_axis_service.register_power_domain(port, enable_pin)
        steps.append(f"registered enable on GPIO {enable_pin} via {port}")

        motor_power_service.acquire(Z_PUMP_DOMAIN)
        steps.append(f"MOTOR ENABLE 1 acknowledged - GPIO {enable_pin} should now read HIGH")

        time.sleep(hold)

        motor_power_service.power_down_now(Z_PUMP_DOMAIN)
        steps.append(f"MOTOR ENABLE 0 acknowledged - GPIO {enable_pin} back LOW")
        return {"ok": True, "domain": "z", "enable_pin": enable_pin, "port": port, "steps": steps}
    except Exception as exc:
        motor_power_service.power_down_now(Z_PUMP_DOMAIN)
        return {"ok": False, "domain": "z", "enable_pin": enable_pin, "port": port,
                "steps": steps, "error": f"{type(exc).__name__}: {exc}"}
