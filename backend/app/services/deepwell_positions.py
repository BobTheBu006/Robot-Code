"""Where the 24 deepwells sit on the right Z axis platform.

A 4 x 6 grid: columns A-D run along X, rows 1-6 along Y, so well "B3" is the
second column in X, third row in Y. Positions are gantry XY in cm, taught by
hand with the encoders (Teach Deepwell Positions).

Two layers:
- **Corners** A1, A6 and D1 define the grid. Every well is interpolated from
  them, which also absorbs a rack that sits slightly rotated or with uneven
  pitch between X and Y.
- **Overrides** pin individual wells to a position taught on that well, for
  when the grid alone is not accurate enough.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from threading import RLock

COLUMNS = "ABCD"   # along X
ROWS = 6           # along Y
WELL_NAMES = [f"{column}{row}" for column in COLUMNS for row in range(1, ROWS + 1)]
CORNER_NAMES = ("A1", f"A{ROWS}", f"{COLUMNS[-1]}1")

_REPO_ROOT = Path(__file__).resolve().parents[3]


class DeepwellPositionError(RuntimeError):
    pass


def _default_path() -> Path:
    override = os.getenv("ROBOT_DEEPWELL_POSITIONS_FILE")
    return Path(override) if override else _REPO_ROOT / "deepwell-positions.json"


def well_indexes(name: str) -> tuple[int, int]:
    """'B3' -> (column 1, row 2), both zero-based."""
    name = name.strip().upper()
    if name not in WELL_NAMES:
        raise DeepwellPositionError(f"Unknown deepwell '{name}'. Wells are A1-{COLUMNS[-1]}{ROWS}.")
    return COLUMNS.index(name[0]), int(name[1:]) - 1


class DeepwellPositionStore:
    def __init__(self, path: Path | None = None) -> None:
        self._explicit_path = path
        self._lock = RLock()

    @property
    def _path(self) -> Path:
        return self._explicit_path if self._explicit_path is not None else _default_path()

    def _read(self) -> dict:
        if not self._path.exists():
            return {"corners": {}, "overrides": {}}
        payload = json.loads(self._path.read_text(encoding="utf-8"))
        payload.setdefault("corners", {})
        payload.setdefault("overrides", {})
        return payload

    def _write(self, payload: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")

    def save_corners(self, corners: dict[str, tuple[float, float]]) -> None:
        """A new grid. Overrides taught against the old one are dropped: the
        rack has been placed again, so they no longer describe it."""
        missing = [name for name in CORNER_NAMES if name not in corners]
        if missing:
            raise DeepwellPositionError(f"The grid needs all three corners; missing {', '.join(missing)}.")
        with self._lock:
            payload = self._read()
            payload["corners"] = {name: [round(corners[name][0], 3), round(corners[name][1], 3)] for name in CORNER_NAMES}
            payload["overrides"] = {}
            self._write(payload)

    def save_overrides(self, wells: dict[str, tuple[float, float]]) -> None:
        with self._lock:
            payload = self._read()
            for name, (x_cm, y_cm) in wells.items():
                well_indexes(name)
                payload["overrides"][name.upper()] = [round(x_cm, 3), round(y_cm, 3)]
            self._write(payload)

    def positions(self) -> dict[str, dict]:
        """Every well: its position and whether it comes from the grid or a
        taught override. Wells without either are left out."""
        payload = self._read()
        corners = payload["corners"]
        result: dict[str, dict] = {}
        grid = all(name in corners for name in CORNER_NAMES)
        if grid:
            ax, ay = corners[CORNER_NAMES[0]]
            row_dx = (corners[CORNER_NAMES[1]][0] - ax) / (ROWS - 1)
            row_dy = (corners[CORNER_NAMES[1]][1] - ay) / (ROWS - 1)
            col_dx = (corners[CORNER_NAMES[2]][0] - ax) / (len(COLUMNS) - 1)
            col_dy = (corners[CORNER_NAMES[2]][1] - ay) / (len(COLUMNS) - 1)
        for name in WELL_NAMES:
            if name in payload["overrides"]:
                x_cm, y_cm = payload["overrides"][name]
                result[name] = {"x_cm": x_cm, "y_cm": y_cm, "source": "taught"}
            elif grid:
                column, row = well_indexes(name)
                result[name] = {
                    "x_cm": round(ax + column * col_dx + row * row_dx, 3),
                    "y_cm": round(ay + column * col_dy + row * row_dy, 3),
                    "source": "grid",
                }
        return result

    def position(self, name: str) -> tuple[float, float]:
        well_indexes(name)
        entry = self.positions().get(name.strip().upper())
        if entry is None:
            raise DeepwellPositionError(
                f"Deepwell {name} has no position yet. Run Teach Deepwell Positions (3 corners, or this well)."
            )
        return entry["x_cm"], entry["y_cm"]


deepwell_position_store = DeepwellPositionStore()
