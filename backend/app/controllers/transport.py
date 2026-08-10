"""One way to talk to a controller, whether it is real or simulated.

The existing drivers each open pyserial directly, which is fine for motion but
leaves no seam for testing the identity handshake. This is that seam: a
line-oriented request/reply channel with exactly two implementations.
"""

from __future__ import annotations

import time
from typing import Protocol

from app.controllers.simulation import simulated_controllers


class TransportError(RuntimeError):
    pass


class ControllerTransport(Protocol):
    device: str

    def open(self) -> None: ...
    def close(self) -> None: ...
    def ask(self, command: str, *, timeout_seconds: float) -> str | None:
        """Send one line, return the first reply line, or None on timeout."""


class SimulatedTransport:
    def __init__(self, device: str) -> None:
        self.device = device
        self._firmware = simulated_controllers.firmware_for(device)
        if self._firmware is None:
            raise TransportError(f"No simulated controller is registered on '{device}'.")

    def open(self) -> None:
        return None

    def close(self) -> None:
        return None

    def ask(self, command: str, *, timeout_seconds: float) -> str | None:
        assert self._firmware is not None
        return self._firmware.respond(command)


class SerialTransport:
    """Short-lived pyserial connection used only for the identity handshake.

    Deliberately separate from the long-lived motion connections in
    gantry_controller/syringe_controller: preflight runs before those exist,
    and reusing them would mean reopening a port mid-run.
    """

    def __init__(self, device: str, *, baud_rate: int = 115200) -> None:
        self.device = device
        self._baud_rate = baud_rate
        self._port = None
        self._retried_after_reset = False

    def open(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on host install
            raise TransportError(f"pyserial is not available: {exc}") from exc

        # Open WITHOUT asserting DTR/RTS. On these boards EN is driven from
        # those lines, so a normal open resets the ESP32 and forces a ~2s wait
        # for it to boot before it can answer - paid on every handshake, for
        # every board, on every run. Firmware that is already running answers
        # immediately, so the reset is pure cost in the common case.
        try:
            port = serial.Serial()
            port.port = self.device
            port.baudrate = self._baud_rate
            port.timeout = 1
            port.dtr = False
            port.rts = False
            port.open()
            self._port = port
        except Exception:
            # Some adapters refuse the staged open; fall back to the plain one,
            # which resets the board and therefore has to wait it out.
            try:
                self._port = serial.Serial(self.device, self._baud_rate, timeout=1)
            except Exception as exc:
                raise TransportError(f"Could not open '{self.device}': {exc}") from exc
            self._settle_after_reset()
            return

        # Discard anything already in flight before asking a question. A fixed
        # short sleep is not enough: if this adapter does reset the board after
        # all, its boot banner is still streaming and the first line read back
        # ("OK XY PINS ...") gets parsed as the answer, which reads as "no
        # identity" and reflashes a perfectly good controller. Draining until
        # the line goes quiet costs nothing when the board is idle and waits
        # out a boot when it is not.
        self._drain_until_quiet()

    def _drain_until_quiet(self, *, quiet_seconds: float = 0.25, max_seconds: float = 3.5) -> None:
        deadline = time.monotonic() + max_seconds
        last_data_at = time.monotonic()
        while time.monotonic() < deadline:
            try:
                waiting = self._port.in_waiting
                if waiting:
                    self._port.read(waiting)
                    last_data_at = time.monotonic()
                    continue
            except Exception:
                break
            if time.monotonic() - last_data_at >= quiet_seconds:
                break
            time.sleep(0.02)
        try:
            self._port.reset_input_buffer()
        except Exception:
            pass

    def _settle_after_reset(self) -> None:
        """Wait out an ESP32 boot and discard its chatter."""
        time.sleep(2.0)
        try:
            self._port.reset_input_buffer()
        except Exception:
            pass

    def close(self) -> None:
        if self._port is None:
            return
        try:
            self._port.close()
        except Exception:
            pass
        self._port = None

    def ask(self, command: str, *, timeout_seconds: float) -> str | None:
        if self._port is None:
            raise TransportError(f"'{self.device}' is not open.")

        try:
            self._port.reset_input_buffer()
            self._port.write(f"{command}\n".encode("utf-8"))
            self._port.flush()
        except Exception as exc:
            raise TransportError(f"Could not write to '{self.device}': {exc}") from exc

        deadline = time.perf_counter() + timeout_seconds
        while time.perf_counter() < deadline:
            try:
                raw = self._port.readline()
            except Exception as exc:
                raise TransportError(f"Could not read from '{self.device}': {exc}") from exc

            line = raw.decode("utf-8", errors="replace").strip()
            if line:
                return line

        # Silence can mean the board really was reset by this open (adapter
        # dependent) and is still booting. Wait it out once and re-ask, so
        # skipping the reset never turns a live board into "unresponsive".
        if not self._retried_after_reset:
            self._retried_after_reset = True
            self._settle_after_reset()
            return self.ask(command, timeout_seconds=timeout_seconds)

        return None


def open_transport(device: str, *, baud_rate: int = 115200) -> ControllerTransport:
    """Pick the right transport for a device, preferring a simulated one."""
    if simulated_controllers.is_simulated(device):
        return SimulatedTransport(device)
    return SerialTransport(device, baud_rate=baud_rate)
