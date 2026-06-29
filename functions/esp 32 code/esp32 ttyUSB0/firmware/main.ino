#include <Arduino.h>
#include <Preferences.h>

// Non-volatile storage so the X calibration (and last known position) survive
// the ESP32 auto-reset that happens each time the host opens the serial port.
Preferences gantryPrefs;

const int DEFAULT_STEPS_PER_REVOLUTION = 800;
const int STEP_PULSE_WIDTH_US = 20;
const float DEFAULT_XY_STEPS_PER_CM = 100.0f;
const float Z_STEPS_PER_CM = 100.0f;
const float DEFAULT_X_WORKSPACE_CM = 115.0f;
const float DEFAULT_Y_WORKSPACE_CM = 60.0f;
const float DEFAULT_Z_WORKSPACE_CM = 60.0f;
const float NEAR_LIMIT_CALIBRATION_CM = 3.0f;
const int SLOW_PROBE_RPM_FLOOR = 25;
const int DEFAULT_MAX_PROBE_ROTATIONS = 120;
const long XY_PROBE_BACKOFF_STEPS = 200;
const long XY_SLOW_PROBE_EXTRA_STEPS = 300;

// X-min homing refinement: after the fast touch, back off one full rotation
// (reversed direction) and re-approach the switch slowly for a repeatable home.
const int XY_SLOW_HOMING_RPM = 10;

// CoreXY X travel directions (dir-pin level applied to BOTH A and B motors).
// These reflect the current driver wiring; flip the two values together if the
// X axis is ever rewired.
const int XY_DIR_TOWARD_X_MIN = HIGH;
const int XY_DIR_TOWARD_X_MAX = LOW;

struct AxisChannel {
  int stepPin;
  int dirPin;
  int minLimitPin;
  int maxLimitPin;
  long currentSteps;
  float trackLengthCm;
};

AxisChannel xAxis = {16, 17, 21, 22, 0, DEFAULT_X_WORKSPACE_CM};
AxisChannel yAxis = {18, 19, 23, 25, 0, DEFAULT_Y_WORKSPACE_CM};
AxisChannel zLeftAxis = {32, 33, 12, 13, 0, DEFAULT_Z_WORKSPACE_CM};
AxisChannel zRightAxis = {32, 33, 12, 13, 0, DEFAULT_Z_WORKSPACE_CM};

long currentXSteps = 0;
long currentYSteps = 0;
float xStepsPerCm = DEFAULT_XY_STEPS_PER_CM;
float yStepsPerCm = DEFAULT_XY_STEPS_PER_CM;
int stepsPerRevolution = DEFAULT_STEPS_PER_REVOLUTION;

int xyLimitSwitchMode = 4;
int zLimitSwitchMode = 4;
bool xyCalibrated = false;
bool zCalibrated = false;

// Stepper driver ENABLE pins for the CoreXY A/B motors. -1 means "no enable pin
// wired" (driver is hardwired enabled), in which case all enable handling is a
// no-op. Most A4988/DRV8825/TMC carriers enable on a LOW level, so default to
// active-low.
int xEnablePin = -1;
int yEnablePin = -1;
bool xyMotorsEnableActiveLow = true;

void saveXCalibrationState() {
  gantryPrefs.begin("gantry", false);
  gantryPrefs.putBool("xyCal", xyCalibrated);
  gantryPrefs.putFloat("xStepsCm", xStepsPerCm);
  gantryPrefs.putFloat("xTrackCm", xAxis.trackLengthCm);
  gantryPrefs.putLong("xPos", currentXSteps);
  gantryPrefs.end();
}

void loadXCalibrationState() {
  gantryPrefs.begin("gantry", true);
  if (gantryPrefs.getBool("xyCal", false)) {
    xyCalibrated = true;
    xStepsPerCm = gantryPrefs.getFloat("xStepsCm", DEFAULT_XY_STEPS_PER_CM);
    xAxis.trackLengthCm = gantryPrefs.getFloat("xTrackCm", DEFAULT_X_WORKSPACE_CM);
    currentXSteps = gantryPrefs.getLong("xPos", 0);
  }
  gantryPrefs.end();

  Serial.print("X CALIBRATION RESTORED ");
  Serial.print(xyCalibrated ? 1 : 0);
  Serial.print(" STEPS_PER_CM ");
  Serial.print(xStepsPerCm, 3);
  Serial.print(" TRACK_CM ");
  Serial.print(xAxis.trackLengthCm, 3);
  Serial.print(" POS_STEPS ");
  Serial.println(currentXSteps);
}

int rpmForMoveProfile(const String &profile) {
  if (profile == "slow") {
    return 120;
  }
  if (profile == "fast") {
    return 420;
  }
  return 240;
}

int rpmForCalibrationProfile(const String &profile) {
  if (profile == "normal") {
    return 180;
  }
  return 100;
}

unsigned long stepIntervalMicrosForRPM(int rpm) {
  float stepsPerSecond = (rpm * stepsPerRevolution) / 60.0f;
  if (stepsPerSecond <= 0.0f) {
    stepsPerSecond = 1.0f;
  }

  unsigned long interval = (unsigned long)(1000000.0f / stepsPerSecond);
  unsigned long minimumInterval = (unsigned long)(STEP_PULSE_WIDTH_US * 2);
  if (interval < minimumInterval) {
    return minimumInterval;
  }

  return interval;
}

long rampIterationsForMotion(long totalIterations, int targetRpm, int accelerationRpmPerSecond) {
  if (totalIterations <= 2 || targetRpm <= 0 || accelerationRpmPerSecond <= 0) {
    return 0;
  }

  float rampSeconds = ((float)targetRpm) / ((float)accelerationRpmPerSecond);
  float targetStepsPerSecond = (targetRpm * stepsPerRevolution) / 60.0f;
  long rampIterations = (long)((targetStepsPerSecond * rampSeconds) / 2.0f);
  if (rampIterations < 1) {
    return 1;
  }

  long maxRamp = totalIterations / 2;
  return rampIterations > maxRamp ? maxRamp : rampIterations;
}

int rpmForTrapezoidIteration(long iteration, long totalIterations, int targetRpm, bool trapezoidalSpeed, int accelerationRpmPerSecond) {
  if (!trapezoidalSpeed) {
    return targetRpm;
  }

  long rampIterations = rampIterationsForMotion(totalIterations, targetRpm, accelerationRpmPerSecond);
  if (rampIterations <= 0) {
    return targetRpm;
  }

  long remaining = totalIterations - iteration - 1;
  long rampPosition = min(iteration + 1, remaining + 1);
  if (rampPosition >= rampIterations) {
    return targetRpm;
  }

  float rampFraction = ((float)rampPosition) / ((float)rampIterations);
  int nextRpm = (int)(targetRpm * rampFraction);
  return max(10, min(targetRpm, nextRpm));
}

void prepareOutputPin(int pin) {
  if (pin < 0) {
    return;
  }

  pinMode(pin, OUTPUT);
  digitalWrite(pin, LOW);
}

void prepareLimitPin(int pin) {
  if (pin < 0) {
    return;
  }

  pinMode(pin, INPUT_PULLUP);
}

void writeEnablePin(int pin, bool enabled) {
  if (pin < 0) {
    return;
  }

  // When the driver enables on a LOW level, "enabled" must drive the pin LOW.
  bool driveHigh = enabled ? !xyMotorsEnableActiveLow : xyMotorsEnableActiveLow;
  digitalWrite(pin, driveHigh ? HIGH : LOW);
}

void setXYMotorsEnabled(bool enabled) {
  writeEnablePin(xEnablePin, enabled);
  writeEnablePin(yEnablePin, enabled);
}

