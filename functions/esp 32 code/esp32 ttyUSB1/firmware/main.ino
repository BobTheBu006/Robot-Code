#include <Arduino.h>

const int STEPS_PER_REVOLUTION = 200;
const int STEP_PULSE_WIDTH_US = 8;
const float XY_STEPS_PER_CM = 100.0f;
const float Z_STEPS_PER_CM = 100.0f;

struct AxisChannel {
  int stepPin;
  int dirPin;
  int minLimitPin;
  int maxLimitPin;
  long currentSteps;
  float trackLengthCm;
};

AxisChannel xAxis = {16, 17, 21, 22, 0, 100.0f};
AxisChannel yAxis = {18, 19, 23, 25, 0, 100.0f};
AxisChannel zLeftAxis = {32, 33, 12, 13, 0, 40.0f};
AxisChannel zRightAxis = {4, 5, 14, 15, 0, 40.0f};

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

  unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
  unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
    ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
    : (unsigned long)STEP_PULSE_WIDTH_US;

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
      delayMicroseconds(lowTimeMicros);
    }
  }

  return !(firstBlocked || secondBlocked);
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

bool moveXYTo(float targetXCm, float targetYCm, const String &profile) {
  if (xyCalibrated) {
    if (targetXCm < 0.0f || targetXCm > xAxis.trackLengthCm || targetYCm < 0.0f || targetYCm > yAxis.trackLengthCm) {
      Serial.println("ERR XY TARGET RANGE");
      return false;
    }
  }

  long targetXSteps = cmToSteps(targetXCm, XY_STEPS_PER_CM);
  long targetYSteps = cmToSteps(targetYCm, XY_STEPS_PER_CM);
  long deltaX = targetXSteps - xAxis.currentSteps;
  long deltaY = targetYSteps - yAxis.currentSteps;
  bool xBlocked = false;
  bool yBlocked = false;
  bool stopRequested = false;

  Serial.print("ACTIVE XY PROFILE ");
  Serial.println(profile);
  Serial.print("TARGET XY CM ");
  Serial.print(targetXCm, 3);
  Serial.print(" ");
  Serial.println(targetYCm, 3);

  bool moved = runDualAxisMove(
    xAxis,
    yAxis,
    deltaX,
    deltaY,
    rpmForMoveProfile(profile),
    xyLimitSwitchMode,
    true,
    xBlocked,
    yBlocked,
    stopRequested
  );

  Serial.print("XY POSITION STEPS ");
  Serial.print(xAxis.currentSteps);
  Serial.print(" ");
  Serial.println(yAxis.currentSteps);

  if (!moved) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR XY LIMIT ");
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

bool moveZTo(float targetLeftCm, float targetRightCm, const String &profile) {
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
  bool leftBlocked = false;
  bool rightBlocked = false;
  bool stopRequested = false;

  Serial.print("ACTIVE Z PROFILE ");
  Serial.println(profile);
  Serial.print("TARGET Z CM ");
  Serial.print(targetLeftCm, 3);
  Serial.print(" ");
  Serial.println(targetRightCm, 3);

  bool moved = runDualAxisMove(
    zLeftAxis,
    zRightAxis,
    deltaLeft,
    deltaRight,
    rpmForMoveProfile(profile),
    zLimitSwitchMode,
    true,
    leftBlocked,
    rightBlocked,
    stopRequested
  );

  Serial.print("Z POSITION STEPS ");
  Serial.print(zLeftAxis.currentSteps);
  Serial.print(" ");
  Serial.println(zRightAxis.currentSteps);

  if (!moved) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR Z LIMIT ");
    if (leftBlocked && rightBlocked) {
      Serial.println("LEFT,RIGHT");
    } else if (leftBlocked) {
      Serial.println("LEFT");
    } else {
      Serial.println("RIGHT");
    }
    return false;
  }

  Serial.println("OK MOVE Z");
  return true;
}

