"""Powering motor drivers only while they are in use.

The behaviour that matters on the machine: the settle delay is paid once at the
start of a sequence and not between every block, and power does not drop while
consecutive blocks are still using the motors.
"""

import sys
import time
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.services.motor_power import MotorPowerService


class _Line:
    """Records what a shared enable line was asked to do."""

    def __init__(self, fail: bool = False) -> None:
        self.calls: list[bool] = []
        self.fail = fail

    def __call__(self, on: bool) -> None:
        if self.fail:
            raise RuntimeError("GPIO unavailable")
        self.calls.append(on)

    @property
    def state(self) -> bool | None:
        return self.calls[-1] if self.calls else None


def _service(line, *, settle=0.0, linger=0.05):
    service = MotorPowerService()
    service.register("d", "test drivers", line, settle_seconds=settle, linger_seconds=linger)
    return service


class EnableTests(unittest.TestCase):
    def test_acquiring_energises_the_drivers(self) -> None:
        line = _Line()
        _service(line).acquire("d")
        self.assertEqual(line.calls, [True])

    def test_the_settle_delay_is_paid_before_stepping(self) -> None:
        line = _Line()
        service = _service(line, settle=0.15)

        started = time.monotonic()
        service.acquire("d")
        elapsed = time.monotonic() - started

        self.assertGreaterEqual(elapsed, 0.15)
        self.assertEqual(line.state, True)

    def test_the_settle_delay_is_not_paid_again_while_already_powered(self) -> None:
        # Back-to-back blocks must not each wait a second.
        line = _Line()
        service = _service(line, settle=0.15)
        service.acquire("d")

        started = time.monotonic()
        service.acquire("d")
        self.assertLess(time.monotonic() - started, 0.05)
        self.assertEqual(line.calls, [True], "power was never cycled")

    def test_an_unknown_domain_is_ignored_rather_than_raising(self) -> None:
        # A machine without an enable line wired must still run.
        service = MotorPowerService()
        service.acquire("nothing-here")
        service.release("nothing-here")

    def test_a_line_that_cannot_be_driven_surfaces(self) -> None:
        service = _service(_Line(fail=True))
        with self.assertRaises(RuntimeError):
            service.acquire("d")


class LingerTests(unittest.TestCase):
    def test_power_stays_on_immediately_after_release(self) -> None:
        line = _Line()
        service = _service(line, linger=5.0)
        service.acquire("d")
        service.release("d")
        self.assertEqual(line.state, True, "releasing must not cut power straight away")

    def test_consecutive_blocks_do_not_power_cycle_the_motors(self) -> None:
        # The whole point: five moves in a row, one power-up.
        line = _Line()
        service = _service(line, linger=5.0)
        for _ in range(5):
            service.acquire("d")
            service.release("d")
        self.assertEqual(line.calls, [True])

    def test_power_drops_once_nothing_has_wanted_the_motors(self) -> None:
        line = _Line()
        service = _service(line, linger=0.05)
        service.acquire("d")
        service.release("d")

        deadline = time.monotonic() + 2.0
        while line.state is not False and time.monotonic() < deadline:
            time.sleep(0.01)

        self.assertEqual(line.calls, [True, False])

    def test_reacquiring_during_the_linger_cancels_the_power_down(self) -> None:
        line = _Line()
        service = _service(line, linger=0.2)
        service.acquire("d")
        service.release("d")
        time.sleep(0.05)
        service.acquire("d")   # a block arrived before the timer fired
        time.sleep(0.3)        # past when it would have fired

        self.assertEqual(line.calls, [True], "power must not drop while held")

    def test_an_overlapping_hold_keeps_power_until_the_last_release(self) -> None:
        line = _Line()
        service = _service(line, linger=0.05)
        service.acquire("d")
        service.acquire("d")
        service.release("d")
        time.sleep(0.15)
        self.assertEqual(line.state, True, "one holder remains")

        service.release("d")
        deadline = time.monotonic() + 2.0
        while line.state is not False and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(line.state, False)


class PowerDownTests(unittest.TestCase):
    def test_power_down_now_ignores_holders_and_the_timer(self) -> None:
        # End of run and E-Stop: everything has stopped, so drop power at once.
        line = _Line()
        service = _service(line, linger=60.0)
        service.acquire("d")
        service.power_down_now()
        self.assertEqual(line.calls, [True, False])

    def test_power_down_is_safe_to_repeat(self) -> None:
        line = _Line()
        service = _service(line, linger=60.0)
        service.acquire("d")
        service.power_down_now()
        service.power_down_now()
        self.assertEqual(line.calls, [True, False])

    def test_a_failing_line_does_not_stop_other_domains_powering_off(self) -> None:
        good, bad = _Line(), _Line()
        service = MotorPowerService()
        service.register("good", "good", good, settle_seconds=0.0, linger_seconds=60.0)
        service.register("bad", "bad", bad, settle_seconds=0.0, linger_seconds=60.0)
        service.acquire("good")
        service.acquire("bad")
        bad.fail = True

        service.power_down_now()   # must not raise

        self.assertEqual(good.state, False)
        self.assertIsNotNone(service.snapshot()["domains"][1]["last_error"])

    def test_after_power_down_the_next_move_pays_the_settle_delay_again(self) -> None:
        line = _Line()
        service = _service(line, settle=0.15, linger=60.0)
        service.acquire("d")
        service.power_down_now()

        started = time.monotonic()
        service.acquire("d")
        self.assertGreaterEqual(time.monotonic() - started, 0.15)


class ReportingTests(unittest.TestCase):
    def test_the_snapshot_says_whether_power_is_held_or_lingering(self) -> None:
        line = _Line()
        service = _service(line, linger=5.0)
        service.acquire("d")
        held = service.snapshot()["domains"][0]
        self.assertTrue(held["powered"])
        self.assertFalse(held["lingering"])
        self.assertEqual(held["holders"], 1)

        service.release("d")
        lingering = service.snapshot()["domains"][0]
        self.assertTrue(lingering["powered"])
        self.assertTrue(lingering["lingering"])


if __name__ == "__main__":
    unittest.main()
