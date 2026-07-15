"""Keeps the calibrated track lengths as the single source of truth for the
gantry workspace.

When a calibration runs with new track lengths, those values become the new
defaults on the Calibrate block and the usable ranges on every move block are
re-derived from them. Without this the move blocks keep whatever ranges were
hand-written when they were authored, and silently drift out of step with the
machine the moment it is re-measured.

The usable range is inset from each limit switch by the calibrated buffer: user
coordinate 0 sits one buffer off the min switch, so the usable maximum is
trackLength - 2 * buffer. The buffer is editable on the Calibrate block and the
firmware persists whatever it was calibrated with, so it is read back from the
block rather than hard-coded here.
"""

from __future__ import annotations

import json
from pathlib import Path
from threading import Lock

# Fallback only, matching DEFAULT_XY_LIMIT_BUFFER_CM in the ESP32 firmware. The
# live value comes from the Calibrate block's limit_buffer_cm default.
DEFAULT_XY_LIMIT_BUFFER_CM = 0.5

_REPO_ROOT = Path(__file__).resolve().parents[3]
_APP_FUNCTIONS_DIR = Path(__file__).resolve().parents[1] / "functions"

# Move blocks whose target ranges are derived from the calibrated track lengths.
# Each entry maps an input key to the axis its range comes from.
_RANGE_DERIVED_INPUTS: dict[str, dict[str, str]] = {
    "move_gantry_xy": {"x_cm": "x", "y_cm": "y"},
    "move_gantry_circle": {"center_x_cm": "x", "center_y_cm": "y"},
}

# Both tool-change blocks describe the same physical rack, so an edit to a tool
# position on either one has to land on both.
_TOOLHEAD_FUNCTION_IDS = ("pickup_toolhead", "drop_toolhead")


def usable_max_cm(track_length_cm: float, buffer_cm: float = DEFAULT_XY_LIMIT_BUFFER_CM) -> float:
    """Highest coordinate a move may request on a track of this length."""
    return round(track_length_cm - 2.0 * buffer_cm, 3)


