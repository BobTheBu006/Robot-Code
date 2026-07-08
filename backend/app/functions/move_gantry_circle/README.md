# Move Gantry Circle

Traces a full circle with the CoreXY gantry around a given center position.

- `center_x_cm` / `center_y_cm`: absolute circle center in workspace cm.
- `radius_cm`: circle radius in cm; the whole circle must fit inside the calibrated workspace.
- `repeat_count`: number of full circles to trace before continuing.
- `speed_rpm`: target motor speed, ramped with `acceleration_rpm_per_s` over the whole lap when `trapezoidal_speed` is on.

The gantry first moves in a straight line to the circle start point (center X + radius, center Y),
then follows the circle counter-clockwise in ~0.5 mm chords and stops back at the start point. When
`repeat_count` is greater than 1, it repeats the full-circle move that many times.
Requires a prior Calibrate Gantry XY run. Any limit switch press stops the move immediately.

Serial protocol: `CIRCLEXY <centerXCm> <centerYCm> <radiusCm> <rpm> <trapezoidFlag> <accelerationRpmPerSecond>`,
completing with `OK CIRCLE XY`.