void applyXYEnable(int nextAEnablePin, int nextBEnablePin, bool activeLow) {
  xEnablePin = nextAEnablePin;
  yEnablePin = nextBEnablePin;
  xyMotorsEnableActiveLow = activeLow;
  prepareOutputPin(xEnablePin);
  prepareOutputPin(yEnablePin);
  // Energize both CoreXY drivers immediately so single-axis moves still turn
  // both motors. A CoreXY axis requires both A and B drivers enabled.
  setXYMotorsEnabled(true);

  Serial.print("OK XY ENABLE ");
  Serial.print(xEnablePin);
  Serial.print(" ");
  Serial.print(yEnablePin);
  Serial.print(" ");
  Serial.println(xyMotorsEnableActiveLow ? 1 : 0);
}

bool isLimitActive(int pin) {
  return pin >= 0 && digitalRead(pin) == LOW;
}

bool consumeStopCommandIfPresent() {
  if (!Serial.available()) {
    return false;
  }

  String pending = Serial.readStringUntil('\n');
  pending.trim();
  pending.toUpperCase();
  if (pending == "STOP") {
    Serial.println("OK STOP");
    return true;
  }

  return false;
}

bool axisLimitActive(const AxisChannel &axis, bool positiveDirection, int limitMode) {
  if (positiveDirection) {
    return limitMode == 4 && isLimitActive(axis.maxLimitPin);
  }

  return isLimitActive(axis.minLimitPin);
}

bool cartesianLimitActiveForMove(long deltaX, long deltaY) {
  if (deltaX > 0 && xyLimitSwitchMode == 4 && isLimitActive(xAxis.maxLimitPin)) {
    return true;
  }
  if (deltaX < 0 && isLimitActive(xAxis.minLimitPin)) {
    return true;
  }
  if (deltaY > 0 && xyLimitSwitchMode == 4 && isLimitActive(yAxis.maxLimitPin)) {
    return true;
  }
  if (deltaY < 0 && isLimitActive(yAxis.minLimitPin)) {
    return true;
  }
  return false;
}

void applyAxisPins(AxisChannel &axis, int stepPin, int dirPin) {
  axis.stepPin = stepPin;
  axis.dirPin = dirPin;
  prepareOutputPin(axis.stepPin);
  prepareOutputPin(axis.dirPin);
}

void applyAxisLimits(AxisChannel &axis, int minLimitPin, int maxLimitPin, int limitMode) {
  axis.minLimitPin = minLimitPin;
  axis.maxLimitPin = maxLimitPin;
  prepareLimitPin(axis.minLimitPin);
  if (limitMode == 4) {
    prepareLimitPin(axis.maxLimitPin);
  }
}

long cmToSteps(float centimeters, float stepsPerCm) {
  return lroundf(centimeters * stepsPerCm);
}

float stepsToCm(long steps, float stepsPerCm) {
  return ((float)steps) / stepsPerCm;
}

bool runDualAxisMove(
  AxisChannel &firstAxis,
  AxisChannel &secondAxis,
  long firstTargetDeltaSteps,
  long secondTargetDeltaSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  int limitMode,
  bool useLimitChecks,
  bool &firstBlocked,
  bool &secondBlocked,
  bool &stopRequested
) {
  long absFirst = labs(firstTargetDeltaSteps);
  long absSecond = labs(secondTargetDeltaSteps);
  long totalIterations = max(absFirst, absSecond);

  bool firstPositive = firstTargetDeltaSteps >= 0;
  bool secondPositive = secondTargetDeltaSteps >= 0;

  digitalWrite(firstAxis.dirPin, firstPositive ? HIGH : LOW);
  digitalWrite(secondAxis.dirPin, secondPositive ? HIGH : LOW);
  delayMicroseconds(20);

  if (totalIterations == 0) {
    firstBlocked = false;
    secondBlocked = false;
    stopRequested = false;
    return true;
  }

  long accumulatorFirst = 0;
  long accumulatorSecond = 0;
  firstBlocked = false;
  secondBlocked = false;
  stopRequested = false;

  for (long iteration = 0; iteration < totalIterations; iteration++) {
    if (consumeStopCommandIfPresent()) {
      stopRequested = true;
      return false;
    }

    bool stepFirst = false;
    bool stepSecond = false;

    accumulatorFirst += absFirst;
    if (!firstBlocked && absFirst > 0 && accumulatorFirst >= totalIterations) {
      accumulatorFirst -= totalIterations;
      if (useLimitChecks && axisLimitActive(firstAxis, firstPositive, limitMode)) {
        firstBlocked = true;
      } else {
        stepFirst = true;
      }
    }

    accumulatorSecond += absSecond;
    if (!secondBlocked && absSecond > 0 && accumulatorSecond >= totalIterations) {
      accumulatorSecond -= totalIterations;
      if (useLimitChecks && axisLimitActive(secondAxis, secondPositive, limitMode)) {
        secondBlocked = true;
      } else {
        stepSecond = true;
      }
    }

    if (stepFirst) {
      digitalWrite(firstAxis.stepPin, HIGH);
    }
    if (stepSecond) {
      digitalWrite(secondAxis.stepPin, HIGH);
    }

    if (stepFirst || stepSecond) {
      delayMicroseconds(STEP_PULSE_WIDTH_US);
    }

    if (stepFirst) {
      digitalWrite(firstAxis.stepPin, LOW);
      firstAxis.currentSteps += firstPositive ? 1 : -1;
    }
    if (stepSecond) {
      digitalWrite(secondAxis.stepPin, LOW);
      secondAxis.currentSteps += secondPositive ? 1 : -1;
    }

    if (stepFirst || stepSecond) {
      int activeRpm = rpmForTrapezoidIteration(
        iteration,
        totalIterations,
        rpm,
        trapezoidalSpeed,
        accelerationRpmPerSecond
      );
      unsigned long intervalMicros = stepIntervalMicrosForRPM(activeRpm);
      unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
        ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
        : (unsigned long)STEP_PULSE_WIDTH_US;
      delayMicroseconds(lowTimeMicros);
    }
  }

  return !(firstBlocked || secondBlocked);
}

