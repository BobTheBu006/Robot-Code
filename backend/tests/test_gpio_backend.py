import sys
import types
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services import gpio_backend
from app.services.gpio_backend import LgpioBackend, load_gpio_backend


class FakeLgpio(types.ModuleType):
    """Records the lgpio calls the adapter makes so tests can assert the contract."""

    SET_PULL_UP = 32
    SET_PULL_DOWN = 64

    def __init__(self, chip_labels: dict[int, str], read_value: int = 1) -> None:
        super().__init__("lgpio")
        self.chip_labels = chip_labels
        self.read_value = read_value
        self.calls: list[tuple] = []
        self.freed: list[int] = []
        self.closed_handles: list[int] = []

    def gpiochip_open(self, chip: int) -> int:
        if chip not in self.chip_labels:
            raise RuntimeError(f"can not open gpiochip {chip}")
        return 100 + chip

    def gpiochip_close(self, handle: int) -> None:
        self.closed_handles.append(handle)

    def gpio_get_chip_info(self, handle: int) -> list:
        chip = handle - 100
        return [54, f"gpiochip{chip}", self.chip_labels[chip]]

    def gpio_claim_output(self, handle: int, gpio: int, level: int = 0, lFlags: int = 0) -> int:
        self.calls.append(("claim_output", handle, gpio, level))
        return 0

    def gpio_claim_input(self, handle: int, gpio: int, lFlags: int = 0) -> int:
        self.calls.append(("claim_input", handle, gpio, lFlags))
        return 0

    def gpio_write(self, handle: int, gpio: int, level: int) -> int:
        self.calls.append(("write", handle, gpio, level))
        return 0

    def gpio_read(self, handle: int, gpio: int) -> int:
        self.calls.append(("read", handle, gpio))
        return self.read_value

    def gpio_free(self, handle: int, gpio: int) -> int:
        self.freed.append(gpio)
        return 0


