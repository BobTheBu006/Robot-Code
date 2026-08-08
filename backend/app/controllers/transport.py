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

    def open(self) -> None:
        try:
            import serial  # type: ignore
        except ImportError as exc:  # pragma: no cover - depends on host install
            raise TransportError(f"pyserial is not available: {exc}") from exc

        try:
            self._port = serial.Serial(self.device, self._baud_rate, timeout=1)
        except Exception as exc:
            raise TransportError(f"Could not open '{self.device}': {exc}") from exc

        # ESP32 boards reset when the port opens (DTR/RTS toggling), so the
        # first thing on the wire is boot chatter. Give it a moment, then throw
        # away whatever is buffered rather than parsing it as a reply.
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

        return None


def open_transport(device: str, *, baud_rate: int = 115200) -> ControllerTransport:
    """Pick the right transport for a device, preferring a simulated one."""
    if simulated_controllers.is_simulated(device):
        return SimulatedTransport(device)
    return SerialTransport(device, baud_rate=baud_rate)
