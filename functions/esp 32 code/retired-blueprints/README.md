# Retired blueprints

Blueprints for functions that no longer run on an ESP32.

This folder deliberately does **not** start with `esp32 `, which is how
`Esp32BuilderService._workspace_dirs()` recognises a workspace - so nothing in
here is treated as a controller, regenerates a manifest, or gets flashed.

## calibrate_xy.json

The XY gantry moved to Raspberry Pi GPIO; `calibrate_xy` is executed by
`raspberry_gantry.py`, not by firmware. The blueprint stayed behind in the
`esp32 ttyUSB0` workspace, and because a blueprint's workspace decides its
`builder_board_id`, every sync regenerated the manifest as belonging to a board
called `ttyUSB0`.

That board no longer exists, so the reference was dangling. Worse, if a board
ever enumerated on `/dev/ttyUSB0` and got added to the Hardware Map under that
id again, `calibrate_xy` would have asked for it to be flashed with CoreXY
firmware - onto whichever controller happened to be on that port.

The manifest at `backend/app/functions/calibrate_xy/manifest.json` is complete
on its own and is now the source of truth for that block.
