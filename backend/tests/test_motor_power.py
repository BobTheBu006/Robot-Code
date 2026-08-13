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
        # The line may be re-asserted (that is deliberate - see acquire), but it
        # must never be switched off in between.
        self.assertNotIn(False, line.calls, "power was never cut")

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
        # The whole point: five moves in a row without the drivers ever
        # dropping out. The enable is re-asserted each time rather than trusted,
        # so what matters is that nothing ever switched it off.
        line = _Line()
        service = _service(line, linger=5.0)
        for _ in range(5):
            service.acquire("d")
            service.release("d")
        self.assertNotIn(False, line.calls)
        self.assertTrue(line.state)

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

        self.assertNotIn(False, line.calls, "power must not drop while held")
        self.assertTrue(line.state)

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

class PolarityTests(unittest.TestCase):
    """A TB6600 is disabled by energising its ENABLE opto, a TB67S109 enabled.

    Getting this backwards does not fail loudly - the machine reports the
    motors as powered and simply refuses to move - so it is pinned here.
    """

    def test_an_active_high_domain_drives_high_to_enable(self) -> None:
        line = _Line()
        service = MotorPowerService()
        service.register("d", "TB67S109", line, settle_seconds=0.0, linger_seconds=60.0)
        service.acquire("d")
        self.assertEqual(line.state, True)
        service.power_down_now()
        self.assertEqual(line.state, False)

    def test_an_active_low_domain_is_recorded_as_such(self) -> None:
        line = _Line()
        service = MotorPowerService()
        service.register("d", "TB6600", line, settle_seconds=0.0, linger_seconds=60.0, active_low=True)
        service.acquire("d")

        domain = service.snapshot()["domains"][0]
        self.assertTrue(domain["active_low"])
        self.assertTrue(domain["powered"], "powered means enabled, whatever voltage that takes")

    def test_re_registering_updates_the_polarity(self) -> None:
        # A driver swapped for a different type must not keep the old polarity.
        line = _Line()
        service = MotorPowerService()
        service.register("d", "first", line, settle_seconds=0.0)
        service.register("d", "second", line, settle_seconds=0.0, active_low=True)
        self.assertTrue(service.snapshot()["domains"][0]["active_low"])

class ReassertTests(unittest.TestCase):
    """The enable line is asserted on every acquire, not just the first.

    Twice now a move has run with the drivers off while the service reported
    them on: the GPIO was re-claimed at its disabled level by the driver's own
    setup, and acquire trusted `powered` and skipped the write. The line is a
    physical thing other code touches, so it gets written every time.
    """

    def test_the_line_is_written_again_on_a_second_acquire(self) -> None:
        line = _Line()
        service = _service(line, linger=60.0)
        service.acquire("d")
        service.release("d")
        service.acquire("d")
        self.assertEqual(line.calls.count(True), 2, "asserted again rather than assumed")

    def test_a_line_disturbed_between_moves_is_put_back(self) -> None:
        # Stand-in for the real failure: something else drove the pin to its
        # disabled level while the domain still thought it was powered.
        line = _Line()
        service = _service(line, linger=60.0)
        service.acquire("d")
        service.release("d")
        line.calls.append(False)      # a driver re-claimed the pin, disabled
        service.acquire("d")
        self.assertTrue(line.state, "the next move re-enabled it")

    def test_is_powered_reports_the_hold(self) -> None:
        line = _Line()
        service = _service(line, linger=60.0)
        self.assertFalse(service.is_powered("d"))
        service.acquire("d")
        self.assertTrue(service.is_powered("d"))
        service.power_down_now()
        self.assertFalse(service.is_powered("d"))

    def test_is_powered_is_false_for_an_unknown_domain(self) -> None:
        self.assertFalse(MotorPowerService().is_powered("nope"))


if __name__ == "__main__":
    unittest.main()