bool runCoreXYCartesianMove(
  long deltaXSteps,
  long deltaYSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool useLimitChecks,
  bool &xBlocked,
  bool &yBlocked,
  bool &stopRequested
) {
  long deltaA = deltaXSteps + deltaYSteps;
  long deltaB = deltaXSteps - deltaYSteps;
  long absA = labs(deltaA);
  long absB = labs(deltaB);
  long totalIterations = max(absA, absB);
  bool aPositive = deltaA >= 0;
  bool bPositive = deltaB >= 0;
  int xSign = deltaXSteps > 0 ? 1 : deltaXSteps < 0 ? -1 : 0;
  int ySign = deltaYSteps > 0 ? 1 : deltaYSteps < 0 ? -1 : 0;

  digitalWrite(xAxis.dirPin, aPositive ? HIGH : LOW);
  digitalWrite(yAxis.dirPin, bPositive ? HIGH : LOW);
  delayMicroseconds(20);

  xBlocked = false;
  yBlocked = false;
  stopRequested = false;

  if (totalIterations == 0) {
    return true;
  }

  long accumulatorA = 0;
  long accumulatorB = 0;
  long accumulatorX = 0;
  long accumulatorY = 0;
  long absX = labs(deltaXSteps);
  long absY = labs(deltaYSteps);

  for (long iteration = 0; iteration < totalIterations; iteration++) {
    if (consumeStopCommandIfPresent()) {
      stopRequested = true;
      return false;
    }

    if (useLimitChecks) {
      if (xSign > 0 && xyLimitSwitchMode == 4 && isLimitActive(xAxis.maxLimitPin)) {
        xBlocked = true;
      }
      if (xSign < 0 && isLimitActive(xAxis.minLimitPin)) {
        xBlocked = true;
      }
      if (ySign > 0 && xyLimitSwitchMode == 4 && isLimitActive(yAxis.maxLimitPin)) {
        yBlocked = true;
      }
      if (ySign < 0 && isLimitActive(yAxis.minLimitPin)) {
        yBlocked = true;
      }
      if ((xBlocked && xSign != 0) || (yBlocked && ySign != 0)) {
        return false;
      }
    }

    bool stepA = false;
    bool stepB = false;

    accumulatorA += absA;
    if (absA > 0 && accumulatorA >= totalIterations) {
      accumulatorA -= totalIterations;
      stepA = true;
    }

    accumulatorB += absB;
    if (absB > 0 && accumulatorB >= totalIterations) {
      accumulatorB -= totalIterations;
      stepB = true;
    }

    if (stepA) {
      digitalWrite(xAxis.stepPin, HIGH);
    }
    if (stepB) {
      digitalWrite(yAxis.stepPin, HIGH);
    }
    if (stepA || stepB) {
      delayMicroseconds(STEP_PULSE_WIDTH_US);
    }
    if (stepA) {
      digitalWrite(xAxis.stepPin, LOW);
      xAxis.currentSteps += aPositive ? 1 : -1;
    }
    if (stepB) {
      digitalWrite(yAxis.stepPin, LOW);
      yAxis.currentSteps += bPositive ? 1 : -1;
    }

    accumulatorX += absX;
    if (absX > 0 && accumulatorX >= totalIterations) {
      accumulatorX -= totalIterations;
      currentXSteps += xSign;
    }
    accumulatorY += absY;
    if (absY > 0 && accumulatorY >= totalIterations) {
      accumulatorY -= totalIterations;
      currentYSteps += ySign;
    }

    if (stepA || stepB) {
      int activeRpm = rpmForTrapezoidIteration(
        iteration,
        totalIterations,
        rpm,
        trapezoidalSpeed,
        accelerationRpmPerSecond
      );
      unsigned long intervalMicros = stepIntervalMicrosForRPM(activeRpm);
      unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
        ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
        : (unsigned long)STEP_PULSE_WIDTH_US;
      delayMicroseconds(lowTimeMicros);
    }
  }

  return true;
}

void applyXYPins(int nextXStepPin, int nextXDirPin, int nextYStepPin, int nextYDirPin) {
  applyAxisPins(xAxis, nextXStepPin, nextXDirPin);
  applyAxisPins(yAxis, nextYStepPin, nextYDirPin);

  Serial.print("OK XY PINS ");
  Serial.print(xAxis.stepPin);
  Serial.print(" ");
  Serial.print(xAxis.dirPin);
  Serial.print(" ");
  Serial.print(yAxis.stepPin);
  Serial.print(" ");
  Serial.println(yAxis.dirPin);
}

void applyXYLimits(
  int nextLimitMode,
  int nextXMinLimitPin,
  int nextXMaxLimitPin,
  int nextYMinLimitPin,
  int nextYMaxLimitPin
) {
  xyLimitSwitchMode = nextLimitMode == 2 ? 2 : 4;
  applyAxisLimits(xAxis, nextXMinLimitPin, nextXMaxLimitPin, xyLimitSwitchMode);
  applyAxisLimits(yAxis, nextYMinLimitPin, nextYMaxLimitPin, xyLimitSwitchMode);

  Serial.print("OK XY LIMITS ");
  Serial.print(xyLimitSwitchMode);
  Serial.print(" ");
  Serial.print(xAxis.minLimitPin);
  Serial.print(" ");
  Serial.print(xAxis.maxLimitPin);
  Serial.print(" ");
  Serial.print(yAxis.minLimitPin);
  Serial.print(" ");
  Serial.println(yAxis.maxLimitPin);
}

void applyZPins(int nextLeftStepPin, int nextLeftDirPin, int nextRightStepPin, int nextRightDirPin) {
  applyAxisPins(zLeftAxis, nextLeftStepPin, nextLeftDirPin);
  applyAxisPins(zRightAxis, nextRightStepPin, nextRightDirPin);

  Serial.print("OK Z PINS ");
  Serial.print(zLeftAxis.stepPin);
  Serial.print(" ");
  Serial.print(zLeftAxis.dirPin);
  Serial.print(" ");
  Serial.print(zRightAxis.stepPin);
  Serial.print(" ");
  Serial.println(zRightAxis.dirPin);
}

void applyZLimits(
  int nextLimitMode,
  int nextLeftMinLimitPin,
  int nextLeftMaxLimitPin,
  int nextRightMinLimitPin,
  int nextRightMaxLimitPin
) {
  zLimitSwitchMode = nextLimitMode == 2 ? 2 : 4;
  applyAxisLimits(zLeftAxis, nextLeftMinLimitPin, nextLeftMaxLimitPin, zLimitSwitchMode);
  applyAxisLimits(zRightAxis, nextRightMinLimitPin, nextRightMaxLimitPin, zLimitSwitchMode);

  Serial.print("OK Z LIMITS ");
  Serial.print(zLimitSwitchMode);
  Serial.print(" ");
  Serial.print(zLeftAxis.minLimitPin);
  Serial.print(" ");
  Serial.print(zLeftAxis.maxLimitPin);
  Serial.print(" ");
  Serial.print(zRightAxis.minLimitPin);
  Serial.print(" ");
  Serial.println(zRightAxis.maxLimitPin);
}

bool moveXYTo(float targetXCm, float targetYCm, int rpm, bool trapezoidalSpeed, int accelerationRpmPerSecond) {
  if (xyCalibrated) {
    if (targetXCm < 0.0f || targetXCm > xAxis.trackLengthCm || targetYCm < 0.0f || targetYCm > yAxis.trackLengthCm) {
      Serial.println("ERR XY TARGET RANGE");
      return false;
    }
  }

  long targetXSteps = cmToSteps(targetXCm, xStepsPerCm);
  long targetYSteps = cmToSteps(targetYCm, yStepsPerCm);
  long deltaX = targetXSteps - currentXSteps;
  long deltaY = targetYSteps - currentYSteps;
  bool xBlocked = false;
  bool yBlocked = false;
  bool stopRequested = false;

  Serial.print("ACTIVE XY RPM ");
  Serial.print(rpm);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);
  Serial.print("TARGET COREXY CM ");
  Serial.print(targetXCm, 3);
  Serial.print(" ");
  Serial.println(targetYCm, 3);

  setXYMotorsEnabled(true);

  bool moved = runCoreXYCartesianMove(
    deltaX,
    deltaY,
    rpm,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    true,
    xBlocked,
    yBlocked,
    stopRequested
  );

  if (moved) {
    currentXSteps = targetXSteps;
    currentYSteps = targetYSteps;
  }

  Serial.print("COREXY MOTOR POSITION STEPS ");
  Serial.print(xAxis.currentSteps);
  Serial.print(" ");
  Serial.println(yAxis.currentSteps);
  Serial.print("XY CARTESIAN POSITION STEPS ");
  Serial.print(currentXSteps);
  Serial.print(" ");
  Serial.println(currentYSteps);

  if (!moved) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR ESTOP XY LIMIT ");
    if (xBlocked && yBlocked) {
      Serial.println("X,Y");
    } else if (xBlocked) {
      Serial.println("X");
    } else {
      Serial.println("Y");
    }
    return false;
  }

  Serial.println("OK MOVE XY");
  return true;
}

bool maybeCheckZOnlyOnTheFlyCalibration(
  float targetLeftCm,
  float targetRightCm,
  bool onTheFlyCalibration,
  int maxDiffSteps,
  int rpm,
  int accelerationRpmPerSecond
);
bool probeCoreXYLimit(
  char axis,
  bool positiveDirection,
  long maxProbeSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &stopRequested
);
bool probeZLimit(
  bool positiveDirection,
  long leftExpectedTravelSteps,
  long rightExpectedTravelSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &stopRequested
);
bool calibrateXY(
  float xTrackLengthCm,
  int calibrationRPM,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  int nextStepsPerRotation,
  int maxProbeRotations
);
bool calibrateZ(float leftTrackLengthCm, float rightTrackLengthCm, int calibrationRPM, bool trapezoidalSpeed, int accelerationRpmPerSecond);

