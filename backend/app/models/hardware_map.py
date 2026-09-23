from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

HardwareDeviceKind = Literal["stepper_motor", "servo", "sensor"]
HardwareSensorKind = Literal["position_limit_switch", "aht20_temperature_humidity", "rotary_position_encoder"]


class HardwareBoardMapping(BaseModel):
    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    usb_port: str = Field(min_length=1)
    enabled: bool = True
    notes: str | None = None
    # A "dynamic" controller isn't permanently wired to usb_port — it's
    # physically swapped in/out of that port during a workflow run (e.g. the
    # 7-syringe-pump ESP32 today, a USB camera in the future). expected_serial_number
    # is the real USB descriptor serial number captured from whichever board was
    # on usb_port when the user confirmed "this is the one", used to verify the
    # right physical device is connected before a workflow acts on it.
    dynamic: bool = False
    expected_serial_number: str | None = None
    expected_hardware_id: str | None = None
    expected_device_label: str | None = None


class HardwarePinMapping(BaseModel):
    id: str = Field(min_length=1)
    signal: str = Field(min_length=1)
    gpio: str = Field(min_length=1)
    function_input_key: str | None = None
    notes: str | None = None


class HardwareDeviceMapping(BaseModel):
    id: str = Field(min_length=1)
    board_id: str = ""
    name: str = Field(min_length=1)
    kind: HardwareDeviceKind = "stepper_motor"
    enabled: bool = True
    sensor_kind: HardwareSensorKind | None = None
    rotation_min_deg: float | None = None
    rotation_max_deg: float | None = None
    calibration_ml_per_200_steps: float | None = None
    pins: list[HardwarePinMapping] = Field(default_factory=list)
    notes: str | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_legacy_kind(cls, data: object) -> object:
        if not isinstance(data, dict):
            return data

        normalized_data = dict(data)
        legacy_kind = normalized_data.get("kind")
        if legacy_kind == "motor":
            normalized_data["kind"] = "stepper_motor"
        elif legacy_kind in {"actuator", "other"}:
            normalized_data["kind"] = "servo"

        if normalized_data.get("kind") == "sensor" and not normalized_data.get("sensor_kind"):
            normalized_data["sensor_kind"] = "position_limit_switch"

        return normalized_data


# How a tool uses one contact of a pogo connector. "i2c" and "uart" hand the
# Pi's hardware peripheral to the pin; "gpio" leaves it as a plain input for
# the tool's own functions to claim; "unused" parks it as an input.
ConnectorPinMode = Literal["unused", "i2c", "uart", "gpio"]

# How the Pi confirms that the tool it was told about is the one on the head.
#   fingerprint - an ESP32 on the connector's USB answers the identity query
#   usb_serial  - a USB device reports the expected USB serial number
#   loopback    - the tool shorts TXD to RXD, so a pattern driven out comes back
#   none        - a dumb tool; nothing can be checked, and the result says so
ConnectorVerification = Literal["none", "loopback", "usb_serial", "fingerprint"]


class HardwareConnectorPin(BaseModel):
    name: str = Field(min_length=1)
    gpio: str = Field(min_length=1)
    # The Pi alternate function that routes this pin to its peripheral, as
    # pinctrl names it (a3 is I2C1 on GPIO 2/3, a4 is UART0 on GPIO 14/15 on
    # the Pi 5). Measured with `pinctrl funcs`, not read off a datasheet.
    peripheral: Literal["i2c", "uart"] | None = None
    alt_function: str | None = None


class HardwareConnectorMapping(BaseModel):
    """A connector whose far side changes with the docked tool.

    Only groups attach to a connector. Each group describes one tool: which of
    the connector's pins it uses and how, which controller shows up on the USB
    when it is docked, and how to verify it. At most one group is active at a
    time, and hardware in the others is unavailable until its tool is docked.
    """

    id: str = Field(min_length=1)
    label: str = Field(min_length=1)
    pins: list[HardwareConnectorPin] = Field(default_factory=list)
    # The Pi USB port the connector's USB lines are wired to. Informational:
    # tools are verified by identity, not by which ttyUSB they enumerate as.
    usb_port: str | None = None
    enabled: bool = True
    notes: str | None = None


class HardwareGroupMapping(BaseModel):
    id: str = Field(min_length=1)
    name: str = Field(min_length=1)
    member_ids: list[str] = Field(default_factory=list)
    enabled: bool = True
    notes: str | None = None
    # Set only for a group that is a tool on a dynamic connector.
    connector_id: str | None = None
    pin_modes: dict[str, ConnectorPinMode] = Field(default_factory=dict)
    usb_board_id: str | None = None
    verification: ConnectorVerification = "none"
    # The rack slot this tool lives in. Picking that slot up connects it.
    toolhead_index: int | None = None


