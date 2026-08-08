"""Fake controllers, sized for testing identity - not for pretending to move.

With no hardware on the bench there has to be *something* that answers `ID?`,
otherwise the preflight path below can only ever be tested against mocks of
itself. So a simulated controller implements the identity handshake honestly
and stubs everything else: it acknowledges motion commands without modelling
any motion. If a test needs to assert where the gantry ended up, that belongs
in the driver-level tests, which already simulate GPIO.

Enable with `ROBOT_SIMULATED_CONTROLLERS`, either inline JSON or a path to a
JSON file:

    [{"device": "SIM0", "serial_number": "SIM-0001",
      "controller_id": "controller-x83xnc", "fingerprint": "abc123",
      "routines": ["dispense", "prime"]}]

A spec with no `fingerprint` models a board whose firmware predates the
handshake, which is what every real board looks like before it is reflashed.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock

SIMULATION_ENV_VAR = "ROBOT_SIMULATED_CONTROLLERS"

# Bumped when the wire format of the ID? reply changes incompatibly.
IDENTITY_PROTOCOL_VERSION = 1

# What the current hand-written sketches answer to a command they do not know.
LEGACY_UNKNOWN_COMMAND_REPLY = "ERR UNKNOWN CMD"


@dataclass
class SimulatedControllerSpec:
    device: str
    serial_number: str
    controller_id: str | None = None
    fingerprint: str | None = None
    protocol: int = IDENTITY_PROTOCOL_VERSION
    routines: list[str] = field(default_factory=list)
    description: str = "Simulated ESP32"
    hardware_id: str | None = None
    # Models a board that is plugged in but wedged: it enumerates on USB and
    # never answers. Preflight must treat that as "cannot verify", not as
    # "verified".
    unresponsive: bool = False
    # Models firmware predating the handshake, which is what every real board
    # runs until it is reflashed once. Such a board does not answer ID? with a
    # null identity - it does not recognise the command at all.
    supports_identity: bool = True

    @classmethod
    def from_json(cls, payload: dict) -> "SimulatedControllerSpec":
        device = str(payload.get("device") or "").strip()
        if not device:
            raise ValueError("A simulated controller needs a 'device'.")

        serial_number = str(payload.get("serial_number") or f"SIM-{device}").strip()
        routines = payload.get("routines") or []
        return cls(
            device=device,
            serial_number=serial_number,
            controller_id=payload.get("controller_id"),
            fingerprint=payload.get("fingerprint"),
            protocol=int(payload.get("protocol") or IDENTITY_PROTOCOL_VERSION),
            routines=[str(routine) for routine in routines],
            description=str(payload.get("description") or "Simulated ESP32"),
            hardware_id=payload.get("hardware_id") or f"SIM:{serial_number}",
            unresponsive=bool(payload.get("unresponsive", False)),
            supports_identity=bool(payload.get("supports_identity", True)),
        )


class SimulatedFirmware:
    """The bit that actually answers on the wire."""

    def __init__(self, spec: SimulatedControllerSpec) -> None:
        self.spec = spec
        self.received: list[str] = []

    def respond(self, command: str) -> str | None:
        """One request line in, one reply line out. None means "said nothing"."""
        self.received.append(command)

        if self.spec.unresponsive:
            return None

        normalized = command.strip().upper()

        if normalized in {"ID?", "ID"}:
            if not self.spec.supports_identity:
                return LEGACY_UNKNOWN_COMMAND_REPLY

            return json.dumps(
                {
                    "controller_id": self.spec.controller_id,
                    "fingerprint": self.spec.fingerprint,
                    "protocol": self.spec.protocol,
                    "routines": sorted(self.spec.routines),
                },
                separators=(",", ":"),
                sort_keys=True,
            )

        if normalized == "PING":
            return "PONG"

        if normalized == "STOP":
            return "OK STOP"

        # Everything else is acknowledged without being modelled. This is the
        # deliberate limit of the simulation: it exists to exercise identity
        # and connectivity, not to stand in for the machine.
        return f"OK SIMULATED {normalized.split(' ')[0]}"


class SimulatedControllerRegistry:
    def __init__(self) -> None:
        self._lock = RLock()
        self._specs: dict[str, SimulatedControllerSpec] = {}
        self._firmware: dict[str, SimulatedFirmware] = {}
        self._loaded_from_env = False

    def _load_env_once(self) -> None:
        if self._loaded_from_env:
            return
        self._loaded_from_env = True

        raw = os.getenv(SIMULATION_ENV_VAR, "").strip()
        if not raw:
            return

        try:
            payload = json.loads(raw) if raw.startswith("[") else json.loads(Path(raw).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError, ValueError):
            # A malformed simulation config must not take the backend down;
            # the absence of simulated boards is visible enough on its own.
            return

        if not isinstance(payload, list):
            return

        for entry in payload:
            if isinstance(entry, dict):
                try:
                    self.register(SimulatedControllerSpec.from_json(entry))
                except ValueError:
                    continue

    def register(self, spec: SimulatedControllerSpec) -> SimulatedFirmware:
        with self._lock:
            self._specs[spec.device] = spec
            firmware = SimulatedFirmware(spec)
            self._firmware[spec.device] = firmware
            return firmware

    def clear(self) -> None:
        with self._lock:
            self._specs.clear()
            self._firmware.clear()
            self._loaded_from_env = False

    def reload_from_env(self) -> None:
        with self._lock:
            self._specs.clear()
            self._firmware.clear()
            self._loaded_from_env = False
            self._load_env_once()

    def specs(self) -> list[SimulatedControllerSpec]:
        with self._lock:
            self._load_env_once()
            return sorted(self._specs.values(), key=lambda spec: spec.device)

    def firmware_for(self, device: str) -> SimulatedFirmware | None:
        with self._lock:
            self._load_env_once()
            return self._firmware.get(device)

    def is_simulated(self, device: str) -> bool:
        return self.firmware_for(device) is not None

    def enabled(self) -> bool:
        return bool(self.specs())


simulated_controllers = SimulatedControllerRegistry()
