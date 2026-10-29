"""Both Z sides home at once: each motor is stopped by its own switch.

A simulated Z board stands in for the ESP32. It follows the firmware's rules:
"STOP <Z switch>" holds only that motor while the other carries on, plain
STOP ends the move - and firmware without stop sources ignores a sourced stop
mid-move, which is why the Pi asks (FEATURES?) before relying on it.
"""

import contextlib
import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.models.gantry import GantryZCalibrationRequest
from app.services import hybrid_z_axis
from app.services.hybrid_z_axis import HybridZAxisService

SIDES = ("left", "right")
SWITCH_SIDE = {"Z_LEFT_MIN": "left", "Z_LEFT_MAX": "left", "Z_RIGHT_MIN": "right", "Z_RIGHT_MAX": "right"}


class FakeZBoard:
    """Serial-port stand-in. Positions are physical steps; the min switch is
    pressed at or below 0, the max switch at or above `max_at`."""

    def __init__(self, positions: dict, max_at: dict, *, stop_sources: bool = True, step: int = 50) -> None:
        self.pos = dict(positions)
        self.max_at = dict(max_at)
        self.stop_sources = stop_sources
        self.step = step
        self.out = b""
        self.move: dict | None = None
        self.log: list[str] = []

    def pressed(self, side: str, end: str) -> bool:
        return self.pos[side] <= 0 if end == "min" else self.pos[side] >= self.max_at[side]

    # -- serial API used by the service --
    def reset_input_buffer(self) -> None:
        self.out = b""

    def reset_output_buffer(self) -> None:
        pass

    def flush(self) -> None:
        pass

    def write(self, data: bytes) -> None:
        for line in data.decode().splitlines():
            if line.strip():
                self._command(line.strip())

    @property
    def in_waiting(self) -> int:
        self._advance()
        return len(self.out)

    def read(self, count: int) -> bytes:
        data, self.out = self.out[:count], self.out[count:]
        return data

    def readline(self) -> bytes:
        while self.move is not None and b"\n" not in self.out:
            self._advance()
        if b"\n" not in self.out:
            return b""
        line, _, self.out = self.out.partition(b"\n")
        return line + b"\n"

    # -- firmware behaviour --
    def _reply(self, line: str) -> None:
        self.out += (line + "\n").encode()

    def _command(self, command: str) -> None:
        self.log.append(command)
        if command.startswith("SET Z PINS"):
            self._reply("OK SET Z PINS")
        elif command == "FEATURES?":
            self._reply("OK FEATURES STOP_SOURCE" if self.stop_sources else "ERR UNKNOWN CMD")
        elif command.startswith("STEP Z"):
            parts = command.split()
            self.move = {
                "remaining": {"left": int(parts[2]), "right": int(parts[3])},
                "done": {"left": 0, "right": 0},
                "held": set(),
            }
        elif command == "STOP" or command.startswith("STOP "):
            source = command[5:].strip()
            if self.move is None:
                self._reply("OK " + command)
                return
            if source and not self.stop_sources:
                return  # old firmware: only an exact "STOP" is recognised mid-move
            self._reply("OK " + command)
            side = SWITCH_SIDE.get(source)
            if side is None:
                self._finish(stopped=True)
                return
            self.move["held"].add(side)
            self._finish_if_done()

    def _advance(self) -> None:
        if self.move is None:
            return
        for side in SIDES:
            remaining = self.move["remaining"][side]
            if remaining == 0 or side in self.move["held"]:
                continue
            count = min(self.step, abs(remaining)) * (1 if remaining > 0 else -1)
            self.pos[side] += count
            self.move["done"][side] += count
            self.move["remaining"][side] -= count
        self._finish_if_done()

    def _finish_if_done(self) -> None:
        if self.move and all(self.move["remaining"][s] == 0 or s in self.move["held"] for s in SIDES):
            self._finish(stopped=False)

    def _finish(self, *, stopped: bool) -> None:
        done = self.move["done"]
        self.move = None
        self._reply(f"{'OK STOP STEP Z' if stopped else 'OK STEP Z'} {done['left']} {done['right']}")


PINS = {12: ("left", "min"), 13: ("left", "max"), 14: ("right", "min"), 15: ("right", "max")}


