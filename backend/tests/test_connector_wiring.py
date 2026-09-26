"""Tools wired to the pogo connector's pins rather than to GPIO numbers.

A device in a tool group names connector pins (SDA, SCL, TXD, RXD). The code
works out how each pin is used from that wiring and resolves the real Pi GPIO,
so the owner never sets pin modes by hand.
"""

import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.function_manifest import FunctionManifest
from app.models.hardware_map import (
    FunctionHardwareAssignment,
    HardwareBoardMapping,
    HardwareDeviceMapping,
    HardwareGroupMapping,
    HardwareMap,
    HardwarePinMapping,
    connector_pin_modes,
)
from app.services.hardware_map import HardwareMapError, HardwareMapService, default_pogo_connector
from app.services.pogo_connector import ConnectorStateStore, PogoConnectorService, SimulatedPinDriver

CONNECTOR = "pogo-connector"


def _device(device_id, *pins, kind="sensor", sensor_kind="position_limit_switch", board_id=CONNECTOR):
    return HardwareDeviceMapping(
        id=device_id, board_id=board_id, name=device_id.replace("-", " ").title(), kind=kind,
        sensor_kind=sensor_kind if kind == "sensor" else None,
        pins=[HardwarePinMapping(id=f"{device_id}-{signal}", signal=signal, gpio=gpio, function_input_key=key)
              for signal, gpio, key in pins],
    )


def _aht20(device_id="climate-sensor"):
    return _device(device_id, ("scl", "SCL", None), ("sda", "SDA", None), sensor_kind="aht20_temperature_humidity")


def _tool(*member_ids, **fields):
    return HardwareGroupMapping(id="tool", name="Tool", connector_id=CONNECTOR, member_ids=list(member_ids), **fields)


def _map(groups, devices, boards=(), assignments=(), **fields):
    connector = default_pogo_connector()
    if "connector" in fields:
        connector = fields.pop("connector")
    return HardwareMap(
        boards=list(boards), devices=list(devices), groups=list(groups), connectors=[connector],
        function_assignments=list(assignments), **fields,
    )


class DerivedModeTests(unittest.TestCase):
    def test_an_i2c_sensor_on_sda_scl_uses_the_i2c_bus(self) -> None:
        hardware_map = _map([_tool("climate-sensor")], [_aht20()])
        modes = connector_pin_modes(hardware_map, hardware_map.groups[0])
        self.assertEqual(modes, {"SDA": "i2c", "SCL": "i2c", "TXD": "unused", "RXD": "unused"})

    def test_a_plain_wire_is_gpio_even_on_a_uart_pin(self) -> None:
        hardware_map = _map([_tool("probe")], [_device("probe", ("signal", "RXD", None))])
        self.assertEqual(connector_pin_modes(hardware_map, hardware_map.groups[0])["RXD"], "gpio")

    def test_a_tx_signal_on_txd_is_uart(self) -> None:
        hardware_map = _map([_tool("modem")], [_device("modem", ("tx", "TXD", None), kind="servo")])
        self.assertEqual(connector_pin_modes(hardware_map, hardware_map.groups[0])["TXD"], "uart")

    def test_two_i2c_devices_share_the_bus(self) -> None:
        hardware_map = _map([_tool("a", "b")], [_aht20("a"), _aht20("b")])
        self.assertEqual(connector_pin_modes(hardware_map, hardware_map.groups[0])["SDA"], "i2c")

    def test_two_wires_on_one_gpio_pin_are_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "both wired to RXD"):
            _map([_tool("a", "b")], [_device("a", ("signal", "RXD", None)), _device("b", ("signal", "RXD", None))])

    def test_half_an_i2c_bus_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "must use all"):
            _map([_tool("half")], [_device("half", ("sda", "SDA", None))])

    def test_a_loopback_tool_cannot_have_hardware_on_its_shorted_pins(self) -> None:
        with self.assertRaisesRegex(ValueError, "shorted"):
            _map([_tool("probe", verification="loopback")], [_device("probe", ("signal", "TXD", None))])


