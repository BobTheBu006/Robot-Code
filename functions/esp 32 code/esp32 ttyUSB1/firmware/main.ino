#include <Arduino.h>

const int STEPS_PER_REVOLUTION = 200;
const int STEP_PULSE_WIDTH_US = 8;
const float XY_STEPS_PER_CM = 100.0f;
const float Z_STEPS_PER_CM = 100.0f;
const float DEFAULT_X_WORKSPACE_CM = 115.0f;
const float DEFAULT_Y_WORKSPACE_CM = 60.0f;
const float DEFAULT_Z_WORKSPACE_CM = 60.0f;
const float NEAR_LIMIT_CALIBRATION_CM = 3.0f;
const int SLOW_PROBE_RPM_FLOOR = 25;

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

int xyLimitSwitchMode = 4;
int zLimitSwitchMode = 4;
bool xyCalibrated = false;
bool zCalibrated = false;

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
  float stepsPerSecond = (rpm * STEPS_PER_REVOLUTION) / 60.0f;
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
  float targetStepsPerSecond = (targetRpm * STEPS_PER_REVOLUTION) / 60.0f;
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

  long targetXSteps = cmToSteps(targetXCm, XY_STEPS_PER_CM);
  long targetYSteps = cmToSteps(targetYCm, XY_STEPS_PER_CM);
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
  long expectedTravelSteps,
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
bool calibrateXY(float xTrackLengthCm, float yTrackLengthCm, int calibrationRPM, bool trapezoidalSpeed, int accelerationRpmPerSecond);
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
    if (!calibrateXY(xAxis.trackLengthCm, yAxis.trackLengthCm, slowProbeRpmFor(rpm), true, accelerationRpmPerSecond)) {
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

  long returnXSteps = cmToSteps(targetXCm, XY_STEPS_PER_CM);
  long returnYSteps = cmToSteps(targetYCm, XY_STEPS_PER_CM);
  long returnZSteps = cmToSteps(targetZCm, Z_STEPS_PER_CM);
  long nearXYSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, XY_STEPS_PER_CM);
  long nearZSteps = cmToSteps(NEAR_LIMIT_CALIBRATION_CM, Z_STEPS_PER_CM);
  long xMaxSteps = cmToSteps(xAxis.trackLengthCm, XY_STEPS_PER_CM);
  long yMaxSteps = cmToSteps(yAxis.trackLengthCm, XY_STEPS_PER_CM);
  long zLeftMaxSteps = cmToSteps(zLeftAxis.trackLengthCm, Z_STEPS_PER_CM);
  long zRightMaxSteps = cmToSteps(zRightAxis.trackLengthCm, Z_STEPS_PER_CM);

  if (returnXSteps <= nearXYSteps && !checkCoreXYAxisCalibration('X', false, 0, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (xMaxSteps - returnXSteps <= nearXYSteps && !checkCoreXYAxisCalibration('X', true, xMaxSteps, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (returnYSteps <= nearXYSteps && !checkCoreXYAxisCalibration('Y', false, 0, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
    return false;
  }
  if (yMaxSteps - returnYSteps <= nearXYSteps && !checkCoreXYAxisCalibration('Y', true, yMaxSteps, returnXSteps, returnYSteps, maxDiffSteps, rpm, accelerationRpmPerSecond)) {
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
  long expectedTravelSteps,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  bool &stopRequested
) {
  long travel = labs(expectedTravelSteps) + 500;
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

  long backoff = 200;
  bool ignoredX = false;
  bool ignoredY = false;
  bool backoffStop = false;
  runCoreXYCartesianMove(
    axis == 'X' ? (positiveDirection ? -backoff : backoff) : 0,
    axis == 'Y' ? (positiveDirection ? -backoff : backoff) : 0,
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
    axis == 'X' ? (positiveDirection ? backoff + 300 : -(backoff + 300)) : 0,
    axis == 'Y' ? (positiveDirection ? backoff + 300 : -(backoff + 300)) : 0,
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

bool calibrateXY(float xTrackLengthCm, float yTrackLengthCm, int calibrationRPM, bool trapezoidalSpeed, int accelerationRpmPerSecond) {
  long xExpectedSteps = cmToSteps(xTrackLengthCm, XY_STEPS_PER_CM);
  long yExpectedSteps = cmToSteps(yTrackLengthCm, XY_STEPS_PER_CM);

  Serial.print("ACTIVE XY CALIBRATION RPM ");
  Serial.print(calibrationRPM);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);

  bool stopRequested = false;

  if (!probeCoreXYLimit('X', false, xExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP CALIBRATE XY" : "ERR XY MIN HOME X");
    return false;
  }
  xAxis.currentSteps = 0;
  yAxis.currentSteps = 0;
  currentXSteps = 0;

  if (xyLimitSwitchMode == 4) {
    if (!probeCoreXYLimit('X', true, xExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
      Serial.println(stopRequested ? "ERR STOP CALIBRATE XY" : "ERR XY MAX HOME X");
      return false;
    }
  }
  xAxis.trackLengthCm = xyLimitSwitchMode == 4 ? stepsToCm(currentXSteps, XY_STEPS_PER_CM) : xTrackLengthCm;

  bool ignoredFirst = false;
  bool ignoredSecond = false;
  bool returnStopRequested = false;
  runCoreXYCartesianMove(
    -currentXSteps,
    0,
    calibrationRPM,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    false,
    ignoredFirst,
    ignoredSecond,
    returnStopRequested
  );
  if (returnStopRequested) {
    return false;
  }

  currentXSteps = 0;

  if (!probeCoreXYLimit('Y', false, yExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
    Serial.println(stopRequested ? "ERR STOP CALIBRATE XY" : "ERR XY MIN HOME Y");
    return false;
  }
  currentYSteps = 0;

  if (xyLimitSwitchMode == 4) {
    if (!probeCoreXYLimit('Y', true, yExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
      Serial.println(stopRequested ? "ERR STOP CALIBRATE XY" : "ERR XY MAX HOME Y");
      return false;
    }
  }
  yAxis.trackLengthCm = xyLimitSwitchMode == 4 ? stepsToCm(currentYSteps, XY_STEPS_PER_CM) : yTrackLengthCm;

  ignoredFirst = false;
  ignoredSecond = false;
  returnStopRequested = false;
  runCoreXYCartesianMove(
    0,
    -currentYSteps,
    calibrationRPM,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    false,
    ignoredFirst,
    ignoredSecond,
    returnStopRequested
  );
  if (returnStopRequested) {
    return false;
  }

  currentYSteps = 0;
  xAxis.currentSteps = 0;
  yAxis.currentSteps = 0;
  xyCalibrated = true;

  Serial.print("XY WORKSPACE CM ");
  Serial.print(xAxis.trackLengthCm, 3);
  Serial.print(" ");
  Serial.println(yAxis.trackLengthCm, 3);
  Serial.println("OK CALIBRATE XY");
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

  if (zLimitSwitchMode == 4) {
    if (!probeZLimit(true, leftExpectedSteps, rightExpectedSteps, calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, stopRequested)) {
      Serial.println(stopRequested ? "ERR STOP CALIBRATE Z" : "ERR Z MAX HOME");
      return false;
    }
  } else {
    zLeftAxis.currentSteps = leftExpectedSteps;
    zRightAxis.currentSteps = rightExpectedSteps;
  }

  zLeftAxis.trackLengthCm = stepsToCm(zLeftAxis.currentSteps, Z_STEPS_PER_CM);
  zRightAxis.trackLengthCm = stepsToCm(zRightAxis.currentSteps, Z_STEPS_PER_CM);

  bool ignoredFirst = false;
  bool ignoredSecond = false;
  bool returnStopRequested = false;
  runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    -zLeftAxis.currentSteps,
    -zRightAxis.currentSteps,
    calibrationRPM,
    trapezoidalSpeed,
    accelerationRpmPerSecond,
    zLimitSwitchMode,
    false,
    ignoredFirst,
    ignoredSecond,
    returnStopRequested
  );
  if (returnStopRequested) {
    return false;
  }

  zLeftAxis.currentSteps = 0;
  zRightAxis.currentSteps = 0;
  zCalibrated = true;

  Serial.print("Z WORKSPACE CM ");
  Serial.print(zLeftAxis.trackLengthCm, 3);
  Serial.print(" ");
  Serial.println(zRightAxis.trackLengthCm, 3);
  Serial.println("OK CALIBRATE Z");
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
    return false;
  }

  applyXYLimits(nextMode, nextXMin, nextXMax, nextYMin, nextYMax);
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
  float yTrackLengthCm = 0.0f;
  char speedBuffer[16] = "safe";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 300;
  int parsed = sscanf(cmd.c_str(), "CALIBRATE XY %f %f %15s %d %d", &xTrackLengthCm, &yTrackLengthCm, speedBuffer, &trapezoidFlag, &accelerationRpmPerSecond);
  if (parsed < 2) {
    return false;
  }

  String speedToken = parsed >= 3 ? String(speedBuffer) : String("safe");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForCalibrationProfile(speedToken);
  calibrateXY(xTrackLengthCm, yTrackLengthCm, rpm, parsed >= 4 ? trapezoidFlag != 0 : true, parsed >= 5 ? accelerationRpmPerSecond : 300);
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
    return false;
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
  else if (handleSetXYPinsCommand(cmd)) {
  }
  else if (handleSetXYLimitsCommand(cmd)) {
  }
  else if (handleMoveXYZCommand(cmd)) {
  }
  else if (handleMoveXYCommand(cmd)) {
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