class HomingTogetherTests(unittest.TestCase):
    def _service(self, board: FakeZBoard) -> HybridZAxisService:
        service = HybridZAxisService()
        patches = [
            mock.patch.object(service, "_save_state"),  # never touch the real z-gantry-state.json
            mock.patch.object(service, "_hold_power", lambda *_args: contextlib.nullcontext()),
            mock.patch.object(service, "_resolve_port", lambda *_args: "/dev/fake"),
            mock.patch.object(service, "_open_serial", lambda *_args: board),
            mock.patch.object(service, "_setup_limit_gpio", lambda *_args: None),
            mock.patch.object(service, "_cleanup_limit_gpio", lambda *_args: None),
            mock.patch.object(service, "_limit_active", lambda _gpio, pin: board.pressed(*PINS[pin])),
            mock.patch.object(hybrid_z_axis, "load_gpio_backend", lambda: (object(), None)),
        ]
        for patch in patches:
            patch.start()
            self.addCleanup(patch.stop)
        return service

    def _calibrate(self, service: HybridZAxisService, axes: str = "both") -> dict:
        request = GantryZCalibrationRequest(
            z_left_track_length_cm=5.0, z_right_track_length_cm=5.0, steps_per_cm_estimate=1000.0,
            limit_buffer_cm=0.0, axes=axes,
        )
        return service.calibrate_z({"mode": "test"}, request)

    def test_both_sides_seek_at_once_and_stop_on_their_own_switch(self) -> None:
        board = FakeZBoard({"left": 3000, "right": 500}, {"left": 5000, "right": 4800})
        service = self._service(board)
        result = service._seek_switches(board, None, {"left": 12, "right": 14}, -1, 10000, 100, True, 300, 800)

        self.assertEqual(result["left"][1], True)
        self.assertEqual(result["right"][1], True)
        # One move for both; the right switch (closer) is stopped by source,
        # then the left gets the plain STOP that ends the move.
        self.assertEqual(sum(command.startswith("STEP Z") for command in board.log), 1)
        self.assertEqual(board.log[1:], ["STOP Z_RIGHT_MIN", "STOP"])
        # Each stopped within one poll of its switch, not dragged on by the other.
        self.assertGreater(board.pos["right"], -100)
        self.assertGreater(board.pos["left"], -100)

    def test_a_side_already_on_its_switch_does_not_move(self) -> None:
        board = FakeZBoard({"left": 0, "right": 600}, {"left": 5000, "right": 5000})
        service = self._service(board)
        result = service._seek_switches(board, None, {"left": 12, "right": 14}, -1, 10000, 100, True, 300, 800)
        self.assertEqual(result["left"], (0, True))
        self.assertTrue(board.log[0].startswith("STEP Z 0 -10000"))

    def test_calibration_homes_both_together_and_measures_each_side(self) -> None:
        board = FakeZBoard({"left": 3000, "right": 700}, {"left": 5000, "right": 4700})
        result = self._calibrate(self._service(board))

        self.assertTrue(result["homed_together"])
        self.assertTrue(result["calibrated"])
        self.assertIn("STOP Z_RIGHT_MIN", board.log)
        self.assertTrue(any(command.endswith("_MAX") for command in board.log))
        # Every seek moved both motors in one command.
        seeks = [command.split() for command in board.log if command.startswith("STEP Z") and "10000" in command]
        self.assertEqual(len(seeks), 2, "one fast seek down, one up")
        self.assertTrue(all(int(parts[2]) != 0 and int(parts[3]) != 0 for parts in seeks), seeks)
        lengths = result["workspace"]
        self.assertAlmostEqual(lengths["z_left_track_length_cm"] / lengths["z_right_track_length_cm"], 5000 / 4700, places=1)

    def test_old_firmware_falls_back_to_one_side_after_the_other(self) -> None:
        board = FakeZBoard({"left": 3000, "right": 700}, {"left": 5000, "right": 4700}, stop_sources=False)
        result = self._calibrate(self._service(board))

        self.assertFalse(result["homed_together"])
        self.assertTrue(result["calibrated"])
        self.assertFalse([command for command in board.log if command.startswith("STOP Z_")])

    def test_a_single_side_calibration_never_asks_for_stop_sources(self) -> None:
        board = FakeZBoard({"left": 3000, "right": 700}, {"left": 5000, "right": 4700})
        result = self._calibrate(self._service(board), axes="left")
        self.assertFalse(result["homed_together"])
        self.assertNotIn("FEATURES?", board.log)
        self.assertEqual(board.pos["right"], 700)


if __name__ == "__main__":
    unittest.main()
