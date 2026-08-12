"""Run the five peristaltic pumps on the Z/pump ESP32.

These share a board, a serial port and a driver-enable line with the Z axes, so
this deliberately does not open its own connection - it borrows the Z service's,
which already owns the port and the reset/handshake/drain dance. Two services
opening /dev/ttyUSB0 would fight and neither would work.

Volume is the unit an operator thinks in, so requests are in millilitres and are
converted to steps here using each pump's calibration. Peristaltic output
depends on tubing bore and how compressed the tube is, so that figure has to be
measured per pump rather than derived - the Hardware Map holds it as
`calibration_ml_per_200_steps`.
"""

from __future__ import annotations

from dataclasses import dataclass

from app.services.hybrid_z_axis import hybrid_z_axis_service
from app.services.motor_power import Z_PUMP_DOMAIN, motor_power_service

PUMP_COUNT = 5
DEFAULT_ML_PER_200_STEPS = 1.0


class PeristalticPumpError(RuntimeError):
    """The pumps could not be driven."""


@dataclass
class PumpCommand:
    index: int          # 0-based
    steps: int          # signed: positive dispenses, negative draws back
    speed_rpm: int


def steps_for_volume(volume_ml: float, ml_per_200_steps: float) -> int:
    """Convert a volume to motor steps for one pump.

    Guards a zero or missing calibration rather than dividing by it: an
    uncalibrated pump asked for 5 mL would otherwise raise, or worse, run a
    nonsense number of steps into the tubing.
    """
    calibration = float(ml_per_200_steps or 0.0)
    if calibration <= 0:
        raise PeristalticPumpError(
            "This pump has no volume calibration yet. Set 'mL per 200 steps' for it in the "
            "Hardware Map - dispense into a scale and divide."
        )
    return int(round((float(volume_ml) / calibration) * 200.0))


class PeristalticPumpService:
    def run(
        self,
        context: dict,
        commands: list[PumpCommand],
        *,
        dir_pins: list[int],
        step_pins: list[int],
        enable_pin: int,
        tool_port: str | None = None,
    ) -> dict:
        """Run any subset of pumps at once, each at its own speed."""
        if len(dir_pins) != PUMP_COUNT or len(step_pins) != PUMP_COUNT:
            raise PeristalticPumpError(
                f"Expected {PUMP_COUNT} pump direction and step pins; "
                f"got {len(dir_pins)} and {len(step_pins)}."
            )

        steps = [0] * PUMP_COUNT
        rpm = [60] * PUMP_COUNT
        for command in commands:
            if not 0 <= command.index < PUMP_COUNT:
                raise PeristalticPumpError(f"Pump {command.index + 1} does not exist.")
            steps[command.index] = int(command.steps)
            rpm[command.index] = max(1, int(command.speed_rpm))

        if not any(steps):
            return {"ok": True, "status": "completed", "steps_done": [0] * PUMP_COUNT,
                    "message": "No pump was asked to move."}

        service = hybrid_z_axis_service
        port = service._resolve_port(context, tool_port)

        # The enable line covers every driver on this board, so this is the
        # same power domain the Z axes use - registered by the service that
        # owns the serial port rather than duplicated here.
        if enable_pin >= 0:
            service.register_power_domain(port, enable_pin)

        # Acquire pays the settle delay only if the drivers were actually off,
        # and release just starts the linger timer, so a workflow that pumps in
        # several consecutive blocks keeps them powered throughout.
        motor_power_service.acquire(Z_PUMP_DOMAIN)
        try:
            with service._lock:
                serial_port = service._open_serial(port, 115200)
                self._configure(serial_port, dir_pins, step_pins)
                return self._run(serial_port, steps, rpm)
        finally:
            motor_power_service.release(Z_PUMP_DOMAIN)

    # ---- serial ----

    def _configure(self, serial_port, dir_pins: list[int], step_pins: list[int]) -> None:
        pairs = " ".join(f"{dir_pins[i]} {step_pins[i]}" for i in range(PUMP_COUNT))
        reply, completed = hybrid_z_axis_service._send(
            serial_port, f"SET PUMP PINS {pairs}",
            terminal_prefixes=("OK", "ERR"), deadline_seconds=5.0,
        )
        if not completed or not reply or "OK" not in reply.upper():
            raise PeristalticPumpError(f"The controller did not accept the pump pins: {reply}")

    def _run(self, serial_port, steps: list[int], rpm: list[int]) -> dict:
        pairs = " ".join(f"{steps[i]} {rpm[i]}" for i in range(PUMP_COUNT))

        # Budget the wait on the slowest pump's own run time rather than a fixed
        # timeout: a slow 20 mL dispense legitimately takes minutes, and cutting
        # it off at an arbitrary deadline would abandon a move still in progress.
        seconds = 0.0
        for index in range(PUMP_COUNT):
            if steps[index]:
                revolutions = abs(steps[index]) / 800.0
                seconds = max(seconds, (revolutions / max(1, rpm[index])) * 60.0)
        deadline = max(15.0, seconds * 1.5 + 10.0)

        reply, completed = hybrid_z_axis_service._send(
            serial_port, f"PUMP RUN {pairs}",
            terminal_prefixes=("OK PUMP RUN", "OK STOP PUMP RUN", "ERR"), deadline_seconds=deadline,
        )
        if not completed or not reply:
            raise PeristalticPumpError(
                f"The pumps did not report finishing within {deadline:.0f}s. Last reply: {reply}"
            )
        upper = reply.upper()
        if "ERR" in upper:
            if "DISABLED" in upper:
                raise PeristalticPumpError(
                    "The controller refused to run: the driver enable line is off. "
                    "This usually means the firmware was reset after the enable was set."
                )
            raise PeristalticPumpError(f"The controller rejected the pump command: {reply}")

        done = self._parse_done(reply)
        stopped = "OK STOP" in upper
        return {
            "ok": not stopped,
            "status": "stopped" if stopped else "completed",
            "steps_done": done,
            "steps_requested": list(steps),
            "message": (
                "Pump run stopped early." if stopped
                else "Pumps finished."
            ),
        }

    def _parse_done(self, reply: str) -> list[int]:
        for line in reversed(reply.splitlines()):
            upper = line.upper()
            if "PUMP RUN" not in upper:
                continue
            tail = line.split("PUMP RUN", 1)[1].split()
            values = []
            for token in tail[:PUMP_COUNT]:
                try:
                    values.append(int(token))
                except ValueError:
                    break
            if len(values) == PUMP_COUNT:
                return values
        return [0] * PUMP_COUNT

peristaltic_pump_service = PeristalticPumpService()