bool moveZTo(float targetLeftCm, float targetRightCm, int rpm, bool trapezoidalSpeed, int accelerationRpmPerSecond, bool onTheFlyCalibration, int maxDiffSteps) {
  if (zCalibrated) {
    if (
      targetLeftCm < 0.0f || targetLeftCm > zLeftAxis.trackLengthCm
      || targetRightCm < 0.0f || targetRightCm > zRightAxis.trackLengthCm
    ) {
      Serial.println("ERR Z TARGET RANGE");
      return false;
    }
  }

  long targetLeftSteps = cmToSteps(targetLeftCm, Z_STEPS_PER_CM);
  long targetRightSteps = cmToSteps(targetRightCm, Z_STEPS_PER_CM);
  long deltaLeft = targetLeftSteps - zLeftAxis.currentSteps;
  long deltaRight = targetRightSteps - zRightAxis.currentSteps;
  bool singleZMotor = zLeftAxis.stepPin == zRightAxis.stepPin && zLeftAxis.dirPin == zRightAxis.dirPin;
  bool leftBlocked = false;
  bool rightBlocked = false;
  bool stopRequested = false;

  Serial.print("ACTIVE Z RPM ");
  Serial.print(rpm);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);
  Serial.print("TARGET Z CM ");
  Serial.print(targetLeftCm, 3);
  Serial.print(" ");
  Serial.println(targetRightCm, 3);

  bool moved = runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    deltaLeft,
    singleZMotor ? 0 : deltaRight,
    rpm,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    true,
    leftBlocked,
    rightBlocked,
    stopRequested
  );

  if (singleZMotor) {
    zRightAxis.currentSteps = zLeftAxis.currentSteps;
  }

  Serial.print("Z POSITION STEPS ");
  Serial.print(zLeftAxis.currentSteps);
  Serial.print(" ");
  Serial.println(zRightAxis.currentSteps);

  if (!moved) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR ESTOP Z LIMIT ");
    if (leftBlocked && rightBlocked) {
      Serial.println("LEFT,RIGHT");
    } else if (leftBlocked) {
      Serial.println("LEFT");
    } else {
      Serial.println("RIGHT");
    }
    return false;
  }

  if (!maybeCheckZOnlyOnTheFlyCalibration(targetLeftCm, targetRightCm, onTheFlyCalibration, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }

  Serial.println("OK MOVE Z");
  return true;
}

