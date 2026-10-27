"""Save the tool positions taught by hand in the editor's teach dialog.

The dialog does the interactive part (TEACH START / POS? / END through
/api/robot/xy-teach); this runs once at the end with what was saved and
writes it into the shared toolhead defaults that Pick Up and Drop use.
"""

import json

from app.services.workspace_defaults import workspace_defaults_service

TOOLHEAD_COUNT = 6
# The rack sits at the min end of the rail; a slot can be slightly below the
# homed X reference (see TOOLHEAD_MIN_X_CM), never far outside the track.
MIN_CM, MAX_CM = -2.0, 120.0


def _taught(inputs: dict) -> dict[int, tuple[float, float]]:
    raw = inputs.get("positions") or {}
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else {}
    taught: dict[int, tuple[float, float]] = {}
    for slot, position in raw.items():
        index = int(slot)
        if not 1 <= index <= TOOLHEAD_COUNT:
            raise ValueError(f"Slot {index} does not exist; the rack has {TOOLHEAD_COUNT}.")
        x_cm, y_cm = float(position["x_cm"]), float(position["y_cm"])
        for axis, value in (("X", x_cm), ("Y", y_cm)):
            if not MIN_CM <= value <= MAX_CM:
                raise ValueError(f"Slot {index} {axis} = {value:.2f} cm is outside the machine.")
        taught[index] = (round(x_cm, 3), round(y_cm, 3))
    return taught


def execute(context: dict, inputs: dict) -> dict:
    taught = _taught(inputs)
    if not taught:
        return {"status": "completed", "message": "No tool positions were saved.", "saved": {}, "mode": context.get("mode")}

    values = {}
    for index, (x_cm, y_cm) in taught.items():
        values[f"tool_{index}_x_cm"] = x_cm
        values[f"tool_{index}_y_cm"] = y_cm
    changed = workspace_defaults_service.apply_toolhead_defaults(values)

    slots = ", ".join(f"{i}: X {x:g} / Y {y:g}" for i, (x, y) in sorted(taught.items()))
    return {
        "status": "completed",
        "message": f"Saved tool positions - {slots}.",
        "saved": {str(i): {"x_cm": x, "y_cm": y} for i, (x, y) in sorted(taught.items())},
        "defaults_updated": changed,
        "mode": context.get("mode"),
    }