class WorkspaceDefaultsService:
    def __init__(self, repo_root: Path, app_functions_dir: Path) -> None:
        self._repo_root = repo_root
        self._app_functions_dir = app_functions_dir
        self._lock = Lock()

    def _read_json(self, path: Path) -> dict:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)

    def _write_json_atomic(self, path: Path, payload: dict) -> None:
        temp_path = path.with_suffix(path.suffix + ".tmp")
        with temp_path.open("w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
            handle.write("\n")
        temp_path.replace(path)

    def _calibrate_builder_source(self) -> Path | None:
        """Path to the blueprint that generates the calibrate_xy manifest.

        The generated manifest is rewritten from this source on every builder
        sync, so defaults must be written here to survive.
        """
        manifest_path = self._app_functions_dir / "calibrate_xy" / "manifest.json"
        if not manifest_path.exists():
            return None
        source_path = self._read_json(manifest_path).get("builder_source_path")
        if not source_path:
            return None
        candidate = Path(source_path)
        return candidate if candidate.exists() else None

    def current_track_lengths(self) -> dict[str, float | None]:
        source = self._calibrate_builder_source()
        keys = {"x_track_length_cm": None, "y_track_length_cm": None, "limit_buffer_cm": None}
        if source is None:
            return dict(keys)
        manifest = self._read_json(source).get("manifest", {})
        values: dict[str, float | None] = dict(keys)
        for definition in manifest.get("inputs", []):
            if definition.get("key") in values:
                values[definition["key"]] = definition.get("default")
        return values

    def current_buffer_cm(self) -> float:
        value = self.current_track_lengths().get("limit_buffer_cm")
        return DEFAULT_XY_LIMIT_BUFFER_CM if value is None else float(value)

    def apply_track_lengths(
        self,
        x_track_length_cm: float,
        y_track_length_cm: float,
        limit_buffer_cm: float = DEFAULT_XY_LIMIT_BUFFER_CM,
    ) -> dict:
        """Adopt these track lengths and buffer as the new defaults and ranges.

        Returns a summary of what changed. Safe to call when nothing changed:
        files are only rewritten when a value actually differs.
        """
        with self._lock:
            changed: list[str] = []
            source = self._calibrate_builder_source()

            if source is not None:
                blueprint = self._read_json(source)
                manifest = blueprint.get("manifest", {})
                wanted = {
                    "x_track_length_cm": float(x_track_length_cm),
                    "y_track_length_cm": float(y_track_length_cm),
                    "limit_buffer_cm": float(limit_buffer_cm),
                }
                source_changed = False
                for definition in manifest.get("inputs", []):
                    key = definition.get("key")
                    if key in wanted and definition.get("default") != wanted[key]:
                        definition["default"] = wanted[key]
                        source_changed = True
                        changed.append(f"calibrate_xy.{key} default -> {wanted[key]}")
                if source_changed:
                    self._write_json_atomic(source, blueprint)

            usable = {
                "x": usable_max_cm(x_track_length_cm, limit_buffer_cm),
                "y": usable_max_cm(y_track_length_cm, limit_buffer_cm),
            }

            for function_id, input_axes in _RANGE_DERIVED_INPUTS.items():
                manifest_path = self._app_functions_dir / function_id / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = self._read_json(manifest_path)
                manifest_changed = False
                for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]:
                    axis = input_axes.get(definition.get("key"))
                    if axis is None:
                        continue
                    if definition.get("min") != 0.0:
                        definition["min"] = 0.0
                        manifest_changed = True
                    if definition.get("max") != usable[axis]:
                        definition["max"] = usable[axis]
                        manifest_changed = True
                        changed.append(f"{function_id}.{definition['key']} max -> {usable[axis]}")
                if manifest_changed:
                    self._write_json_atomic(manifest_path, manifest)

            if changed:
                # Regenerate calibrate_xy's manifest from the blueprint just edited.
                try:
                    from app.services.esp32_builder import esp32_builder_service

                    esp32_builder_service.sync_generated_functions()
                except Exception:
                    # A builder that cannot sync must not fail a completed
                    # calibration; the blueprint on disk is already correct.
                    pass

            return {
                "x_track_length_cm": float(x_track_length_cm),
                "y_track_length_cm": float(y_track_length_cm),
                "usable_x_max_cm": usable["x"],
                "usable_y_max_cm": usable["y"],
                "buffer_cm": float(limit_buffer_cm),
                "changed": changed,
            }


    def current_toolhead_positions(self) -> dict[int, tuple[float, float]]:
        """Tool positions as currently stored on the Pick Up Toolhead block."""
        manifest_path = self._app_functions_dir / "pickup_toolhead" / "manifest.json"
        if not manifest_path.exists():
            return {}
        manifest = self._read_json(manifest_path)
        by_key = {
            definition.get("key"): definition.get("default")
            for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]
        }
        positions: dict[int, tuple[float, float]] = {}
        for index in range(1, 7):
            x_cm = by_key.get(f"tool_{index}_x_cm")
            y_cm = by_key.get(f"tool_{index}_y_cm")
            if x_cm is not None and y_cm is not None:
                positions[index] = (float(x_cm), float(y_cm))
        return positions

    def apply_toolhead_positions(self, positions: dict[int, tuple[float, float]]) -> list[str]:
        """Adopt these tool positions as the new defaults on both tool blocks.

        Called after a successful tool change so a position tuned in the UI
        sticks, instead of reverting to the value authored here. Only writes when
        a value actually differs.
        """
        with self._lock:
            changed: list[str] = []
            wanted: dict[str, float] = {}
            for index, (x_cm, y_cm) in positions.items():
                wanted[f"tool_{index}_x_cm"] = round(float(x_cm), 3)
                wanted[f"tool_{index}_y_cm"] = round(float(y_cm), 3)

            for function_id in _TOOLHEAD_FUNCTION_IDS:
                manifest_path = self._app_functions_dir / function_id / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = self._read_json(manifest_path)
                manifest_changed = False
                for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]:
                    key = definition.get("key")
                    if key in wanted and definition.get("default") != wanted[key]:
                        definition["default"] = wanted[key]
                        manifest_changed = True
                        changed.append(f"{function_id}.{key} default -> {wanted[key]}")
                if manifest_changed:
                    self._write_json_atomic(manifest_path, manifest)

            return changed


workspace_defaults_service = WorkspaceDefaultsService(
    repo_root=_REPO_ROOT,
    app_functions_dir=_APP_FUNCTIONS_DIR,
)
