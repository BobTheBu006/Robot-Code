"""The dynamic pogo-pin connector: which tool is on the far side of it.

The toolhead carries a spring-pin connector with four Pi GPIOs (SDA, SCL, TXD,
RXD) and one USB port. What those contacts mean depends on the tool docked
there, so the Hardware Map describes each tool as a *group* attached to the
connector, and exactly one group - or none - is active at a time.

Activating a group does three things, in this order:

1. **Verify** the tool, where that is possible. An ESP32 on the USB answers the
   identity query; a USB device reports its serial; a tool that shorts TXD to
   RXD echoes a pattern driven out on TXD. A dumb tool cannot be checked at
   all, and the result says so rather than reporting a pass.
2. **Configure the pins** for that tool: I2C and UART hand the pin to the Pi
   peripheral, GPIO and unused leave it an input. Only after verification, so
   a wrong tool never has its pins reconfigured under it.
3. **Record** the tool as active. Hardware in every other group on the
   connector is then unavailable to workflow functions, with a reason naming
   the tool that is not docked. That is how the function map follows the tool.

A failed verification parks every pin and leaves the connector empty. It never
leaves the previous tool recorded as present.
"""

from __future__ import annotations

import json
import os
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path
from threading import RLock
from typing import Any, Protocol

from app.models.hardware_map import (
    HardwareConnectorMapping,
    HardwareGroupMapping,
    HardwareMap,
    connector_pin_modes,
)

_REPO_ROOT = Path(__file__).resolve().parents[3]

# Long enough for an ESP32 to boot and enumerate after its pogo pins make
# contact. Measured nowhere yet - revisit once a tool is docked for real.
DEFAULT_USB_SETTLE_SECONDS = 8.0
USB_POLL_INTERVAL_SECONDS = 0.5

# Time for a driven level to reach the other pin through the tool's short.
LOOPBACK_SETTLE_SECONDS = 0.002


class ConnectorError(RuntimeError):
    pass


# ---- pins ---------------------------------------------------------------


class PinDriver(Protocol):
    def park(self, gpio: str) -> None:
        """High-impedance input, no pull."""

    def set_alt(self, gpio: str, alt_function: str) -> None:
        """Route the pin to a peripheral."""

    def drive(self, gpio: str, level: int) -> None:
        """Output at a level."""

    def input(self, gpio: str, pull: str) -> None:
        """Input with pull "up", "down" or "none"."""

    def level(self, gpio: str) -> int: ...


_PULL_ARGS = {"up": "pu", "down": "pd", "none": "pn"}


class PinctrlDriver:
    """Pin functions through `pinctrl`, which can select alternate functions -
    the thing RPi.GPIO and lgpio cannot do."""

    def _run(self, *args: str) -> str:
        try:
            completed = subprocess.run(
                ["pinctrl", *args], check=True, capture_output=True, text=True, timeout=5
            )
        except (OSError, subprocess.SubprocessError) as exc:
            raise ConnectorError(f"pinctrl {' '.join(args)} failed: {exc}") from exc
        return completed.stdout

    def park(self, gpio: str) -> None:
        self._run("set", gpio, "ip", "pn")

    def set_alt(self, gpio: str, alt_function: str) -> None:
        self._run("set", gpio, alt_function)

    def drive(self, gpio: str, level: int) -> None:
        self._run("set", gpio, "op", "dh" if level else "dl")

    def input(self, gpio: str, pull: str) -> None:
        self._run("set", gpio, "ip", _PULL_ARGS[pull])

    def level(self, gpio: str) -> int:
        return 1 if self._run("lev", gpio).strip() == "1" else 0


@dataclass
class SimulatedPinDriver:
    """In-memory pins. `shorted` pairs model a tool that bridges two contacts."""

    shorted: set[frozenset[str]] = field(default_factory=set)
    state: dict[str, tuple[str, Any]] = field(default_factory=dict)

    def park(self, gpio: str) -> None:
        self.state[gpio] = ("input", "none")

    def set_alt(self, gpio: str, alt_function: str) -> None:
        self.state[gpio] = ("alt", alt_function)

    def drive(self, gpio: str, level: int) -> None:
        self.state[gpio] = ("output", 1 if level else 0)

    def input(self, gpio: str, pull: str) -> None:
        self.state[gpio] = ("input", pull)

    def level(self, gpio: str) -> int:
        mode, value = self.state.get(gpio, ("input", "none"))
        if mode == "output":
            return value
        for pair in self.shorted:
            if gpio in pair:
                other = next(iter(pair - {gpio}))
                other_mode, other_value = self.state.get(other, ("input", "none"))
                if other_mode == "output":
                    return other_value
        return 1 if value == "up" else 0


