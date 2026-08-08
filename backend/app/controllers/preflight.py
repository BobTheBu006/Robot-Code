"""Ask each controller who it is before trusting it with a run.

This replaces "flash every board before every workflow" with "verify, and flash
only what is actually wrong". It also closes the failure that made flashing
unpredictable: a board whose reported identity does not match the one the
Hardware Map expects is now a hard error, where before an unresolvable board id
was quietly downgraded to a warning and the run continued against whatever
firmware happened to be on it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum

from app.controllers.fingerprint import ControllerIdentity, FirmwareBundle
from app.controllers.transport import TransportError, open_transport

IDENTITY_COMMAND = "ID?"
DEFAULT_IDENTITY_TIMEOUT_SECONDS = 3.0


class PreflightVerdict(str, Enum):
    OK = "ok"
    """Right board, right firmware. Nothing to do."""

    NEEDS_FLASH = "needs_flash"
    """Right board (or one that cannot say), but not the expected firmware."""

    WRONG_CONTROLLER = "wrong_controller"
    """The board on this port says it is something else. Never auto-flash."""

    NOT_CONNECTED = "not_connected"
    """No port carries the expected USB serial number."""

    UNRESPONSIVE = "unresponsive"
    """The port exists but nothing answered."""

    @property
    def blocks_run(self) -> bool:
        return self in {PreflightVerdict.WRONG_CONTROLLER, PreflightVerdict.NOT_CONNECTED}


@dataclass
class ControllerPreflightResult:
    controller_id: str
    verdict: PreflightVerdict
    message: str
    port: str | None = None
    expected_fingerprint: str | None = None
    reported_fingerprint: str | None = None
    reported_controller_id: str | None = None
    missing_routines: list[str] = field(default_factory=list)

    @property
    def needs_flash(self) -> bool:
        return self.verdict is PreflightVerdict.NEEDS_FLASH

    @property
    def ok(self) -> bool:
        return self.verdict is PreflightVerdict.OK


def probe_identity(
    port: str,
    *,
    timeout_seconds: float = DEFAULT_IDENTITY_TIMEOUT_SECONDS,
) -> tuple[ControllerIdentity | None, str | None]:
    """Open a port, ask `ID?`, and close it again.

    Returns (identity, error). A board running pre-handshake firmware returns
    (None, None): it answered something, just not an identity.
    """
    transport = open_transport(port)
    try:
        transport.open()
    except TransportError as exc:
        return None, str(exc)

    try:
        reply = transport.ask(IDENTITY_COMMAND, timeout_seconds=timeout_seconds)
    except TransportError as exc:
        return None, str(exc)
    finally:
        transport.close()

    if reply is None:
        return None, "no reply"

    return ControllerIdentity.parse(reply), None


def preflight_controller(
    *,
    controller_id: str,
    expected: FirmwareBundle,
    port: str | None,
    timeout_seconds: float = DEFAULT_IDENTITY_TIMEOUT_SECONDS,
) -> ControllerPreflightResult:
    """Decide what, if anything, must happen to this controller before a run."""
    expected_fingerprint = expected.fingerprint()

    if not port:
        return ControllerPreflightResult(
            controller_id=controller_id,
            verdict=PreflightVerdict.NOT_CONNECTED,
            message=(
                f"Controller '{controller_id}' is not connected. It is identified by its USB "
                "serial number, so it can be on any port - plug it in and try again."
            ),
            expected_fingerprint=expected_fingerprint,
        )

    identity, error = probe_identity(port, timeout_seconds=timeout_seconds)

    if identity is None:
        if error == "no reply":
            return ControllerPreflightResult(
                controller_id=controller_id,
                verdict=PreflightVerdict.UNRESPONSIVE,
                message=(
                    f"Controller '{controller_id}' on {port} did not answer {IDENTITY_COMMAND}. "
                    "It will be reflashed, which also recovers a board stuck in a bad state."
                ),
                port=port,
                expected_fingerprint=expected_fingerprint,
            )

        if error:
            return ControllerPreflightResult(
                controller_id=controller_id,
                verdict=PreflightVerdict.UNRESPONSIVE,
                message=f"Controller '{controller_id}' on {port} could not be reached: {error}",
                port=port,
                expected_fingerprint=expected_fingerprint,
            )

        # Answered, but with no identity: firmware predating the handshake.
        # Every board looks like this until it is reflashed once.
        return ControllerPreflightResult(
            controller_id=controller_id,
            verdict=PreflightVerdict.NEEDS_FLASH,
            message=(
                f"Controller '{controller_id}' on {port} is running firmware that predates the "
                "identity handshake, so it cannot be verified. It will be flashed once."
            ),
            port=port,
            expected_fingerprint=expected_fingerprint,
        )

    # A board that names a different controller is the wrong physical board on
    # this port. Flashing it would overwrite an unrelated controller's firmware,
    # which is exactly the accident the old port-derived board ids allowed.
    if identity.controller_id and identity.controller_id != controller_id:
        return ControllerPreflightResult(
            controller_id=controller_id,
            verdict=PreflightVerdict.WRONG_CONTROLLER,
            message=(
                f"The board on {port} reports it is '{identity.controller_id}', but the Hardware Map "
                f"expects '{controller_id}' there. Refusing to flash it. Check which board is "
                "plugged in, or fix the USB serial number recorded for these controllers."
            ),
            port=port,
            expected_fingerprint=expected_fingerprint,
            reported_fingerprint=identity.fingerprint,
            reported_controller_id=identity.controller_id,
        )

    missing_routines = sorted(set(expected.routines) - set(identity.routines))

    if identity.fingerprint == expected_fingerprint and not missing_routines:
        return ControllerPreflightResult(
            controller_id=controller_id,
            verdict=PreflightVerdict.OK,
            message=f"Controller '{controller_id}' on {port} already runs the expected firmware.",
            port=port,
            expected_fingerprint=expected_fingerprint,
            reported_fingerprint=identity.fingerprint,
            reported_controller_id=identity.controller_id,
        )

    if missing_routines:
        detail = f"it is missing routine(s): {', '.join(missing_routines)}"
    else:
        detail = f"its firmware fingerprint is {identity.fingerprint or 'unknown'}"

    return ControllerPreflightResult(
        controller_id=controller_id,
        verdict=PreflightVerdict.NEEDS_FLASH,
        message=(
            f"Controller '{controller_id}' on {port} needs reflashing: {detail}, "
            f"expected {expected_fingerprint}."
        ),
        port=port,
        expected_fingerprint=expected_fingerprint,
        reported_fingerprint=identity.fingerprint,
        reported_controller_id=identity.controller_id,
        missing_routines=missing_routines,
    )


@dataclass
class PreflightReport:
    results: list[ControllerPreflightResult] = field(default_factory=list)

    @property
    def blocking_errors(self) -> list[ControllerPreflightResult]:
        return [result for result in self.results if result.verdict.blocks_run]

    @property
    def controllers_to_flash(self) -> list[str]:
        return [result.controller_id for result in self.results if result.needs_flash]

    @property
    def ok(self) -> bool:
        return not self.blocking_errors

    def summary(self) -> str:
        if self.blocking_errors:
            return " ".join(result.message for result in self.blocking_errors)
        if self.controllers_to_flash:
            return f"{len(self.controllers_to_flash)} controller(s) need flashing before this run."
        return "All controllers already run the expected firmware."