class GpioBackendLoaderTests(unittest.TestCase):
    def setUp(self) -> None:
        gpio_backend.reset_gpio_backend_cache()

    def tearDown(self) -> None:
        sys.modules.pop("lgpio", None)
        sys.modules.pop("RPi.GPIO", None)
        sys.modules.pop("RPi", None)
        gpio_backend.reset_gpio_backend_cache()

    def _install_fake_lgpio(self, chip_labels: dict[int, str], read_value: int = 1) -> FakeLgpio:
        fake = FakeLgpio(chip_labels, read_value)
        sys.modules["lgpio"] = fake
        return fake

    def test_falls_back_to_lgpio_when_rpi_gpio_is_missing(self) -> None:
        self._install_fake_lgpio({0: "pinctrl-rp1"})

        backend, reason = load_gpio_backend()

        self.assertIsNone(reason)
        self.assertIsInstance(backend, LgpioBackend)
        self.assertEqual(backend.chip, 0)

    def test_prefers_pinctrl_chip_over_lower_numbered_brcmstb_chips(self) -> None:
        # Older Pi 5 kernels expose the 40-pin header as gpiochip4 while
        # gpiochip0-3 are internal brcmstb chips.
        self._install_fake_lgpio({
            0: "gpio-brcmstb",
            1: "gpio-brcmstb",
            4: "pinctrl-rp1",
        })

        backend, reason = load_gpio_backend()

        self.assertIsNone(reason)
        self.assertIsInstance(backend, LgpioBackend)
        self.assertEqual(backend.chip, 4)

    def test_prefers_working_rpi_gpio_over_lgpio(self) -> None:
        class WorkingGPIO(types.ModuleType):
            BCM = "BCM"

            def setwarnings(self, _enabled: bool) -> None:
                return None

            def setmode(self, _mode: str) -> None:
                return None

            def gpio_function(self, _channel: int) -> int:
                return 0

            def cleanup(self) -> None:
                return None

        working = WorkingGPIO("RPi.GPIO")
        rpi_module = types.ModuleType("RPi")
        rpi_module.GPIO = working
        sys.modules["RPi"] = rpi_module
        sys.modules["RPi.GPIO"] = working
        self._install_fake_lgpio({0: "pinctrl-bcm2711"})

        backend, reason = load_gpio_backend()

        self.assertIsNone(reason)
        self.assertIs(backend, working)

    def test_rpi_gpio_failing_soc_detection_falls_back_to_lgpio(self) -> None:
        class Pi5IncompatibleGPIO(types.ModuleType):
            BCM = "BCM"

            def setwarnings(self, _enabled: bool) -> None:
                return None

            def setmode(self, _mode: str) -> None:
                return None

            def gpio_function(self, _channel: int) -> int:
                raise RuntimeError("Cannot determine SOC peripheral base address")

            def cleanup(self) -> None:
                return None

        broken = Pi5IncompatibleGPIO("RPi.GPIO")
        rpi_module = types.ModuleType("RPi")
        rpi_module.GPIO = broken
        sys.modules["RPi"] = rpi_module
        sys.modules["RPi.GPIO"] = broken
        self._install_fake_lgpio({0: "pinctrl-rp1"})

        backend, reason = load_gpio_backend()

        self.assertIsNone(reason)
        self.assertIsInstance(backend, LgpioBackend)

    def test_reports_both_reasons_when_no_backend_is_available(self) -> None:
        backend, reason = load_gpio_backend()

        self.assertIsNone(backend)
        self.assertIn("RPi.GPIO is unavailable", reason)
        self.assertIn("lgpio fallback is unavailable", reason)

    def test_adapter_setup_output_input_cleanup_contract(self) -> None:
        fake = self._install_fake_lgpio({0: "pinctrl-rp1"}, read_value=0)
        backend, _ = load_gpio_backend()
        assert isinstance(backend, LgpioBackend)
        handle = 100

        backend.setup(17, backend.OUT, initial=backend.LOW)
        backend.setup(21, backend.IN, pull_up_down=backend.PUD_UP)
        backend.output(17, backend.HIGH)
        backend.output(17, backend.LOW)
        value = backend.input(21)
        backend.cleanup([17, 21])

        self.assertEqual(value, backend.LOW)
        self.assertEqual(fake.calls, [
            ("claim_output", handle, 17, 0),
            ("claim_input", handle, 21, FakeLgpio.SET_PULL_UP),
            ("write", handle, 17, 1),
            ("write", handle, 17, 0),
            ("read", handle, 21),
        ])
        self.assertEqual(sorted(fake.freed), [17, 21])


class RaspberryGantryLgpioExecutionTests(unittest.TestCase):
    def setUp(self) -> None:
        gpio_backend.reset_gpio_backend_cache()

    def tearDown(self) -> None:
        sys.modules.pop("lgpio", None)
        gpio_backend.reset_gpio_backend_cache()
        import os
        os.environ.pop("ROBOT_GPIO_XY_STEPS_PER_CM", None)

    def test_move_xy_executes_for_real_through_lgpio(self) -> None:
        import os

        from app.models.gantry import GantryXYMoveRequest
        from app.services.raspberry_gantry import RaspberryGantryGPIOService

        # gpio_read -> 1 means limit switches are inactive (active-low default).
        fake = FakeLgpio({0: "pinctrl-rp1"}, read_value=1)
        sys.modules["lgpio"] = fake
        os.environ["ROBOT_GPIO_XY_STEPS_PER_CM"] = "1"

        service = RaspberryGantryGPIOService()
        result = service.move_xy(
            {"mode": "test"},
            GantryXYMoveRequest(x_cm=1, y_cm=1, z_cm=0),
        )

        self.assertEqual(result["status"], "gpio_executed")
        self.assertFalse(result["simulated"])
        step_writes = [call for call in fake.calls if call[0] == "write"]
        self.assertGreater(len(step_writes), 0)


if __name__ == "__main__":
    unittest.main()