def _simulating() -> bool:
    return os.getenv("ROBOT_GPIO_SIMULATE", "").strip().lower() in {"1", "true", "yes", "on"}


# ---- state --------------------------------------------------------------


def _default_state_path() -> Path:
    override = os.getenv("ROBOT_CONNECTOR_STATE_FILE")
    return Path(override) if override else _REPO_ROOT / "connector-state.json"


class ConnectorStateStore:
    """Which group is active on each connector, persisted across restarts."""

    def __init__(self, state_path: Path | None = None) -> None:
        # Resolved on every access unless given, so a test that sets
        # ROBOT_CONNECTOR_STATE_FILE never writes into the repository.
        self._explicit_path = state_path
        self._lock = RLock()

    @property
    def _state_path(self) -> Path:
        return self._explicit_path if self._explicit_path is not None else _default_state_path()

    def read(self) -> dict[str, dict[str, Any]]:
        with self._lock:
            if not self._state_path.exists():
                return {}
            try:
                payload = json.loads(self._state_path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                return {}
            return payload if isinstance(payload, dict) else {}

    def set(self, connector_id: str, record: dict[str, Any] | None) -> None:
        with self._lock:
            state = self.read()
            if record is None:
                state.pop(connector_id, None)
            else:
                state[connector_id] = record
            self._state_path.parent.mkdir(parents=True, exist_ok=True)
            self._state_path.write_text(json.dumps(state, indent=2) + "\n", encoding="utf-8")

    def active_group_id(self, connector_id: str) -> str | None:
        record = self.read().get(connector_id)
        return record.get("group_id") if record else None

    def active_group_ids(self) -> set[str]:
        return {record["group_id"] for record in self.read().values() if record.get("group_id")}


# ---- service ------------------------------------------------------------


@dataclass
class ConnectorResult:
    connector_id: str
    group_id: str | None
    group_name: str | None
    verification: str
    verified: bool
    message: str
    warnings: list[str] = field(default_factory=list)
    pin_modes: dict[str, str] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "connector_id": self.connector_id,
            "group_id": self.group_id,
            "group_name": self.group_name,
            "verification": self.verification,
            "verified": self.verified,
            "message": self.message,
            "warnings": list(self.warnings),
            "pin_modes": dict(self.pin_modes),
        }