class FunctionHardwareAssignment(BaseModel):
    function_id: str = Field(min_length=1)
    device_id: str = Field(min_length=1)
    hardware_device_id: str = ""


class HardwareNodePosition(BaseModel):
    node_id: str = Field(min_length=1)
    x: float
    y: float


class HardwareMap(BaseModel):
    version: int = 1
    boards: list[HardwareBoardMapping] = Field(default_factory=list)
    devices: list[HardwareDeviceMapping] = Field(default_factory=list)
    groups: list[HardwareGroupMapping] = Field(default_factory=list)
    connectors: list[HardwareConnectorMapping] = Field(default_factory=list)
    function_assignments: list[FunctionHardwareAssignment] = Field(default_factory=list)
    node_positions: list[HardwareNodePosition] = Field(default_factory=list)
    updated_at: datetime | None = None

    @model_validator(mode="after")
    def validate_unique_node_ids(self) -> "HardwareMap":
        seen_ids: set[str] = {"raspberry-pi"}
        duplicates: list[str] = []
        for item_id in [
            *(board.id for board in self.boards),
            *(device.id for device in self.devices),
            *(group.id for group in self.groups),
            *(connector.id for connector in self.connectors),
        ]:
            if item_id in seen_ids:
                duplicates.append(item_id)
            seen_ids.add(item_id)

        if duplicates:
            raise ValueError("Hardware map IDs must be unique: " + ", ".join(sorted(set(duplicates))))

        return self

    @model_validator(mode="after")
    def validate_connector_groups(self) -> "HardwareMap":
        """Reject a tool definition the connector could not actually serve.

        Caught at save time, because the alternative is finding out when a
        tool change half-configures the pins mid-run.
        """
        connectors = {connector.id: connector for connector in self.connectors}
        board_ids = {board.id for board in self.boards}
        slots: dict[tuple[str, int], str] = {}

        for group in self.groups:
            if group.connector_id is None:
                if group.pin_modes or group.usb_board_id or group.toolhead_index is not None:
                    raise ValueError(
                        f"Group '{group.name}' sets connector pins, USB or a rack slot but is not "
                        "attached to a connector."
                    )
                continue

            connector = connectors.get(group.connector_id)
            if connector is None:
                raise ValueError(f"Group '{group.name}' is attached to unknown connector '{group.connector_id}'.")

            pins = {pin.name: pin for pin in connector.pins}
            for pin_name, mode in group.pin_modes.items():
                pin = pins.get(pin_name)
                if pin is None:
                    raise ValueError(f"Group '{group.name}' uses pin '{pin_name}', which {connector.label} does not have.")
                if mode in {"i2c", "uart"} and pin.peripheral != mode:
                    raise ValueError(
                        f"Group '{group.name}' uses {pin_name} as {mode.upper()}, but that pin cannot carry {mode.upper()}."
                    )

            # I2C needs both wires; half a bus is a wiring mistake, not a mode.
            i2c_pins = {pin.name for pin in connector.pins if pin.peripheral == "i2c"}
            used_i2c = {name for name, mode in group.pin_modes.items() if mode == "i2c"}
            if used_i2c and used_i2c != i2c_pins:
                raise ValueError(f"Group '{group.name}' must use all of {', '.join(sorted(i2c_pins))} for I2C, not just some.")

            if group.verification == "loopback":
                uart_pins = [pin.name for pin in connector.pins if pin.peripheral == "uart"]
                if len(uart_pins) != 2:
                    raise ValueError(f"{connector.label} has no TX/RX pair to verify a loopback on.")
                busy = [name for name in uart_pins if group.pin_modes.get(name, "unused") != "unused"]
                if busy:
                    raise ValueError(
                        f"Group '{group.name}' is verified by a TX-RX loopback, so {', '.join(busy)} "
                        "are shorted on the tool and cannot also be used."
                    )

            if group.verification in {"fingerprint", "usb_serial"} and not group.usb_board_id:
                raise ValueError(f"Group '{group.name}' is verified over USB but names no USB controller.")
            if group.usb_board_id and group.usb_board_id not in board_ids:
                raise ValueError(f"Group '{group.name}' names unknown USB controller '{group.usb_board_id}'.")

            if group.toolhead_index is not None:
                key = (group.connector_id, group.toolhead_index)
                if key in slots:
                    raise ValueError(
                        f"Groups '{slots[key]}' and '{group.name}' both claim rack slot {group.toolhead_index}."
                    )
                slots[key] = group.name

        return self


class HardwareMapSaveResponse(BaseModel):
    path: str
    saved_at: datetime
    hardware_map: HardwareMap


class HardwareBoardConnectionStatus(BaseModel):
    board_id: str
    label: str
    usb_port: str
    dynamic: bool
    expected_serial_number: str | None
    detected_serial_number: str | None
    detected_hardware_id: str | None
    connected: bool
    matched: bool
    message: str