bool homeAxesToMinimum(
  AxisChannel &firstAxis,
  AxisChannel &secondAxis,
  int limitMode,
  long firstMaxSteps,
  long secondMaxSteps,
  int rpm,
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

bool calibrateXY(float xTrackLengthCm, float yTrackLengthCm, const String &profile) {
  int calibrationRPM = rpmForCalibrationProfile(profile);
  long xExpectedSteps = cmToSteps(xTrackLengthCm, XY_STEPS_PER_CM);
  long yExpectedSteps = cmToSteps(yTrackLengthCm, XY_STEPS_PER_CM);
  long xHomeTravel = xExpectedSteps + 500;
  long yHomeTravel = yExpectedSteps + 500;

  Serial.print("ACTIVE XY CALIBRATION PROFILE ");
  Serial.println(profile);

  bool xHomed = false;
  bool yHomed = false;
  bool stopRequested = false;
  if (!homeAxesToMinimum(xAxis, yAxis, xyLimitSwitchMode, xHomeTravel, yHomeTravel, calibrationRPM, xHomed, yHomed, stopRequested)) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR XY HOME ");
    if (!xHomed && !yHomed) {
      Serial.println("X,Y");
    } else if (!xHomed) {
      Serial.println("X");
    } else {
      Serial.println("Y");
    }
    return false;
  }

  xAxis.currentSteps = 0;
  yAxis.currentSteps = 0;

  if (xyLimitSwitchMode == 4) {
    bool xBlocked = false;
    bool yBlocked = false;
    bool maxStopRequested = false;
    runDualAxisMove(
      xAxis,
      yAxis,
      xExpectedSteps,
      yExpectedSteps,
      calibrationRPM,
      xyLimitSwitchMode,
      true,
      xBlocked,
      yBlocked,
      maxStopRequested
    );
    if (maxStopRequested) {
      return false;
    }
  } else {
    xAxis.currentSteps = xExpectedSteps;
    yAxis.currentSteps = yExpectedSteps;
  }

  xAxis.trackLengthCm = stepsToCm(xAxis.currentSteps, XY_STEPS_PER_CM);
  yAxis.trackLengthCm = stepsToCm(yAxis.currentSteps, XY_STEPS_PER_CM);

  bool ignoredFirst = false;
  bool ignoredSecond = false;
  bool returnStopRequested = false;
  runDualAxisMove(
    xAxis,
    yAxis,
    -xAxis.currentSteps,
    -yAxis.currentSteps,
    calibrationRPM,
    xyLimitSwitchMode,
    false,
    ignoredFirst,
    ignoredSecond,
    returnStopRequested
  );
  if (returnStopRequested) {
    return false;
  }

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

bool calibrateZ(float leftTrackLengthCm, float rightTrackLengthCm, const String &profile) {
  int calibrationRPM = rpmForCalibrationProfile(profile);
  long leftExpectedSteps = cmToSteps(leftTrackLengthCm, Z_STEPS_PER_CM);
  long rightExpectedSteps = cmToSteps(rightTrackLengthCm, Z_STEPS_PER_CM);
  long leftHomeTravel = leftExpectedSteps + 500;
  long rightHomeTravel = rightExpectedSteps + 500;

  Serial.print("ACTIVE Z CALIBRATION PROFILE ");
  Serial.println(profile);

  bool leftHomed = false;
  bool rightHomed = false;
  bool stopRequested = false;
  if (!homeAxesToMinimum(zLeftAxis, zRightAxis, zLimitSwitchMode, leftHomeTravel, rightHomeTravel, calibrationRPM, leftHomed, rightHomed, stopRequested)) {
    if (stopRequested) {
      return false;
    }
    Serial.print("ERR Z HOME ");
    if (!leftHomed && !rightHomed) {
      Serial.println("LEFT,RIGHT");
    } else if (!leftHomed) {
      Serial.println("LEFT");
    } else {
      Serial.println("RIGHT");
    }
    return false;
  }

  zLeftAxis.currentSteps = 0;
  zRightAxis.currentSteps = 0;

  if (zLimitSwitchMode == 4) {
    bool leftBlocked = false;
    bool rightBlocked = false;
    bool maxStopRequested = false;
    runDualAxisMove(
      zLeftAxis,
      zRightAxis,
      leftExpectedSteps,
      rightExpectedSteps,
      calibrationRPM,
      zLimitSwitchMode,
      true,
      leftBlocked,
      rightBlocked,
      maxStopRequested
    );
    if (maxStopRequested) {
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
  char profileBuffer[16] = "normal";
  int parsed = sscanf(cmd.c_str(), "MOVE XY %f %f %15s", &targetXCm, &targetYCm, profileBuffer);
  if (parsed < 2) {
    return false;
  }

  String profile = parsed >= 3 ? String(profileBuffer) : String("normal");
  profile.toLowerCase();
  moveXYTo(targetXCm, targetYCm, profile);
  return true;
}

bool handleCalibrateXYCommand(const String &cmd) {
  float xTrackLengthCm = 0.0f;
  float yTrackLengthCm = 0.0f;
  char profileBuffer[16] = "safe";
  int parsed = sscanf(cmd.c_str(), "CALIBRATE XY %f %f %15s", &xTrackLengthCm, &yTrackLengthCm, profileBuffer);
  if (parsed < 2) {
    return false;
  }

  String profile = parsed >= 3 ? String(profileBuffer) : String("safe");
  profile.toLowerCase();
  calibrateXY(xTrackLengthCm, yTrackLengthCm, profile);
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
  char profileBuffer[16] = "normal";
  int parsed = sscanf(cmd.c_str(), "MOVE Z %f %f %15s", &targetLeftCm, &targetRightCm, profileBuffer);
  if (parsed < 2) {
    return false;
  }

  String profile = parsed >= 3 ? String(profileBuffer) : String("normal");
  profile.toLowerCase();
  moveZTo(targetLeftCm, targetRightCm, profile);
  return true;
}

bool handleCalibrateZCommand(const String &cmd) {
  float leftTrackLengthCm = 0.0f;
  float rightTrackLengthCm = 0.0f;
  char profileBuffer[16] = "safe";
  int parsed = sscanf(cmd.c_str(), "CALIBRATE Z %f %f %15s", &leftTrackLengthCm, &rightTrackLengthCm, profileBuffer);
  if (parsed < 2) {
    return false;
  }

  String profile = parsed >= 3 ? String(profileBuffer) : String("safe");
  profile.toLowerCase();
  calibrateZ(leftTrackLengthCm, rightTrackLengthCm, profile);
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