class PogoConnectorService:
    def __init__(
        self,
        *,
        state_store: ConnectorStateStore | None = None,
        pin_driver: PinDriver | None = None,
        load_map=None,
        usb_settle_seconds: float = DEFAULT_USB_SETTLE_SECONDS,
    ) -> None:
        self._state_store = state_store or connector_state_store
        self._pin_driver = pin_driver
        self._load_map = load_map
        self._usb_settle_seconds = usb_settle_seconds
        self._lock = RLock()

    # -- collaborators, resolved late so tests and the simulate flag apply --

    def _pins(self) -> PinDriver:
        if self._pin_driver is None:
            # Simulated pins model a docked loopback tool, so simulated runs of
            # a loopback-verified tool pass; the result still says "simulated".
            self._pin_driver = (
                SimulatedPinDriver(shorted={frozenset({"14", "15"})}) if _simulating() else PinctrlDriver()
            )
        return self._pin_driver

    def _map(self) -> HardwareMap:
        if self._load_map is not None:
            return self._load_map()
        from app.services.hardware_map import hardware_map_service

        return hardware_map_service.load_map()

    # -- lookups --

    def connector_groups(self, hardware_map: HardwareMap, connector_id: str | None = None) -> list[HardwareGroupMapping]:
        return [
            group
            for group in hardware_map.groups
            if group.connector_id and (connector_id is None or group.connector_id == connector_id)
        ]

    def _connector(self, hardware_map: HardwareMap, connector_id: str) -> HardwareConnectorMapping:
        connector = next((c for c in hardware_map.connectors if c.id == connector_id), None)
        if connector is None:
            raise ConnectorError(f"Unknown connector '{connector_id}' in the Hardware Map.")
        return connector

    def status(self) -> list[dict[str, Any]]:
        hardware_map = self._map()
        state = self._state_store.read()
        statuses = []
        for connector in hardware_map.connectors:
            record = state.get(connector.id) or {}
            statuses.append(
                {
                    "connector_id": connector.id,
                    "label": connector.label,
                    "active_group_id": record.get("group_id"),
                    "active_group_name": record.get("group_name"),
                    "verified": record.get("verified", False),
                    "message": record.get("message") or f"{connector.label} is empty.",
                    "groups": [
                        {"id": group.id, "name": group.name, "toolhead_index": group.toolhead_index}
                        for group in self.connector_groups(hardware_map, connector.id)
                    ],
                }
            )
        return statuses

    # -- the operations blocks call --

    def activate(self, group_id: str) -> ConnectorResult:
        """Verify, configure and record a tool. Raises if it fails verification."""
        with self._lock:
            hardware_map = self._map()
            group = next((g for g in hardware_map.groups if g.id == group_id), None)
            if group is None:
                raise ConnectorError(f"Unknown tool group '{group_id}' in the Hardware Map.")
            if not group.connector_id:
                raise ConnectorError(f"Group '{group.name}' is not attached to a connector.")
            connector = self._connector(hardware_map, group.connector_id)
            if not connector.enabled:
                raise ConnectorError(f"{connector.label} is disabled in the Hardware Map.")
            if not group.enabled:
                raise ConnectorError(f"Tool '{group.name}' is disabled in the Hardware Map.")

            # Forget the previous tool before touching anything, so a failure
            # below can never leave it recorded as still docked.
            self._park_all(connector)
            self._state_store.set(connector.id, None)

            try:
                verified, message, warnings = self._verify(hardware_map, connector, group)
                self._apply_pin_modes(hardware_map, connector, group)
            except Exception as exc:
                self._park_all(connector)
                failure = f"Could not connect tool '{group.name}' on {connector.label}: {exc}"
                # Empty, but remember why, so the UI can say more than "empty".
                self._state_store.set(
                    connector.id,
                    {"group_id": None, "verified": False, "message": failure, "updated_at": time.time()},
                )
                raise ConnectorError(failure) from exc

            result = ConnectorResult(
                connector_id=connector.id,
                group_id=group.id,
                group_name=group.name,
                verification=group.verification,
                verified=verified,
                message=message,
                warnings=warnings,
                pin_modes=self._effective_pin_modes(hardware_map, connector, group),
            )
            self._state_store.set(
                connector.id,
                {
                    "group_id": group.id,
                    "group_name": group.name,
                    "verified": verified,
                    "verification": group.verification,
                    "message": message,
                    "updated_at": time.time(),
                },
            )
            return result

    def deactivate(self, connector_id: str | None = None) -> list[ConnectorResult]:
        """Park the pins and record the connector as empty."""
        with self._lock:
            hardware_map = self._map()
            connectors = (
                hardware_map.connectors
                if connector_id is None
                else [self._connector(hardware_map, connector_id)]
            )
            results = []
            for connector in connectors:
                self._park_all(connector)
                self._state_store.set(connector.id, None)
                results.append(
                    ConnectorResult(
                        connector_id=connector.id,
                        group_id=None,
                        group_name=None,
                        verification="none",
                        verified=False,
                        message=f"{connector.label} is empty; all pins parked as inputs.",
                    )
                )
            return results

    def connect_for_toolhead(self, toolhead_index: int, *, reverify: bool = True) -> list[ConnectorResult]:
        """After a pick-up: activate the slot's tool on each connector, or
        leave the connector empty when the tool has no electrical connection.

        With reverify=False a tool already recorded as active is left alone,
        for the case where the pick-up found the tool already held.
        """
        with self._lock:
            hardware_map = self._map()
            results = []
            for connector in hardware_map.connectors:
                if not connector.enabled:
                    continue
                group = next(
                    (
                        g
                        for g in self.connector_groups(hardware_map, connector.id)
                        if g.toolhead_index == toolhead_index
                    ),
                    None,
                )
                if group is None:
                    results.extend(self.deactivate(connector.id))
                    continue
                if not reverify and self._state_store.active_group_id(connector.id) == group.id:
                    record = self._state_store.read().get(connector.id) or {}
                    results.append(
                        ConnectorResult(
                            connector_id=connector.id,
                            group_id=group.id,
                            group_name=group.name,
                            verification=group.verification,
                            verified=bool(record.get("verified")),
                            message=record.get("message") or f"Tool '{group.name}' is already connected.",
                            pin_modes=self._effective_pin_modes(hardware_map, connector, group),
                        )
                    )
                    continue
                results.append(self.activate(group.id))
            return results

    def contact_check_blocker(self, toolhead_index: int) -> str | None:
        """Why a TXD-RXD contact check cannot work for this slot, or None.

        Asked before any motion, so a check that could never pass is refused
        up front rather than after the head has been driven into the rack.
        """
        hardware_map = self._map()
        connector = self._contact_connector(hardware_map)
        if connector is None:
            return "No enabled connector has a TXD/RXD pair to check contact on."
        group = next(
            (g for g in self.connector_groups(hardware_map, connector.id) if g.toolhead_index == toolhead_index),
            None,
        )
        if group is None:
            return None
        modes = connector_pin_modes(hardware_map, group)
        busy = [
            pin.name
            for pin in connector.pins
            if pin.peripheral == "uart" and modes.get(pin.name, "unused") != "unused"
        ]
        if busy:
            return (
                f"Tool '{group.name}' in slot {toolhead_index} uses {', '.join(busy)}, so they are not "
                "shorted and a contact check would always fail. Turn the check off for this slot."
            )
        return None

    def check_contact(self) -> tuple[bool, str]:
        """Are TXD and RXD shorted right now? Never raises for a plain miss:
        the pick-up decides whether to retry."""
        with self._lock:
            connector = self._contact_connector(self._map())
            if connector is None:
                return False, "No enabled connector has a TXD/RXD pair to check contact on."
            try:
                self._verify_loopback(connector)
            except ConnectorError as exc:
                return False, str(exc)
            suffix = " (simulated)" if _simulating() else ""
            return True, f"TXD-RXD contact confirmed on {connector.label}{suffix}."

    def sync_to_held_tool(self, toolhead_index: int | None) -> list[ConnectorResult]:
        """Follow an operator's answer to "which tool is on the head?".

        The answer is the truth about the head, so a connector check that
        fails here is reported rather than raised: the connector is left
        empty, and the failure is recorded for the UI to show.
        """
        if toolhead_index is None:
            return self.deactivate()
        try:
            return self.connect_for_toolhead(toolhead_index)
        except ConnectorError as exc:
            return [
                ConnectorResult(
                    connector_id="",
                    group_id=None,
                    group_name=None,
                    verification="none",
                    verified=False,
                    message=str(exc),
                )
            ]

    # -- internals --

    def _contact_connector(self, hardware_map: HardwareMap) -> HardwareConnectorMapping | None:
        return next(
            (
                connector
                for connector in hardware_map.connectors
                if connector.enabled and sum(1 for pin in connector.pins if pin.peripheral == "uart") == 2
            ),
            None,
        )

    def _park_all(self, connector: HardwareConnectorMapping) -> None:
        pins = self._pins()
        for pin in connector.pins:
            pins.park(pin.gpio)

    def _effective_pin_modes(
        self, hardware_map: HardwareMap, connector: HardwareConnectorMapping, group: HardwareGroupMapping
    ) -> dict[str, str]:
        modes = connector_pin_modes(hardware_map, group)
        return {pin.name: modes.get(pin.name, "unused") for pin in connector.pins}

    def _apply_pin_modes(
        self, hardware_map: HardwareMap, connector: HardwareConnectorMapping, group: HardwareGroupMapping
    ) -> None:
        pins = self._pins()
        modes = self._effective_pin_modes(hardware_map, connector, group)
        for pin in connector.pins:
            mode = modes[pin.name]
            if mode in {"i2c", "uart"}:
                if not pin.alt_function:
                    raise ConnectorError(f"{connector.label} pin {pin.name} has no alternate function recorded for {mode}.")
                pins.set_alt(pin.gpio, pin.alt_function)
            else:
                # GPIO pins are left as inputs for the tool's functions to
                # claim; nothing is driven until a block asks for it.
                pins.park(pin.gpio)

    def _verify(
        self,
        hardware_map: HardwareMap,
        connector: HardwareConnectorMapping,
        group: HardwareGroupMapping,
    ) -> tuple[bool, str, list[str]]:
        suffix = " (simulated)" if _simulating() else ""
        if group.verification == "loopback":
            self._verify_loopback(connector)
            return True, f"Tool '{group.name}' confirmed by its TXD-RXD loopback{suffix}.", []
        if group.verification == "fingerprint":
            message = self._verify_fingerprint(group)
            return True, message + suffix, []
        if group.verification == "usb_serial":
            message = self._verify_usb_serial(group)
            return True, message + suffix, []

        warning = (
            f"Tool '{group.name}' has no way to be verified; it is assumed to be docked. "
            "Nothing checked that it is really there."
        )
        return False, f"Tool '{group.name}' connected (not verified).", [warning]

    def _verify_loopback(self, connector: HardwareConnectorMapping) -> None:
        uart = [pin for pin in connector.pins if pin.peripheral == "uart"]
        tx = next((pin for pin in uart if pin.name.upper().startswith("T")), None)
        rx = next((pin for pin in uart if pin.name.upper().startswith("R")), None)
        if tx is None or rx is None:
            raise ConnectorError(f"{connector.label} has no TXD/RXD pair to test a loopback on.")

        pins = self._pins()
        try:
            # Pull RX the opposite way to what TX drives, so a floating RX (no
            # tool, or a tool without the short) reads wrong every time.
            for level in (1, 0, 1, 0):
                pins.input(rx.gpio, "down" if level else "up")
                pins.drive(tx.gpio, level)
                time.sleep(LOOPBACK_SETTLE_SECONDS)
                seen = pins.level(rx.gpio)
                if seen != level:
                    raise ConnectorError(
                        f"no TXD-RXD loopback: drove {tx.name} {'high' if level else 'low'} and "
                        f"{rx.name} read {'high' if seen else 'low'}. The tool is missing, not "
                        "seated, or is not the one expected."
                    )
        finally:
            pins.park(tx.gpio)
            pins.park(rx.gpio)

    def _verify_fingerprint(self, group: HardwareGroupMapping) -> str:
        from app.controllers.preflight import PreflightVerdict
        from app.services.esp32_builder import esp32_builder_service

        board_id = group.usb_board_id or ""
        deadline = time.monotonic() + self._usb_settle_seconds
        while True:
            result = esp32_builder_service.preflight_board(board_id)
            waiting = result.verdict in {PreflightVerdict.NOT_CONNECTED, PreflightVerdict.UNRESPONSIVE}
            if not waiting or time.monotonic() >= deadline:
                break
            time.sleep(USB_POLL_INTERVAL_SECONDS)

        if result.verdict is PreflightVerdict.OK:
            return f"Tool '{group.name}' confirmed: {board_id} answered with the expected firmware."
        if result.verdict is PreflightVerdict.NEEDS_FLASH and result.reported_controller_id == board_id:
            # The right board with stale firmware is still the right tool; the
            # run preflight is what decides whether to flash it.
            return (
                f"Tool '{group.name}' confirmed: {board_id} identified itself, "
                "but its firmware differs from the workspace and needs flashing."
            )
        raise ConnectorError(result.message)

    def _verify_usb_serial(self, group: HardwareGroupMapping) -> str:
        from app.services.hardware_map import hardware_map_service

        deadline = time.monotonic() + self._usb_settle_seconds
        while True:
            status = hardware_map_service.verify_board_connection(group.usb_board_id or "")
            if status.matched or status.connected or time.monotonic() >= deadline:
                break
            time.sleep(USB_POLL_INTERVAL_SECONDS)
        if not status.matched:
            raise ConnectorError(status.message)
        return f"Tool '{group.name}' confirmed by USB serial: {status.message}"


connector_state_store = ConnectorStateStore()
pogo_connector_service = PogoConnectorService()
