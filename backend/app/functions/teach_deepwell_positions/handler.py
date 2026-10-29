"""Save the deepwell positions taught by hand in the editor's teach dialog."""

import json

from app.services.deepwell_positions import CORNER_NAMES, deepwell_position_store

MIN_CM, MAX_CM = -2.0, 120.0


def _taught(inputs: dict) -> dict[str, tuple[float, float]]:
    raw = inputs.get("positions") or {}
    if isinstance(raw, str):
        raw = json.loads(raw) if raw.strip() else {}
    taught = {}
    for name, position in raw.items():
        x_cm, y_cm = float(position["x_cm"]), float(position["y_cm"])
        for axis, value in (("X", x_cm), ("Y", y_cm)):
            if not MIN_CM <= value <= MAX_CM:
                raise ValueError(f"Well {name} {axis} = {value:.2f} cm is outside the machine.")
        taught[name.strip().upper()] = (x_cm, y_cm)
    return taught


def execute(context: dict, inputs: dict) -> dict:
    mode = str(inputs.get("mode") or "corners")
    taught = _taught(inputs)
    if not taught:
        return {"status": "completed", "message": "No deepwell positions were saved.", "saved": {}, "mode": context.get("mode")}

    if mode == "corners":
        deepwell_position_store.save_corners(taught)
        message = "Grid saved from corners " + ", ".join(CORNER_NAMES) + "; individual wells reset to the grid."
    else:
        deepwell_position_store.save_overrides(taught)
        message = f"Saved {len(taught)} individual well(s): " + ", ".join(sorted(taught)) + "."

    return {
        "status": "completed",
        "message": message,
        "saved": {name: {"x_cm": x, "y_cm": y} for name, (x, y) in sorted(taught.items())},
        "wells": deepwell_position_store.positions(),
        "mode": context.get("mode"),
    }
