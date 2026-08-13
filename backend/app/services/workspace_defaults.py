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

# The Z axes get the same treatment, but per side: the two lead screws are
# calibrated independently and do not necessarily measure the same length.
_Z_RANGE_DERIVED_INPUTS: dict[str, dict[str, str]] = {
    "move_z": {"z_left_cm": "left", "z_right_cm": "right"},
}

# Both tool-change blocks describe the same physical rack, so an edit to a tool
# position on either one has to land on both.
_TOOLHEAD_FUNCTION_IDS = ("pickup_toolhead", "drop_toolhead")

# Every editable tool-change setting that should propagate to both tool blocks
# as the new default: the rack geometry and engage distances. Per-block intent
# stays out - which tool to grab (toolhead_index) and how fast to approach
# (approach_speed_rpm) legitimately differ between blocks. Hardware pins are
# excluded: the Hardware Map owns those.
TOOLHEAD_DEFAULT_KEYS = frozenset(
    {f"tool_{index}_{axis}_cm" for index in range(1, 7) for axis in ("x", "y")}
    | {"clearance_cm", "dip_depth_cm", "lift_cm", "release_cm"}
)


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


    def apply_z_track_lengths(
        self,
        left_track_length_cm: float,
        right_track_length_cm: float,
        limit_buffer_cm: float,
    ) -> dict:
        """Adopt a Z calibration as the new defaults and allowed ranges.

        The mirror of apply_track_lengths for the Z axes: what an operator
        measured during calibration becomes what the next block offers, so a
        corrected track length does not have to be retyped into every Move Z
        block - and a block cannot offer a target the machine cannot reach.

        Per side, unlike XY: the two screws are calibrated independently.
        """
        with self._lock:
            changed: list[str] = []
            usable = {
                "left": usable_max_cm(left_track_length_cm, limit_buffer_cm),
                "right": usable_max_cm(right_track_length_cm, limit_buffer_cm),
            }

            # What was measured becomes the starting point for the next
            # calibration, the same way the XY block adopts its track lengths.
            calibrate_path = self._app_functions_dir / "calibrate_z" / "manifest.json"
            if calibrate_path.exists():
                manifest = self._read_json(calibrate_path)
                wanted = {
                    "z_left_track_length_cm": float(left_track_length_cm),
                    "z_right_track_length_cm": float(right_track_length_cm),
                    "limit_buffer_cm": float(limit_buffer_cm),
                }
                manifest_changed = False
                for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]:
                    key = definition.get("key")
                    if key in wanted and definition.get("default") != wanted[key]:
                        definition["default"] = wanted[key]
                        manifest_changed = True
                        changed.append(f"calibrate_z.{key} default -> {wanted[key]}")
                if manifest_changed:
                    self._write_json_atomic(calibrate_path, manifest)

            for function_id, input_sides in _Z_RANGE_DERIVED_INPUTS.items():
                manifest_path = self._app_functions_dir / function_id / "manifest.json"
                if not manifest_path.exists():
                    continue
                manifest = self._read_json(manifest_path)
                manifest_changed = False
                for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]:
                    side = input_sides.get(definition.get("key"))
                    if side is None:
                        continue
                    if definition.get("min") != 0.0:
                        definition["min"] = 0.0
                        manifest_changed = True
                    if definition.get("max") != usable[side]:
                        definition["max"] = usable[side]
                        manifest_changed = True
                        changed.append(f"{function_id}.{definition['key']} max -> {usable[side]}")
                if manifest_changed:
                    self._write_json_atomic(manifest_path, manifest)

            return {
                "z_left_track_length_cm": float(left_track_length_cm),
                "z_right_track_length_cm": float(right_track_length_cm),
                "usable_left_max_cm": usable["left"],
                "usable_right_max_cm": usable["right"],
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

    def adopt_toolhead_defaults_from_workflow(self, workflow: dict) -> list[str]:
        """Adopt tool-block settings the moment a workflow is saved.

        Editing a value on any Pick Up / Drop Toolhead block and saving the
        workflow makes it the new default for future blocks immediately - the
        user should not have to run the block first for a measured rack
        position to stick."""
        collected: dict[str, float] = {}

        def walk(node: object) -> None:
            if isinstance(node, dict):
                block = node.get("data", {}).get("block") if isinstance(node.get("data"), dict) else None
                if isinstance(block, dict) and block.get("id") in _TOOLHEAD_FUNCTION_IDS:
                    parameters = node["data"].get("parameters")
                    if isinstance(parameters, dict):
                        for key, value in parameters.items():
                            if key in TOOLHEAD_DEFAULT_KEYS and isinstance(value, (int, float)):
                                collected[key] = float(value)
                for value in node.values():
                    walk(value)
            elif isinstance(node, list):
                for item in node:
                    walk(item)

        walk(workflow)
        if not collected:
            return []
        return self.apply_toolhead_defaults(collected)

    def current_toolhead_defaults(self) -> dict[str, float]:
        """The latest stored defaults for every shared tool-change setting.

        Read from the Pick Up Toolhead manifest, which apply_toolhead_defaults
        keeps in lockstep with the drop block."""
        manifest_path = self._app_functions_dir / "pickup_toolhead" / "manifest.json"
        if not manifest_path.exists():
            return {}
        manifest = self._read_json(manifest_path)
        return {
            definition.get("key"): float(definition.get("default"))
            for definition in [*manifest.get("inputs", []), *manifest.get("advanced_inputs", [])]
            if definition.get("key") in TOOLHEAD_DEFAULT_KEYS
            and isinstance(definition.get("default"), (int, float))
        }

    def apply_toolhead_defaults(self, values: dict[str, float]) -> list[str]:
        """Adopt these tool settings as the new defaults on both tool blocks.

        Called after a successful tool change so anything tuned in the UI sticks
        instead of reverting to the value authored here, and so both blocks keep
        describing the same physical rack. Only writes when a value differs.

        Pass only the settings the caller actually supplied. Filling the gaps from
        a model's defaults would let a caller that simply omitted a field reset a
        measurement someone had tuned on the machine.

        Hardware pins are deliberately excluded: those are owned by the Hardware
        Map and resolved from it on every run, so writing them back here would
        record a copy that silently fights the map once it changes.
        """
        with self._lock:
            changed: list[str] = []
            wanted = {key: round(float(value), 3) for key, value in values.items()}

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