class WiringValidationTests(unittest.TestCase):
    def test_a_pin_the_connector_does_not_have_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "which has only"):
            _map([_tool("probe")], [_device("probe", ("signal", "17", None))])

    def test_connector_hardware_must_belong_to_a_tool(self) -> None:
        with self.assertRaisesRegex(ValueError, "belongs to no tool"):
            _map([], [_device("probe", ("signal", "RXD", None))])

    def test_the_four_usb_ports_exist_by_default(self) -> None:
        self.assertEqual([p.number for p in HardwareMap().usb_ports], [1, 2, 3, 4])

    def test_the_connector_usb_must_be_a_defined_port(self) -> None:
        connector = default_pogo_connector().model_copy(update={"usb_port_number": 7})
        with self.assertRaisesRegex(ValueError, "USB 7"):
            _map([], [], connector=connector)


def _manifest():
    return FunctionManifest.model_validate({
        "id": "read_probe", "display_name": "Read Probe", "category": "Robot Actions",
        "description": "Reads the probe.", "version": "0.1.0",
        "inputs": [{"key": "probe_pin", "label": "Probe", "type": "string"}],
        "hardware_devices": [{"id": "probe", "name": "Probe", "kind": "sensor",
                              "pins": [{"id": "p", "signal": "signal", "function_input_key": "probe_pin"}]}],
    })


class FunctionResolutionTests(unittest.TestCase):
    def _service(self, hardware_map, active):
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        service = HardwareMapService(Path(directory.name) / "map.json", active_connector_groups=lambda: active)
        service.save_map(hardware_map)
        return service

    def test_a_connector_pin_resolves_to_its_pi_gpio(self) -> None:
        hardware_map = _map(
            [_tool("probe")], [_device("probe", ("signal", "RXD", "probe_pin"))],
            assignments=[FunctionHardwareAssignment(function_id="read_probe", device_id="probe",
                                                    hardware_device_id="probe")],
        )
        inputs = self._service(hardware_map, {"tool"}).apply_function_defaults(_manifest(), {})
        self.assertEqual(inputs["probe_pin"], "15")

    def test_a_disabled_connector_disables_its_hardware(self) -> None:
        connector = default_pogo_connector().model_copy(update={"enabled": False})
        hardware_map = _map(
            [_tool("probe")], [_device("probe", ("signal", "RXD", "probe_pin"))], connector=connector,
            assignments=[FunctionHardwareAssignment(function_id="read_probe", device_id="probe",
                                                    hardware_device_id="probe")],
        )
        with self.assertRaises(HardwareMapError):
            self._service(hardware_map, {"tool"}).apply_function_defaults(_manifest(), {})

    def test_hardware_on_the_tools_usb_board_leaves_with_the_tool(self) -> None:
        # The group names the board only as usb_board_id, not as a member.
        board = HardwareBoardMapping(id="tool-esp", label="Tool ESP32", usb_port="/dev/ttyUSB1")
        motor = _device("pump-motor", ("step", "12", "probe_pin"), kind="stepper_motor", board_id="tool-esp")
        hardware_map = _map(
            [_tool(usb_board_id="tool-esp")], [motor], boards=[board],
            assignments=[FunctionHardwareAssignment(function_id="read_probe", device_id="probe",
                                                    hardware_device_id="pump-motor")],
        )
        with self.assertRaisesRegex(HardwareMapError, "not connected"):
            self._service(hardware_map, set()).apply_function_defaults(_manifest(), {})


class ActivationTests(unittest.TestCase):
    def test_activating_a_wired_tool_configures_the_derived_modes(self) -> None:
        hardware_map = _map([_tool("climate-sensor", "probe")],
                            [_aht20(), _device("probe", ("signal", "RXD", None))])
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        pins = SimulatedPinDriver()
        service = PogoConnectorService(
            state_store=ConnectorStateStore(Path(directory.name) / "s.json"), pin_driver=pins,
            load_map=lambda: hardware_map, usb_settle_seconds=0.0,
        )

        result = service.activate("tool")

        self.assertEqual(pins.state["2"], ("alt", "a3"))
        self.assertEqual(pins.state["3"], ("alt", "a3"))
        self.assertEqual(pins.state["15"], ("input", "none"), "GPIO left for the probe's block")
        self.assertEqual(result.pin_modes, {"SDA": "i2c", "SCL": "i2c", "TXD": "unused", "RXD": "gpio"})


if __name__ == "__main__":
    unittest.main()