bool checkCoreXYAxisCalibration(
  char axis,
  bool positiveLimit,
  long expectedLimitSteps,
  long returnXSteps,
  long returnYSteps,
  int maxDiffSteps,
  int rpm,
  int accelerationRpmPerSecond
) {
  bool stopRequested = false;
  long beforeSteps = axis == 'X' ? currentXSteps : currentYSteps;
  long travelToLimit = labs(expectedLimitSteps - beforeSteps) + 500;
  if (!probeCoreXYLimit(axis, positiveLimit, travelToLimit, slowProbeRpmFor(rpm), true, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP ON THE FLY XY" : "ERR ON THE FLY XY PROBE");
    return false;
  }

  long observedSteps = axis == 'X' ? currentXSteps : currentYSteps;
  long diffSteps = labs(observedSteps - expectedLimitSteps);
  Serial.print("ON THE FLY XY DIFF ");
  Serial.print(axis);
  Serial.print(" ");
  Serial.println(diffSteps);

  if (diffSteps > maxDiffSteps) {
    Serial.println("ON THE FLY XY RECALIBRATE");
    if (!calibrateXY(
      xAxis.trackLengthCm,
      slowProbeRpmFor(rpm),
      true,
      accelerationRpmPerSecond,
      stepsPerRevolution,
      DEFAULT_MAX_PROBE_ROTATIONS
    )) {
      return false;
    }
  }

  bool ignoredX = false;
  bool ignoredY = false;
  bool returnStop = false;
  runCoreXYCartesianMove(
    returnXSteps - currentXSteps,
    returnYSteps - currentYSteps,
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    true,
    ignoredX,
    ignoredY,
    returnStop
  );
  if (returnStop) {
    return false;
  }
  currentXSteps = returnXSteps;
  currentYSteps = returnYSteps;
  return true;
}

bool checkZCalibrationNearLimit(
  bool positiveLimit,
  long expectedLeftSteps,
  long expectedRightSteps,
  long returnLeftSteps,
  long returnRightSteps,
  int maxDiffSteps,
  int rpm,
  int accelerationRpmPerSecond
) {
  bool stopRequested = false;
  long travelLeft = labs(expectedLeftSteps - zLeftAxis.currentSteps);
  long travelRight = labs(expectedRightSteps - zRightAxis.currentSteps);
  if (!probeZLimit(positiveLimit, travelLeft, travelRight, slowProbeRpmFor(rpm), true, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP ON THE FLY Z" : "ERR ON THE FLY Z PROBE");
    return false;
  }

  long diffLeft = labs(zLeftAxis.currentSteps - expectedLeftSteps);
  long diffRight = labs(zRightAxis.currentSteps - expectedRightSteps);
  Serial.print("ON THE FLY Z DIFF ");
  Serial.print(diffLeft);
  Serial.print(" ");
  Serial.println(diffRight);

  if (diffLeft > maxDiffSteps || diffRight > maxDiffSteps) {
    Serial.println("ON THE FLY Z RECALIBRATE");
    if (!calibrateZ(zLeftAxis.trackLengthCm, zRightAxis.trackLengthCm, slowProbeRpmFor(rpm), true, accelerationRpmPerSecond)) {
      return false;
    }
  }

  bool ignoredLeft = false;
  bool ignoredRight = false;
  bool returnStop = false;
  runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    returnLeftSteps - zLeftAxis.currentSteps,
    returnRightSteps - zRightAxis.currentSteps,
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    true,
    ignoredLeft,
    ignoredRight,
    returnStop
  );
  return !returnStop;
}

bool maybeCheckOnTheFlyCalibration(
  float targetXCm,
  float targetYCm,
  float targetZCm,
  bool onTheFlyCalibration,
  int maxDiffSteps,
  int rpm,
  int accelerationRpmPerSecond
) {
  if (!onTheFlyCalibration) {
    return true;
  }

  long returnXSteps = cmToSteps(targetXCm, xStepsPerCm);
  long returnYSteps = cmToSteps(targetYCm, yStepsPerCm);
  long returnZSteps = cmToSteps(targetZCm, Z_STEPS_PER_CM);
  long nearXSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, xStepsPerCm);
  long nearYSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, yStepsPerCm);
  long nearZSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, Z_STEPS_PER_CM);
  long xMaxSteps = cmToSteps(xAxis.trackLengthCm, xStepsPerCm);
  long yMaxSteps = cmToSteps(yAxis.trackLengthCm, yStepsPerCm);
  long zLeftMaxSteps = cmToSteps(zLeftAxis.trackLengthCm, Z_STEPS_PER_CM);
  long zRightMaxSteps = cmToSteps(zRightAxis.trackLengthCm, Z_STEPS_PER_CM);

  if (returnXSteps <= nearXSteps && !checkCoreXYAxisCalibration('X', false, 0, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (xMaxSteps - returnXSteps <= nearXSteps && !checkCoreXYAxisCalibration('X', true, xMaxSteps, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (returnYSteps <= nearYSteps && !checkCoreXYAxisCalibration('Y', false, 0, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (yMaxSteps - returnYSteps <= nearYSteps && !checkCoreXYAxisCalibration('Y', true, yMaxSteps, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (returnZSteps <= nearZSteps && !checkZCalibrationNearLimit(false, 0, 0, returnZSteps, returnZSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (zLeftMaxSteps - returnZSteps <= nearZSteps && !checkZCalibrationNearLimit(true, zLeftMaxSteps, zRightMaxSteps, returnZSteps, returnZSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }

  return true;
}

bool maybeCheckZOnlyOnTheFlyCalibration(
  float targetLeftCm,
  float targetRightCm,
  bool onTheFlyCalibration,
  int maxDiffSteps,
  int rpm,
  int accelerationRpmPerSecond
) {
  if (!onTheFlyCalibration) {
    return true;
  }

  long returnLeftSteps = cmToSteps(targetLeftCm, Z_STEPS_PER_CM);
  long returnRightSteps = cmToSteps(targetRightCm, Z_STEPS_PER_CM);
  long nearZSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, Z_STEPS_PER_CM);
  long zLeftMaxSteps = cmToSteps(zLeftAxis.trackLengthCm, Z_STEPS_PER_CM);
  long zRightMaxSteps = cmToSteps(zRightAxis.trackLengthCm, Z_STEPS_PER_CM);

  if ((returnLeftSteps <= nearZSteps || returnRightSteps <= nearZSteps)
    && !checkZCalibrationNearLimit(false, 0, 0, returnLeftSteps, returnRightSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }

  if ((zLeftMaxSteps - returnLeftSteps <= nearZSteps || zRightMaxSteps - returnRightSteps <= nearZSteps)
    && !checkZCalibrationNearLimit(true, zLeftMaxSteps, zRightMaxSteps, returnLeftSteps, returnRightSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }

  return true;
}

bool moveXYZTo(float targetXCm, float targetYCm, float targetZCm, int rpm, bool trapezoidalSpeed, int accelerationRpmPerSecond, bool onTheFlyCalibration, int maxDiffSteps) {
  if (!moveXYTo(targetXCm, targetYCm, rpm, trapezoidalSpeed, accelerationRpmPerSecond)) {
    return false;
  }
  if (!moveZTo(targetZCm, targetZCm, rpm, trapezoidalSpeed, accelerationRpmPerSecond, false, maxDiffSteps)) {
    return false;
  }
  if (!maybeCheckOnTheFlyCalibration(targetXCm, targetYCm, targetZCm, onTheFlyCalibration, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  Serial.println("OK MOVE XYZ");
  return true;
}

bool homeAxesToMinimum(
  AxisChannel &firstAxis,
  AxisChannel &secondAxis,
  int limitMode,
  long firstMaxSteps,
  long secondMaxSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &firstHomed,
  bool &secondHomed,
  bool &stopRequested
) {
  long firstTravel = -labs(firstMaxSteps);
  long secondTravel = -labs(secondMaxSteps);
  bool firstBlocked = false;
  bool secondBlocked = false;
  stopRequested = false;

  runDualAxisMove(
    firstAxis,
    secondAxis,
    firstTravel,
    secondTravel,
    rpm,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    limitMode,
    true,
    firstBlocked,
    secondBlocked,
    stopRequested
  );

  if (stopRequested) {
    return false;
  }

  firstHomed = firstBlocked || isLimitActive(firstAxis.minLimitPin);
  secondHomed = secondBlocked || isLimitActive(secondAxis.minLimitPin);
  if (firstHomed) {
    firstAxis.currentSteps = 0;
  }
  if (secondHomed) {
    secondAxis.currentSteps = 0;
  }

  return firstHomed && secondHomed;
}

int slowProbeRpmFor(int rpm) {
  return max(SLOW_PROBE_RPM_FLOOR, rpm / 3);
}

bool probeCoreXYLimit(
  char axis,
  bool positiveDirection,
  long maxProbeSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &stopRequested
) {
  long travel = max(1L, labs(maxProbeSteps));
  long xDelta = axis == 'X' ? (positiveDirection ? travel : -travel) : 0;
  long yDelta = axis == 'Y' ? (positiveDirection ? travel : -travel) : 0;
  bool xBlocked = false;
  bool yBlocked = false;
  stopRequested = false;

  runCoreXYCartesianMove(
    xDelta,
    yDelta,
    rpm,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    true,
    xBlocked,
    yBlocked,
    stopRequested
  );
  if (stopRequested) {
    return false;
  }
  if ((axis == 'X' && !xBlocked) || (axis == 'Y' && !yBlocked)) {
    return false;
  }

  bool ignoredX = false;
  bool ignoredY = false;
  bool backoffStop = false;
  runCoreXYCartesianMove(
    axis == 'X' ? (positiveDirection ? -XY_PROBE_BACKOFF_STEPS : XY_PROBE_BACKOFF_STEPS) : 0,
    axis == 'Y' ? (positiveDirection ? -XY_PROBE_BACKOFF_STEPS : XY_PROBE_BACKOFF_STEPS) : 0,
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    false,
    ignoredX,
    ignoredY,
    backoffStop
  );
  if (backoffStop) {
    stopRequested = true;
    return false;
  }

  xBlocked = false;
  yBlocked = false;
  runCoreXYCartesianMove(
    axis == 'X'
      ? (positiveDirection ? XY_PROBE_BACKOFF_STEPS + XY_SLOW_PROBE_EXTRA_STEPS : -(XY_PROBE_BACKOFF_STEPS + XY_SLOW_PROBE_EXTRA_STEPS))
      : 0,
    axis == 'Y'
      ? (positiveDirection ? XY_PROBE_BACKOFF_STEPS + XY_SLOW_PROBE_EXTRA_STEPS : -(XY_PROBE_BACKOFF_STEPS + XY_SLOW_PROBE_EXTRA_STEPS))
      : 0,
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    true,
    xBlocked,
    yBlocked,
    stopRequested
  );
  if (stopRequested) {
    return false;
  }

  return (axis == 'X' && xBlocked) || (axis == 'Y' && yBlocked);
}

void printXYLimitState(const char *label) {
  Serial.print("XY LIMIT STATE ");
  Serial.print(label);
  Serial.print(" X_MIN ");
  Serial.print(isLimitActive(xAxis.minLimitPin) ? 1 : 0);
  Serial.print(" X_MAX ");
  Serial.print(isLimitActive(xAxis.maxLimitPin) ? 1 : 0);
  Serial.print(" Y_MIN ");
  Serial.print(isLimitActive(yAxis.minLimitPin) ? 1 : 0);
  Serial.print(" Y_MAX ");
  Serial.println(isLimitActive(yAxis.maxLimitPin) ? 1 : 0);
}

void printXYMotorPinState(const char *label) {
  Serial.print("XY MOTOR PINS ");
  Serial.print(label);
  Serial.print(" A_STEP ");
  Serial.print(xAxis.stepPin);
  Serial.print(" A_DIR ");
  Serial.print(xAxis.dirPin);
  Serial.print(" B_STEP ");
  Serial.print(yAxis.stepPin);
  Serial.print(" B_DIR ");
  Serial.println(yAxis.dirPin);
}

void printXYProbeFailure(const char *limitName, int limitPin, long maxProbeSteps, bool stopRequested) {
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return;
  }

  Serial.print("ERR XY ");
  Serial.print(limitName);
  Serial.print(" SAFETY_STEPS ");
  Serial.print(maxProbeSteps);
  Serial.print(" LIMIT_PIN ");
  Serial.print(limitPin);
  Serial.print(" LIMIT_ACTIVE ");
  Serial.println(isLimitActive(limitPin) ? 1 : 0);
}

bool probeZLimit(
  bool positiveDirection,
  long leftExpectedTravelSteps,
  long rightExpectedTravelSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &stopRequested
) {
  long leftTravel = labs(leftExpectedTravelSteps) + 500;
  long rightTravel = labs(rightExpectedTravelSteps) + 500;
  bool leftBlocked = false;
  bool rightBlocked = false;
  stopRequested = false;

  runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    positiveDirection ? leftTravel : -leftTravel,
    positiveDirection ? rightTravel : -rightTravel,
    rpm,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    true,
    leftBlocked,
    rightBlocked,
    stopRequested
  );
  if (stopRequested || !(leftBlocked && rightBlocked)) {
    return false;
  }

  long backoff = 200;
  bool ignoredLeft = false;
  bool ignoredRight = false;
  bool backoffStop = false;
  runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    positiveDirection ? -backoff : backoff,
    positiveDirection ? -backoff : backoff,
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    false,
    ignoredLeft,
    ignoredRight,
    backoffStop
  );
  if (backoffStop) {
    stopRequested = true;
    return false;
  }

  leftBlocked = false;
  rightBlocked = false;
  runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    positiveDirection ? backoff + 300 : -(backoff + 300),
    positiveDirection ? backoff + 300 : -(backoff + 300),
    slowProbeRpmFor(rpm),
    true,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    true,
    leftBlocked,
    rightBlocked,
    stopRequested
  );

  return !stopRequested && leftBlocked && rightBlocked;
}

// Steps both CoreXY motors along X in the given direction.
//  - dirLevel: dir-pin level for the travel direction (applied to A and B).
//  - positionStep: +1/-1 applied to the X position counters per step.
//  - stopLimitPin: if >= 0, halts the instant this switch is active (checked
//    before each step). Pass -1 for a fixed-distance move with no limit check.
// Returns true if it stepped the full `maxSteps` count. Sets limitHit if it
// stopped early on the limit switch, or stopRequested if a STOP arrived.
bool driveXAxis(
  int rpm,
  long maxSteps,
  int dirLevel,
  int positionStep,
  int stopLimitPin,
  long &stepsTaken,
  bool &stopRequested,
  bool &limitHit
) {
  digitalWrite(xAxis.dirPin, dirLevel);
  digitalWrite(yAxis.dirPin, dirLevel);
  delayMicroseconds(20);

  unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
  unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
    ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
    : (unsigned long)STEP_PULSE_WIDTH_US;

  stepsTaken = 0;
  stopRequested = false;
  limitHit = false;
  for (long step = 0; step < maxSteps; step++) {
    if (consumeStopCommandIfPresent()) {
      stopRequested = true;
      return false;
    }
    if (stopLimitPin >= 0 && isLimitActive(stopLimitPin)) {
      limitHit = true;
      return false;
    }

    digitalWrite(xAxis.stepPin, HIGH);
    digitalWrite(yAxis.stepPin, HIGH);
    delayMicroseconds(STEP_PULSE_WIDTH_US);
    digitalWrite(xAxis.stepPin, LOW);
    digitalWrite(yAxis.stepPin, LOW);

    xAxis.currentSteps += positionStep;
    yAxis.currentSteps += positionStep;
    currentXSteps += positionStep;
    stepsTaken++;

    delayMicroseconds(lowTimeMicros);
  }

  return true;
}

// Three-pass homing against one X limit switch: fast touch, back off one full
// rotation, then slow re-touch. Leaves the carriage resting on the switch.
//  - dirToward: dir-pin level that drives toward this switch.
//  - dirAway: the opposite level (for the back-off).
//  - towardStep / awayStep: position-counter deltas for each direction.
// Returns true on success; on failure prints the reason and returns false.
bool homeXAgainstSwitch(
  const char *limitName,
  int limitPin,
  int dirToward,
  int dirAway,
  int towardStep,
  int awayStep,
  int calibrationRPM,
  long maxProbeSteps,
  long &fastSteps,
  long &slowSteps
) {
  bool stopRequested = false;
  bool limitHit = false;
  long ignoredSteps = 0;

  // Fast touch: drive toward the switch until it trips.
  driveXAxis(calibrationRPM, maxProbeSteps, dirToward, towardStep, limitPin, fastSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }
  if (!limitHit) {
    printXYProbeFailure(limitName, limitPin, maxProbeSteps, false);
    return false;
  }

  // Back off one full rotation (reversed direction) to release the switch.
  long backoffSteps = stepsPerRevolution;
  driveXAxis(calibrationRPM, backoffSteps, dirAway, awayStep, -1, ignoredSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }

  // Slow re-touch (reversed direction again), capped a bit past the back-off.
  long slowTravelCap = backoffSteps * 2;
  driveXAxis(XY_SLOW_HOMING_RPM, slowTravelCap, dirToward, towardStep, limitPin, slowSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }
  if (!limitHit) {
    printXYProbeFailure(limitName, limitPin, slowTravelCap, false);
    return false;
  }

  return true;
}

bool calibrateXY(
  float xTrackLengthCm,
  int calibrationRPM,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  int nextStepsPerRotation,
  int maxProbeRotations
) {
  stepsPerRevolution = max(1, nextStepsPerRotation);
  int safeMaxProbeRotations = max(1, maxProbeRotations);
  long maxProbeSteps = (long)stepsPerRevolution * (long)safeMaxProbeRotations;

  Serial.print("ACTIVE X CALIBRATION RPM ");
  Serial.print(calibrationRPM);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.print(accelerationRpmPerSecond);
  Serial.print(" STEPS_PER_ROTATION ");
  Serial.print(stepsPerRevolution);
  Serial.print(" MAX_PROBE_ROTATIONS ");
  Serial.print(safeMaxProbeRotations);
  Serial.print(" MAX_PROBE_STEPS ");
  Serial.println(maxProbeSteps);
  printXYMotorPinState("CALIBRATE");
  printXYLimitState("START");
  setXYMotorsEnabled(true);

  // ---- Home X-min: the refined slow touch defines X = 0. ----
  long minFastSteps = 0;
  long minSlowSteps = 0;
  if (!homeXAgainstSwitch(
        "X_MIN", xAxis.minLimitPin,
        XY_DIR_TOWARD_X_MIN, XY_DIR_TOWARD_X_MAX,
        -1, +1,
        calibrationRPM, maxProbeSteps,
        minFastSteps, minSlowSteps)) {
    return false;
  }
  xAxis.currentSteps = 0;
  yAxis.currentSteps = 0;
  currentXSteps = 0;
  currentYSteps = 0;
  Serial.print("COREXY X MIN HOMED FAST_STEPS ");
  Serial.print(minFastSteps);
  Serial.print(" SLOW_STEPS ");
  Serial.println(minSlowSteps);

  // ---- Home X-max and measure the travel from X = 0. ----
  long maxFastSteps = 0;
  long maxSlowSteps = 0;
  if (!homeXAgainstSwitch(
        "X_MAX", xAxis.maxLimitPin,
        XY_DIR_TOWARD_X_MAX, XY_DIR_TOWARD_X_MIN,
        +1, -1,
        calibrationRPM, maxProbeSteps,
        maxFastSteps, maxSlowSteps)) {
    return false;
  }

  // currentXSteps is now the refined X-max position, with refined X-min == 0.
  long measuredXSteps = currentXSteps;
  if (measuredXSteps <= 0) {
    Serial.println("ERR XY X_MAX MEASURED_ZERO");
    return false;
  }

  xAxis.trackLengthCm = xTrackLengthCm;
  xStepsPerCm = ((float)measuredXSteps) / xTrackLengthCm;
  xyCalibrated = true;
  saveXCalibrationState();

  Serial.print("COREXY X MAX HOMED FAST_STEPS ");
  Serial.print(maxFastSteps);
  Serial.print(" SLOW_STEPS ");
  Serial.println(maxSlowSteps);
  Serial.print("X WORKSPACE CM ");
  Serial.print(xAxis.trackLengthCm, 3);
  Serial.print(" STEPS ");
  Serial.print(measuredXSteps);
  Serial.print(" STEPS_PER_CM ");
  Serial.println(xStepsPerCm, 3);
  printXYLimitState("END");
  Serial.println("OK CALIBRATE XY");
  return true;
}

// Moves the gantry along X to an absolute position (cm from X-min) using the
// measured steps-per-cm from calibration. Stops early if the limit switch in the
// travel direction trips.
bool moveXTo(float targetXCm, int rpm) {
  if (!xyCalibrated) {
    Serial.println("ERR X NOT CALIBRATED");
    return false;
  }
  if (targetXCm < 0.0f || targetXCm > xAxis.trackLengthCm) {
    Serial.println("ERR X TARGET RANGE");
    return false;
  }

  long targetXSteps = lroundf(targetXCm * xStepsPerCm);
  long deltaSteps = targetXSteps - currentXSteps;
  bool towardMax = deltaSteps >= 0;
  int dirLevel = towardMax ? XY_DIR_TOWARD_X_MAX : XY_DIR_TOWARD_X_MIN;
  int positionStep = towardMax ? 1 : -1;
  int travelLimitPin = towardMax ? xAxis.maxLimitPin : xAxis.minLimitPin;
  long steps = labs(deltaSteps);

  Serial.print("ACTIVE MOVE X CM ");
  Serial.print(targetXCm, 3);
  Serial.print(" RPM ");
  Serial.println(rpm);

  setXYMotorsEnabled(true);

  long stepsTaken = 0;
  bool stopRequested = false;
  bool limitHit = false;
  driveXAxis(rpm, steps, dirLevel, positionStep, travelLimitPin, stepsTaken, stopRequested, limitHit);

  Serial.print("X POSITION CM ");
  Serial.print(stepsToCm(currentXSteps, xStepsPerCm), 3);
  Serial.print(" STEPS ");
  Serial.println(currentXSteps);

  if (stopRequested) {
    return false;
  }
  if (limitHit) {
    // Hit the travel-direction limit switch before reaching the target.
    Serial.println("ERR ESTOP X LIMIT");
    saveXCalibrationState();
    return false;
  }

  saveXCalibrationState();
  Serial.println("OK MOVE X");
  return true;
}

bool calibrateZ(float leftTrackLengthCm, float rightTrackLengthCm, int calibrationRPM, bool trapezoidalSpeed, int accelerationRpmPerSecond) {
  long leftExpectedSteps = cmToSteps(leftTrackLengthCm, Z_STEPS_PER_CM);
  long rightExpectedSteps = cmToSteps(rightTrackLengthCm, Z_STEPS_PER_CM);

  Serial.print("ACTIVE Z CALIBRATION RPM ");
  Serial.print(calibrationRPM);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);

  bool stopRequested = false;
  if (!probeZLimit(false, leftExpectedSteps, rightExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP CALIBRATE Z" : "ERR Z MIN HOME");
    return false;
  }

  zLeftAxis.currentSteps = 0;
  zRightAxis.currentSteps = 0;

  if (!probeZLimit(true, leftExpectedSteps, rightExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP CALIBRATE Z" : "ERR Z MAX HOME");
    return false;
  }

  zLeftAxis.trackLengthCm = stepsToCm(zLeftAxis.currentSteps, Z_STEPS_PER_CM);
  zRightAxis.trackLengthCm = stepsToCm(zRightAxis.currentSteps, Z_STEPS_PER_CM);

  zCalibrated = true;

  Serial.print("Z WORKSPACE CM ");
  Serial.print(zLeftAxis.trackLengthCm, 3);
  Serial.print(" ");
  Serial.println(zRightAxis.trackLengthCm, 3);
  Serial.println("OK CALIBRATE Z");
  return true;
}

bool handleSetXYEnableCommand(const String &cmd) {
  int nextAEnablePin = -1;
  int nextBEnablePin = -1;
  int activeLowFlag = 1;
  int parsed = sscanf(cmd.c_str(), "SET XY ENABLE %d %d %d", &nextAEnablePin, &nextBEnablePin, &activeLowFlag);
  if (parsed < 2) {
    return false;
  }

  applyXYEnable(nextAEnablePin, nextBEnablePin, parsed >= 3 ? activeLowFlag != 0 : true);
  return true;
}

bool handleSetXYPinsCommand(const String &cmd) {
  int nextXStepPin = -1;
  int nextXDirPin = -1;
  int nextYStepPin = -1;
  int nextYDirPin = -1;
  int parsed = sscanf(cmd.c_str(), "SET XY PINS %d %d %d %d", &nextXStepPin, &nextXDirPin, &nextYStepPin, &nextYDirPin);
  if (parsed != 4) {
    return false;
  }

  applyXYPins(nextXStepPin, nextXDirPin, nextYStepPin, nextYDirPin);
  return true;
}

bool handleSetXYLimitsCommand(const String &cmd) {
  int nextMode = 4;
  int nextXMin = -1;
  int nextXMax = -1;
  int nextYMin = -1;
  int nextYMax = -1;
  int parsed = sscanf(cmd.c_str(), "SET XY LIMITS %d %d %d %d %d", &nextMode, &nextXMin, &nextXMax, &nextYMin, &nextYMax);
  if (parsed != 5) {
    nextMode = 4;
    parsed = sscanf(cmd.c_str(), "SET XY LIMITS %d %d %d %d", &nextXMin, &nextXMax, &nextYMin, &nextYMax);
    if (parsed != 4) {
      return false;
    }
  }

  applyXYLimits(nextMode, nextXMin, nextXMax, nextYMin, nextYMax);
  return true;
}

bool handleMoveXCommand(const String &cmd) {
  float targetXCm = 0.0f;
  char speedBuffer[16] = "normal";
  int parsed = sscanf(cmd.c_str(), "MOVE X %f %15s", &targetXCm, speedBuffer);
  if (parsed < 1) {
    return false;
  }

  String speedToken = parsed >= 2 ? String(speedBuffer) : String("normal");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForMoveProfile(speedToken);
  moveXTo(targetXCm, rpm);
  return true;
}

bool handleMoveXYCommand(const String &cmd) {
  float targetXCm = 0.0f;
  float targetYCm = 0.0f;
  char speedBuffer[16] = "normal";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 600;
  int parsed = sscanf(cmd.c_str(), "MOVE XY %f %f %15s %d %d", &targetXCm, &targetYCm, speedBuffer, &trapezoidFlag, &accelerationRpmPerSecond);
  if (parsed < 2) {
    return false;
  }

  String speedToken = parsed >= 3 ? String(speedBuffer) : String("normal");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForMoveProfile(speedToken);
  moveXYTo(targetXCm, targetYCm, rpm, parsed >= 4 ? trapezoidFlag != 0 : true, parsed >= 5 ? accelerationRpmPerSecond : 600);
  return true;
}

bool handleMoveXYZCommand(const String &cmd) {
  float targetXCm = 0.0f;
  float targetYCm = 0.0f;
  float targetZCm = 0.0f;
  char speedBuffer[16] = "normal";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 600;
  int onTheFlyFlag = 1;
  int maxDiffSteps = 5;
  int parsed = sscanf(cmd.c_str(), "MOVE XYZ %f %f %f %15s %d %d %d %d", &targetXCm, &targetYCm, &targetZCm, speedBuffer, &trapezoidFlag, &accelerationRpmPerSecond, &onTheFlyFlag, &maxDiffSteps);
  if (parsed < 3) {
    return false;
  }

  String speedToken = parsed >= 4 ? String(speedBuffer) : String("normal");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForMoveProfile(speedToken);
  moveXYZTo(
    targetXCm,
    targetYCm,
    targetZCm,
    rpm,
    parsed >= 5 ? trapezoidFlag != 0 : true,
    parsed >= 6 ? accelerationRpmPerSecond : 600,
    parsed >= 7 ? onTheFlyFlag != 0 : true,
    parsed >= 8 ? maxDiffSteps : 5
  );
  return true;
}

bool handleCalibrateXYCommand(const String &cmd) {
  float xTrackLengthCm = 0.0f;
  char speedBuffer[16] = "safe";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 300;
  int nextStepsPerRotation = DEFAULT_STEPS_PER_REVOLUTION;
  int maxProbeRotations = DEFAULT_MAX_PROBE_ROTATIONS;
  int parsedOld = 0;
  float ignoredYTrackLengthCm = 0.0f;
  int parsed = sscanf(
    cmd.c_str(),
    "CALIBRATE XY %f %15s %d %d %d %d",
    &xTrackLengthCm,
    speedBuffer,
    &trapezoidFlag,
    &accelerationRpmPerSecond,
    &nextStepsPerRotation,
    &maxProbeRotations
  );
  bool shouldTryLegacyFormat = parsed < 2 || (parsed >= 3 && trapezoidFlag != 0 && trapezoidFlag != 1);
  if (shouldTryLegacyFormat) {
    trapezoidFlag = 1;
    accelerationRpmPerSecond = 300;
    nextStepsPerRotation = DEFAULT_STEPS_PER_REVOLUTION;
    maxProbeRotations = DEFAULT_MAX_PROBE_ROTATIONS;
    parsedOld = sscanf(
      cmd.c_str(),
      "CALIBRATE XY %f %f %15s %d %d %d %d",
      &xTrackLengthCm,
      &ignoredYTrackLengthCm,
      speedBuffer,
      &trapezoidFlag,
      &accelerationRpmPerSecond,
      &nextStepsPerRotation,
      &maxProbeRotations
    );
  }
  if (parsed < 2 && parsedOld < 3) {
    return false;
  }

  int effectiveParsed = parsed >= 2 ? parsed : parsedOld - 1;
  String speedToken = effectiveParsed >= 2 ? String(speedBuffer) : String("safe");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForCalibrationProfile(speedToken);
  calibrateXY(
    xTrackLengthCm,
    rpm,
    effectiveParsed >= 3 ? trapezoidFlag != 0 : true,
    effectiveParsed >= 4 ? accelerationRpmPerSecond : 300,
    effectiveParsed >= 5 ? nextStepsPerRotation : DEFAULT_STEPS_PER_REVOLUTION,
    effectiveParsed >= 6 ? maxProbeRotations : DEFAULT_MAX_PROBE_ROTATIONS
  );
  return true;
}

bool handleSetZPinsCommand(const String &cmd) {
  int nextLeftStepPin = -1;
  int nextLeftDirPin = -1;
  int nextRightStepPin = -1;
  int nextRightDirPin = -1;
  int parsed = sscanf(cmd.c_str(), "SET Z PINS %d %d %d %d", &nextLeftStepPin, &nextLeftDirPin, &nextRightStepPin, &nextRightDirPin);
  if (parsed != 4) {
    return false;
  }

  applyZPins(nextLeftStepPin, nextLeftDirPin, nextRightStepPin, nextRightDirPin);
  return true;
}

bool handleSetZLimitsCommand(const String &cmd) {
  int nextMode = 4;
  int nextLeftMin = -1;
  int nextLeftMax = -1;
  int nextRightMin = -1;
  int nextRightMax = -1;
  int parsed = sscanf(cmd.c_str(), "SET Z LIMITS %d %d %d %d %d", &nextMode, &nextLeftMin, &nextLeftMax, &nextRightMin, &nextRightMax);
  if (parsed != 5) {
    nextMode = 4;
    parsed = sscanf(cmd.c_str(), "SET Z LIMITS %d %d %d %d", &nextLeftMin, &nextLeftMax, &nextRightMin, &nextRightMax);
    if (parsed != 4) {
      return false;
    }
  }

  applyZLimits(nextMode, nextLeftMin, nextLeftMax, nextRightMin, nextRightMax);
  return true;
}

bool handleMoveZCommand(const String &cmd) {
  float targetLeftCm = 0.0f;
  float targetRightCm = 0.0f;
  char speedBuffer[16] = "normal";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 600;
  int onTheFlyFlag = 1;
  int maxDiffSteps = 5;
  int parsed = sscanf(cmd.c_str(), "MOVE Z %f %f %15s %d %d %d %d", &targetLeftCm, &targetRightCm, speedBuffer, &trapezoidFlag, &accelerationRpmPerSecond, &onTheFlyFlag, &maxDiffSteps);
  if (parsed < 2) {
    return false;
  }

  String speedToken = parsed >= 3 ? String(speedBuffer) : String("normal");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForMoveProfile(speedToken);
  moveZTo(
    targetLeftCm,
    targetRightCm,
    rpm,
    parsed >= 4 ? trapezoidFlag != 0 : true,
    parsed >= 5 ? accelerationRpmPerSecond : 600,
    parsed >= 6 ? onTheFlyFlag != 0 : true,
    parsed >= 7 ? maxDiffSteps : 5
  );
  return true;
}

bool handleCalibrateZCommand(const String &cmd) {
  float leftTrackLengthCm = 0.0f;
  float rightTrackLengthCm = 0.0f;
  char speedBuffer[16] = "safe";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 300;
  int parsed = sscanf(cmd.c_str(), "CALIBRATE Z %f %f %15s %d %d", &leftTrackLengthCm, &rightTrackLengthCm, speedBuffer, &trapezoidFlag, &accelerationRpmPerSecond);
  if (parsed < 2) {
    return false;
  }

  String speedToken = parsed >= 3 ? String(speedBuffer) : String("safe");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForCalibrationProfile(speedToken);
  calibrateZ(leftTrackLengthCm, rightTrackLengthCm, rpm, parsed >= 4 ? trapezoidFlag != 0 : true, parsed >= 5 ? accelerationRpmPerSecond : 300);
  return true;
}

void setup() {
  Serial.begin(115200);

  applyXYPins(xAxis.stepPin, xAxis.dirPin, yAxis.stepPin, yAxis.dirPin);
  applyXYLimits(xyLimitSwitchMode, xAxis.minLimitPin, xAxis.maxLimitPin, yAxis.minLimitPin, yAxis.maxLimitPin);
  applyZPins(zLeftAxis.stepPin, zLeftAxis.dirPin, zRightAxis.stepPin, zRightAxis.dirPin);
  applyZLimits(zLimitSwitchMode, zLeftAxis.minLimitPin, zLeftAxis.maxLimitPin, zRightAxis.minLimitPin, zRightAxis.maxLimitPin);

  loadXCalibrationState();

  Serial.println("READY");
}

void loop() {
  if (!Serial.available()) {
    return;
  }

  String cmd = Serial.readStringUntil('\n');
  cmd.trim();
  if (cmd.length() == 0) {
    return;
  }

  if (cmd == "PING") {
    Serial.println("PONG");
  }
  else if (cmd == "STOP") {
    Serial.println("OK STOP");
  }
  else if (handleSetXYEnableCommand(cmd)) {
  }
  else if (handleSetXYPinsCommand(cmd)) {
  }
  else if (handleSetXYLimitsCommand(cmd)) {
  }
  else if (handleMoveXYZCommand(cmd)) {
  }
  else if (handleMoveXYCommand(cmd)) {
  }
  else if (handleMoveXCommand(cmd)) {
  }
  else if (handleCalibrateXYCommand(cmd)) {
  }
  else if (handleSetZPinsCommand(cmd)) {
  }
  else if (handleSetZLimitsCommand(cmd)) {
  }
  else if (handleMoveZCommand(cmd)) {
  }
  else if (handleCalibrateZCommand(cmd)) {
  }
  else {
    Serial.println("ERR UNKNOWN CMD");
  }
}
