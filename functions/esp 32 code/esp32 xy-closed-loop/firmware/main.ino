#include <Arduino.h>
#include "controller_identity.h"
#include <Preferences.h>

// Forward declaration only. The Arduino build auto-generates function
// prototypes right after this include block, before EncoderChannel's full
// definition further down - a function taking "EncoderChannel &" only needs
// the type to be known, not complete, for that generated prototype to compile.
struct EncoderChannel;

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

// Safety buffer kept between the usable workspace and every limit switch, so
// moves to 0 or to max stop short of the switches instead of tripping them. Set
// per calibration and persisted, because every later move maps user coordinates
// through it: changing it without re-reading it would silently shift the origin.
const float DEFAULT_XY_LIMIT_BUFFER_CM = 0.5f;
// How far the gantry parks clear of the Y-min switch, in motor rotations,
// while X calibrates. Rotations convert to steps with nothing but the
// steps-per-rotation setting, so the distance is exact even before any
// steps-per-cm has been measured. Sweeping X with the carriage still resting on
// the Y switch loads the frame against its stop, so calibration steps off first.
const float DEFAULT_X_CALIBRATION_Y_ROTATIONS = 1.6f;
// Freeing a limit switch that is already pressed when calibration starts reuses
// the homing back-off distance of one full motor rotation, which is already
// known to release a switch. The nudge repeats up to this many rotations and
// re-checks after each one, so it stops the moment the switch frees and a switch
// with a longer throw still clears.
const int XY_LIMIT_NUDGE_MAX_ROTATIONS = 4;

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
float xyLimitBufferCm = DEFAULT_XY_LIMIT_BUFFER_CM;
int stepsPerRevolution = DEFAULT_STEPS_PER_REVOLUTION;

int xyLimitSwitchMode = 4;
int zLimitSwitchMode = 4;
bool xyCalibrated = false;
bool zCalibrated = false;

// Y is not homed with a calibration probe. The first XY move after a calibration
// assumes the gantry is parked at Y = max; after that, Y is tracked like X.
bool yPositionKnown = false;

// Stepper driver ENABLE pins for the CoreXY A/B motors. -1 means "no enable pin
// wired" (driver is hardwired enabled), in which case all enable handling is a
// no-op. Most A4988/DRV8825/TMC carriers enable on a LOW level, so default to
// active-low.
int xEnablePin = -1;
int yEnablePin = -1;
bool xyMotorsEnableActiveLow = true;

// Bumped whenever the meaning of the saved calibration changes, so a record
// written by older firmware is discarded instead of misread. Version 1 never
// probed Y and saved it as "assumed parked at Y max"; version 2 homes Y against
// the Y-min switch, so a version 1 Y position is wrong by the length of the axis.
const int GANTRY_STATE_VERSION = 2;

void saveXCalibrationState() {
  gantryPrefs.begin("gantry", false);
  gantryPrefs.putInt("ver", GANTRY_STATE_VERSION);
  gantryPrefs.putBool("xyCal", xyCalibrated);
  gantryPrefs.putFloat("xStepsCm", xStepsPerCm);
  gantryPrefs.putFloat("xTrackCm", xAxis.trackLengthCm);
  gantryPrefs.putLong("xPos", currentXSteps);
  gantryPrefs.putBool("yKnown", yPositionKnown);
  gantryPrefs.putLong("yPos", currentYSteps);
  gantryPrefs.putFloat("yTrackCm", yAxis.trackLengthCm);
  gantryPrefs.putFloat("bufCm", xyLimitBufferCm);
  gantryPrefs.end();
}

// Forgets any stored calibration, so the gantry reports itself uncalibrated and
// moves refuse rather than run against a position that is no longer true.
void invalidateXCalibrationState() {
  xyCalibrated = false;
  yPositionKnown = false;
  saveXCalibrationState();
}

void loadXCalibrationState() {
  gantryPrefs.begin("gantry", true);
  int storedVersion = gantryPrefs.getInt("ver", 1);
  bool usable = storedVersion == GANTRY_STATE_VERSION;
  if (usable) {
    // Steps-per-cm describes the belts, pulleys and microstepping, not where the
    // carriage happens to be, so it outlives an invalidated calibration. Keeping
    // it lets the next run convert cm to steps before X has been re-measured.
    xStepsPerCm = gantryPrefs.getFloat("xStepsCm", DEFAULT_XY_STEPS_PER_CM);
    yStepsPerCm = xStepsPerCm;
    // The buffer defines where user coordinate 0 sits, so a restored position is
    // only meaningful alongside the buffer it was recorded with.
    xyLimitBufferCm = gantryPrefs.getFloat("bufCm", DEFAULT_XY_LIMIT_BUFFER_CM);

    if (gantryPrefs.getBool("xyCal", false)) {
      xyCalibrated = true;
      xAxis.trackLengthCm = gantryPrefs.getFloat("xTrackCm", DEFAULT_X_WORKSPACE_CM);
      currentXSteps = gantryPrefs.getLong("xPos", 0);
      yAxis.trackLengthCm = gantryPrefs.getFloat("yTrackCm", DEFAULT_Y_WORKSPACE_CM);
      yPositionKnown = gantryPrefs.getBool("yKnown", false);
      currentYSteps = gantryPrefs.getLong("yPos", 0);
    }
  }
  gantryPrefs.end();

  if (!usable) {
    Serial.print("X CALIBRATION DISCARDED STALE STATE VERSION ");
    Serial.print(storedVersion);
    Serial.print(" EXPECTED ");
    Serial.println(GANTRY_STATE_VERSION);
  }

  Serial.print("X CALIBRATION RESTORED ");
  Serial.print(xyCalibrated ? 1 : 0);
  Serial.print(" STEPS_PER_CM ");
  Serial.print(xStepsPerCm, 3);
  Serial.print(" TRACK_CM ");
  Serial.print(xAxis.trackLengthCm, 3);
  Serial.print(" X_POS_STEPS ");
  Serial.print(currentXSteps);
  Serial.print(" Y_KNOWN ");
  Serial.print(yPositionKnown ? 1 : 0);
  Serial.print(" Y_POS_STEPS ");
  Serial.println(currentYSteps);
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

  // Constant-acceleration ramp distance to reach the target speed: v^2 / (2a), in steps.
  float accelStepsPerSecond2 = (accelerationRpmPerSecond * (float)stepsPerRevolution) / 60.0f;
  float targetStepsPerSecond = (targetRpm * (float)stepsPerRevolution) / 60.0f;
  long rampIterations = (long)((targetStepsPerSecond * targetStepsPerSecond) / (2.0f * accelStepsPerSecond2));
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
  if (rampPosition > rampIterations) {
    rampPosition = rampIterations;
  }

  // Constant-acceleration speed after rampPosition steps: v = sqrt(2 * a * s).
  // On short moves rampIterations is clamped to half the distance, so the peak
  // becomes sqrt(a * distance) instead of the requested target speed - the move
  // accelerates to the midpoint and decelerates to 0, honoring the acceleration
  // value no matter how high the target speed is.
  float accelStepsPerSecond2 = (accelerationRpmPerSecond * (float)stepsPerRevolution) / 60.0f;
  float stepsPerSecond = sqrtf(2.0f * accelStepsPerSecond2 * (float)rampPosition);
  int nextRpm = (int)(((stepsPerSecond * 60.0f) / (float)stepsPerRevolution) + 0.5f);
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


// ---------------------------------------------------------------------------
// Closed-loop XY: AS5047D encoders on the A and B motor shafts, read over SPI.
//
// One encoder per physical motor - "A" and "B" here, matching xAxis/yAxis
// above which despite their names pulse the A and B motors respectively (see
// runCoreXYCartesianMove). Each encoder maps 1:1 to one motor, so the two PID
// loops are independent: no CoreXY transform inside the control loop, only
// when converting a cartesian target into A/B deltas, exactly as every move
// already does.
//
// AS5047D is 14-bit (16384 counts/revolution). At 800 steps/revolution that is
// 20.48 counts per full step, so single-step loss is directly visible.
//
// Correction is applied inside the existing, proven CoreXY stepping loop
// rather than a separate high-rate timer ISR. This is a deliberate interim
// design: it makes the correction genuinely continuous - reconsidered every
// few step iterations throughout the move, not only at the end - using a step
// generator that is already tested and known to hold a straight CoreXY line.
// A fully independent 1kHz control task is the documented next step once this
// is proven on real hardware (see docs/CLOSED_LOOP_XY_PLAN.md); building that
// blind, with no encoder yet wired, is exactly the risk the plan warns against.
// ---------------------------------------------------------------------------

#include <SPI.h>

const int ENCODER_COUNTS_PER_REV = 16384;   // AS5047D: 14-bit
const uint16_t AS5047D_CMD_READ = 0x4000;   // read, with parity bit set below
const uint16_t AS5047D_REG_ANGLECOM = 0x3FFF;
const uint32_t AS5047D_SPI_HZ = 1000000;    // conservative; datasheet allows up to 10 MHz

struct EncoderChannel {
  int csPin = -1;
  uint16_t lastRaw = 0;          // last raw 14-bit angle read
  long turns = 0;                // accumulated whole revolutions
  bool primed = false;           // false until the first read establishes lastRaw
  bool faulted = false;          // set if a read looks like a missed wrap
  uint16_t lastError = 0;        // AS5047D error register, if ever read
};

EncoderChannel encoderA;   // on the A motor shaft (xAxis.stepPin/dirPin)
EncoderChannel encoderB;   // on the B motor shaft (yAxis.stepPin/dirPin)

bool encodersConfigured = false;
bool spiStarted = false;

// PID gains and the following-error fault limit. Zero gains are deliberately
// inert - the loop runs and can report error, but applies no correction -
// until an operator sets real values. This is the "start with Kp small, Ki=0,
// Kd=0" rule from the plan, enforced as the default rather than left to be
// remembered.
struct XYPidState {
  float kp = 0.0f;
  float ki = 0.0f;
  float kd = 0.0f;
  float integralA = 0.0f;
  float integralB = 0.0f;
  float lastMeasuredA = 0.0f;    // for derivative-on-measurement
  float lastMeasuredB = 0.0f;
  bool primed = false;
};
XYPidState xyPid;

// Encoder counts, not steps: correcting in the same units the sensor reports
// avoids a lossy round trip through cm on every control tick.
float xyFollowLimitCounts = 205.0f;   // ~10 full steps at 20.48 counts/step
long xyIntegralClampCounts = 4096;    // +-1/4 revolution; anti-windup

// How often (in step iterations) the loop reads encoders and applies
// correction. Every iteration would mean an SPI transaction between every
// single step pulse, which risks the encoder read itself becoming the speed
// limiter; every few iterations keeps the correction frequent (continuous
// relative to the move, not only at the end) while bounding SPI traffic. Start
// conservative; the achievable rate is a hardware question, not a code one.
const int PID_CHECK_EVERY_N_ITERATIONS = 8;

void configureEncoderPins(int csA, int csB) {
  if (!spiStarted) {
    SPI.begin();
    spiStarted = true;
  }
  encoderA.csPin = csA;
  encoderB.csPin = csB;
  encoderA.primed = false;
  encoderB.primed = false;
  encoderA.faulted = false;
  encoderB.faulted = false;
  if (csA >= 0) {
    pinMode(csA, OUTPUT);
    digitalWrite(csA, HIGH);
  }
  if (csB >= 0) {
    pinMode(csB, OUTPUT);
    digitalWrite(csB, HIGH);
  }
  encodersConfigured = (csA >= 0 && csB >= 0);
}

// Odd parity over the low 15 bits, per the AS5047D frame format.
uint16_t as5047pWithParity(uint16_t command) {
  uint16_t value = command;
  uint8_t parity = 0;
  for (uint8_t bit = 0; bit < 15; bit++) {
    parity ^= (value >> bit) & 0x1;
  }
  if (parity) {
    value |= 0x8000;
  }
  return value;
}

// One 16-bit SPI transaction: send a command frame, get back the previous
// frame's reply (the AS5047D pipelines by one transaction, per its datasheet).
uint16_t as5047pTransfer(int csPin, uint16_t command) {
  uint16_t frame = as5047pWithParity(command);
  SPI.beginTransaction(SPISettings(AS5047D_SPI_HZ, MSBFIRST, SPI_MODE1));
  digitalWrite(csPin, LOW);
  delayMicroseconds(1);
  uint16_t reply = SPI.transfer16(frame);
  digitalWrite(csPin, HIGH);
  SPI.endTransaction();
  return reply;
}

// Reads ANGLECOM and folds the reply into the channel's accumulated position.
// Returns false if the reply looks like it missed a wrap (jumped by more than
// half a revolution since the last read) - that is a fault, not a value to
// silently accept, because it means the channel was not polled often enough
// for the speed the axis was moving at.
bool readEncoderChannel(EncoderChannel &channel) {
  if (channel.csPin < 0) {
    return false;
  }

  // First transfer primes the pipeline; the reply belongs to the read before
  // it, so a real ANGLECOM value needs two transfers back to back.
  as5047pTransfer(channel.csPin, AS5047D_CMD_READ | AS5047D_REG_ANGLECOM);
  uint16_t reply = as5047pTransfer(channel.csPin, AS5047D_CMD_READ | AS5047D_REG_ANGLECOM);

  bool errorFlag = (reply & 0x4000) != 0;
  uint16_t raw = reply & 0x3FFF;

  if (!channel.primed) {
    channel.lastRaw = raw;
    channel.primed = true;
    channel.faulted = errorFlag;
    return !errorFlag;
  }

  int32_t delta = (int32_t)raw - (int32_t)channel.lastRaw;
  // Wrap handling: a delta near +-16384 is really a small step across the
  // 0/16384 boundary, not a big jump. Fold it into the smaller, correct delta.
  if (delta > ENCODER_COUNTS_PER_REV / 2) {
    delta -= ENCODER_COUNTS_PER_REV;
  } else if (delta < -ENCODER_COUNTS_PER_REV / 2) {
    delta += ENCODER_COUNTS_PER_REV;
  }

  // A delta still close to half a revolution after that correction means two
  // consecutive reads were far enough apart in time (or the axis moved fast
  // enough) that which way it wrapped is ambiguous - this is the "must never
  // miss half a revolution" rule from the plan, checked rather than assumed.
  bool ambiguousWrap = labs(delta) > (ENCODER_COUNTS_PER_REV * 3) / 8;

  channel.turns += delta;
  channel.lastRaw = raw;
  channel.faulted = errorFlag || ambiguousWrap;
  channel.lastError = errorFlag ? reply : channel.lastError;
  return !channel.faulted;
}

long encoderAccumulatedCounts(const EncoderChannel &channel) {
  return channel.turns;
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
  bool stopOnAnyNewLimit,
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

  // Switches already pressed when the move starts stay latched until they
  // release, so a move can still escape a limit it is parked on. Any switch
  // that becomes pressed during the move stops the whole move instantly.
  bool firstMinWasActive = useLimitChecks && stopOnAnyNewLimit && isLimitActive(firstAxis.minLimitPin);
  bool firstMaxWasActive = useLimitChecks && stopOnAnyNewLimit && limitMode == 4 && isLimitActive(firstAxis.maxLimitPin);
  bool secondMinWasActive = useLimitChecks && stopOnAnyNewLimit && isLimitActive(secondAxis.minLimitPin);
  bool secondMaxWasActive = useLimitChecks && stopOnAnyNewLimit && limitMode == 4 && isLimitActive(secondAxis.maxLimitPin);

  for (long iteration = 0; iteration < totalIterations; iteration++) {
    if (consumeStopCommandIfPresent()) {
      stopRequested = true;
      return false;
    }

    if (useLimitChecks && stopOnAnyNewLimit) {
      bool firstMinActive = isLimitActive(firstAxis.minLimitPin);
      bool firstMaxActive = limitMode == 4 && isLimitActive(firstAxis.maxLimitPin);
      bool secondMinActive = isLimitActive(secondAxis.minLimitPin);
      bool secondMaxActive = limitMode == 4 && isLimitActive(secondAxis.maxLimitPin);

      if (!firstMinActive) {
        firstMinWasActive = false;
      }
      if (!firstMaxActive) {
        firstMaxWasActive = false;
      }
      if (!secondMinActive) {
        secondMinWasActive = false;
      }
      if (!secondMaxActive) {
        secondMaxWasActive = false;
      }

      if ((firstMinActive && !firstMinWasActive) || (firstMaxActive && !firstMaxWasActive)) {
        firstBlocked = true;
      }
      if ((secondMinActive && !secondMinWasActive) || (secondMaxActive && !secondMaxWasActive)) {
        secondBlocked = true;
      }

      if (firstBlocked || secondBlocked) {
        return false;
      }
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

    // Normal moves stop everything as soon as either axis hits a limit;
    // homing/probing keeps the per-axis behavior so each axis can finish
    // reaching its own switch.
    if (stopOnAnyNewLimit && (firstBlocked || secondBlocked)) {
      return false;
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

// Set by a caller (STEP-and-check-error callers) when a following error past
// the configured limit stops a move outright, distinct from a limit switch or
// an explicit STOP. Read by the command handler to word the reply correctly.
bool xyFollowErrorTripped = false;
float xyLastFollowErrorA = 0.0f;
float xyLastFollowErrorB = 0.0f;
float xyPeakFollowErrorA = 0.0f;
float xyPeakFollowErrorB = 0.0f;

// One control-loop tick: read both encoders, update following-error stats,
// apply PID correction to the per-motor step accumulators. Called periodically
// from inside the stepping loop below, not from a separate timer - see the
// design note at the top of the encoder section.
//
// Correction works by nudging the Bresenham accumulator that decides whether a
// motor steps on the next iteration: a positive correction on a motor that is
// behind makes it more likely to step next, which is the discrete-time
// equivalent of trimming a continuous setpoint. It cannot un-issue a pulse
// already sent, only bias the next one - which is the only lever a step/dir
// interface gives a control loop.
bool applyPidCorrectionTick(
  long commandedA,   // xAxis.currentSteps: motor A's own step count so far
  long commandedB,   // yAxis.currentSteps: motor B's own step count so far
  long &accumulatorA,
  long &accumulatorB,
  long totalIterations
) {
  if (!encodersConfigured) {
    return true;
  }

  bool okA = readEncoderChannel(encoderA);
  bool okB = readEncoderChannel(encoderB);

  // A motor step is ENCODER_COUNTS_PER_REV / stepsPerRevolution counts, so a
  // step-space error compares directly against the encoder-space one.
  float countsPerStep = (float)ENCODER_COUNTS_PER_REV / (float)stepsPerRevolution;
  float measuredA = (float)encoderAccumulatedCounts(encoderA) / countsPerStep;
  float measuredB = (float)encoderAccumulatedCounts(encoderB) / countsPerStep;

  float errorA = (float)commandedA - measuredA;
  float errorB = (float)commandedB - measuredB;
  xyLastFollowErrorA = errorA;
  xyLastFollowErrorB = errorB;
  xyPeakFollowErrorA = max(xyPeakFollowErrorA, fabsf(errorA));
  xyPeakFollowErrorB = max(xyPeakFollowErrorB, fabsf(errorB));

  // A motor's own error in counts, for the fault threshold - which is
  // specified in encoder counts, not steps, since that is the sensor's native
  // unit and what an operator tunes against.
  float errorCountsA = errorA * countsPerStep;
  float errorCountsB = errorB * countsPerStep;
  if (fabsf(errorCountsA) > xyFollowLimitCounts || fabsf(errorCountsB) > xyFollowLimitCounts) {
    xyFollowErrorTripped = true;
    return false;
  }

  if (!okA || !okB) {
    // A read fault does not by itself stop the move - transient SPI noise
    // should not abort a physical motion - but no correction is applied this
    // tick, since the measurement cannot be trusted.
    return true;
  }

  if (xyPid.kp == 0.0f && xyPid.ki == 0.0f && xyPid.kd == 0.0f) {
    return true;   // inert by default; nothing below has any effect
  }

  if (!xyPid.primed) {
    xyPid.lastMeasuredA = measuredA;
    xyPid.lastMeasuredB = measuredB;
    xyPid.primed = true;
  }

  xyPid.integralA = constrain(xyPid.integralA + errorA, -(float)xyIntegralClampCounts, (float)xyIntegralClampCounts);
  xyPid.integralB = constrain(xyPid.integralB + errorB, -(float)xyIntegralClampCounts, (float)xyIntegralClampCounts);

  // Derivative on measurement, not on error: a moving setpoint (which this is,
  // every iteration) would otherwise produce a derivative kick unrelated to
  // any actual disturbance.
  float derivativeA = -(measuredA - xyPid.lastMeasuredA);
  float derivativeB = -(measuredB - xyPid.lastMeasuredB);
  xyPid.lastMeasuredA = measuredA;
  xyPid.lastMeasuredB = measuredB;

  float outputA = xyPid.kp * errorA + xyPid.ki * xyPid.integralA + xyPid.kd * derivativeA;
  float outputB = xyPid.kp * errorB + xyPid.ki * xyPid.integralB + xyPid.kd * derivativeB;

  // Bias the Bresenham accumulator directly: adding to it makes the next
  // iteration more likely to cross the totalIterations threshold and step,
  // which is how a positive (behind-target) error pulls a step forward in
  // time. Clamped to a fraction of one full step per tick so a large error
  // cannot demand many steps at once - the rate limit called for in the plan,
  // enforced here because there is no separate trajectory generator yet to
  // enforce it upstream.
  long biasA = constrain((long)outputA, -1L, 1L);
  long biasB = constrain((long)outputB, -1L, 1L);
  if (totalIterations > 0) {
    accumulatorA += biasA * totalIterations / 4;
    accumulatorB += biasB * totalIterations / 4;
  }

  return true;
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
  xyFollowErrorTripped = false;
  xyLastFollowErrorA = 0.0f;
  xyLastFollowErrorB = 0.0f;
  xyPeakFollowErrorA = 0.0f;
  xyPeakFollowErrorB = 0.0f;
  xyPid.integralA = 0.0f;
  xyPid.integralB = 0.0f;
  xyPid.primed = false;
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

  // Switches already pressed when the move starts stay latched until they
  // release, so a move can still escape a limit it is parked on (e.g. after
  // calibration). Any switch that becomes pressed during the move stops the
  // whole move instantly, regardless of travel direction.
  bool xMinWasActive = useLimitChecks && isLimitActive(xAxis.minLimitPin);
  bool xMaxWasActive = useLimitChecks && xyLimitSwitchMode == 4 && isLimitActive(xAxis.maxLimitPin);
  bool yMinWasActive = useLimitChecks && isLimitActive(yAxis.minLimitPin);
  bool yMaxWasActive = useLimitChecks && xyLimitSwitchMode == 4 && isLimitActive(yAxis.maxLimitPin);

  for (long iteration = 0; iteration < totalIterations; iteration++) {
    if (consumeStopCommandIfPresent()) {
      stopRequested = true;
      return false;
    }

    if (useLimitChecks) {
      bool xMinActive = isLimitActive(xAxis.minLimitPin);
      bool xMaxActive = xyLimitSwitchMode == 4 && isLimitActive(xAxis.maxLimitPin);
      bool yMinActive = isLimitActive(yAxis.minLimitPin);
      bool yMaxActive = xyLimitSwitchMode == 4 && isLimitActive(yAxis.maxLimitPin);

      if (!xMinActive) {
        xMinWasActive = false;
      }
      if (!xMaxActive) {
        xMaxWasActive = false;
      }
      if (!yMinActive) {
        yMinWasActive = false;
      }
      if (!yMaxActive) {
        yMaxWasActive = false;
      }

      if ((xMinActive && !xMinWasActive) || (xMaxActive && !xMaxWasActive)) {
        xBlocked = true;
      }
      if ((yMinActive && !yMinWasActive) || (yMaxActive && !yMaxWasActive)) {
        yBlocked = true;
      }

      // Never drive further into a pressed switch, latched or not.
      if (xSign > 0 && xMaxActive) {
        xBlocked = true;
      }
      if (xSign < 0 && xMinActive) {
        xBlocked = true;
      }
      if (ySign > 0 && yMaxActive) {
        yBlocked = true;
      }
      if (ySign < 0 && yMinActive) {
        yBlocked = true;
      }

      if (xBlocked || yBlocked) {
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

    // Closed-loop correction tick. Every Nth iteration rather than every one,
    // so an SPI round trip is not inserted between every single step pulse -
    // see the design note above applyPidCorrectionTick. This is what makes the
    // correction continuous through the move instead of only happening at the
    // end: it runs dozens of times per move even at modest step counts.
    if (encodersConfigured && (iteration % PID_CHECK_EVERY_N_ITERATIONS) == 0) {
      if (!applyPidCorrectionTick(xAxis.currentSteps, yAxis.currentSteps, accumulatorA, accumulatorB, totalIterations)) {
        return false;
      }
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
    if (xyFollowErrorTripped) {
      // Distinct from a limit switch: nothing physically stopped the
      // carriage, the motors simply fell further behind the encoders than the
      // configured threshold allows. Reported in encoder counts, which is
      // what the threshold itself is specified in.
      Serial.print("ERR FOLLOW ERROR XY ");
      Serial.print(xyLastFollowErrorA, 2);
      Serial.print(" ");
      Serial.println(xyLastFollowErrorB, 2);
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

  if (encodersConfigured) {
    // Peak error during the move is the more useful number for tuning: the
    // final error alone hides a large excursion that the loop pulled back in.
    Serial.print("FOLLOW ERROR PEAK ");
    Serial.print(xyPeakFollowErrorA, 2);
    Serial.print(" ");
    Serial.println(xyPeakFollowErrorB, 2);
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
  float yTrackLengthCm,
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
      yAxis.trackLengthCm,
      slowProbeRpmFor(rpm),
      true,
      accelerationRpmPerSecond,
      stepsPerRevolution,
      DEFAULT_MAX_PROBE_ROTATIONS,
      DEFAULT_X_CALIBRATION_Y_ROTATIONS,
      xyLimitBufferCm
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
    false,
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
    false,
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
    false,
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
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  long &stepsTaken,
  bool &stopRequested,
  bool &limitHit
) {
  digitalWrite(xAxis.dirPin, dirLevel);
  digitalWrite(yAxis.dirPin, dirLevel);
  delayMicroseconds(20);

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

    // Ramp the step interval so acceleration is honored. For a limit probe
    // (stopLimitPin >= 0) the deceleration phase near maxSteps is never reached
    // because we stop on contact, so this effectively just accelerates.
    int activeRpm = rpmForTrapezoidIteration(step, maxSteps, rpm, trapezoidalSpeed, accelerationRpmPerSecond);
    unsigned long intervalMicros = stepIntervalMicrosForRPM(activeRpm);
    unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
      ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
      : (unsigned long)STEP_PULSE_WIDTH_US;
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
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  long maxProbeSteps,
  long &fastSteps,
  long &slowSteps
) {
  bool stopRequested = false;
  bool limitHit = false;
  long ignoredSteps = 0;

  // Fast touch: drive toward the switch until it trips (accelerates on the way).
  driveXAxis(calibrationRPM, maxProbeSteps, dirToward, towardStep, limitPin, trapezoidalSpeed, accelerationRpmPerSecond, fastSteps, stopRequested, limitHit);
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
  driveXAxis(calibrationRPM, backoffSteps, dirAway, awayStep, -1, trapezoidalSpeed, accelerationRpmPerSecond, ignoredSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }

  // Slow re-touch (reversed direction again), capped a bit past the back-off.
  long slowTravelCap = backoffSteps * 2;
  driveXAxis(XY_SLOW_HOMING_RPM, slowTravelCap, dirToward, towardStep, limitPin, trapezoidalSpeed, accelerationRpmPerSecond, slowSteps, stopRequested, limitHit);
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

// Drives pure Y motion on the CoreXY belt: the A and B motors turn in opposite
// directions. positionStep is the cartesian Y direction (-1 toward Y-min).
bool driveYAxis(
  int rpm,
  long maxSteps,
  int positionStep,
  int stopLimitPin,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  long &stepsTaken,
  bool &stopRequested,
  bool &limitHit
) {
  bool towardMin = positionStep < 0;
  // CoreXY cartesian Y is A - B. With this machine's direction levels, -Y
  // (toward Y-min) therefore needs A toward X-max and B toward X-min. Keep
  // this mapping aligned with runCoreXYCartesianMove(deltaX=0, deltaY), whose
  // -Y direction is A=LOW/B=HIGH and +Y is A=HIGH/B=LOW.
  digitalWrite(xAxis.dirPin, towardMin ? XY_DIR_TOWARD_X_MAX : XY_DIR_TOWARD_X_MIN);
  digitalWrite(yAxis.dirPin, towardMin ? XY_DIR_TOWARD_X_MIN : XY_DIR_TOWARD_X_MAX);
  delayMicroseconds(20);

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

    xAxis.currentSteps += towardMin ? -1 : 1;
    yAxis.currentSteps += towardMin ? 1 : -1;
    currentYSteps += positionStep;
    stepsTaken++;

    int activeRpm = rpmForTrapezoidIteration(step, maxSteps, rpm, trapezoidalSpeed, accelerationRpmPerSecond);
    unsigned long intervalMicros = stepIntervalMicrosForRPM(activeRpm);
    unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
      ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
      : (unsigned long)STEP_PULSE_WIDTH_US;
    delayMicroseconds(lowTimeMicros);
  }

  return true;
}

// Three-pass Y-min homing, mirroring homeXAgainstSwitch: fast touch, back off
// one rotation, then slow re-touch. Leaves the carriage resting on the switch.
bool homeYMinSwitch(
  int calibrationRPM,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  long maxProbeSteps,
  long &fastSteps,
  long &slowSteps
) {
  bool stopRequested = false;
  bool limitHit = false;
  long ignoredSteps = 0;

  driveYAxis(calibrationRPM, maxProbeSteps, -1, yAxis.minLimitPin, trapezoidalSpeed, accelerationRpmPerSecond, fastSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }
  if (!limitHit) {
    printXYProbeFailure("Y_MIN", yAxis.minLimitPin, maxProbeSteps, false);
    return false;
  }

  long backoffSteps = stepsPerRevolution;
  driveYAxis(calibrationRPM, backoffSteps, +1, -1, trapezoidalSpeed, accelerationRpmPerSecond, ignoredSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }

  long slowTravelCap = backoffSteps * 2;
  driveYAxis(XY_SLOW_HOMING_RPM, slowTravelCap, -1, yAxis.minLimitPin, trapezoidalSpeed, accelerationRpmPerSecond, slowSteps, stopRequested, limitHit);
  if (stopRequested) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }
  if (!limitHit) {
    printXYProbeFailure("Y_MIN", yAxis.minLimitPin, slowTravelCap, false);
    return false;
  }

  return true;
}

// If a limit switch is already pressed when calibration starts, nudge the
// carriage away from it instead of refusing to calibrate. Errors only when a
// switch stays pressed after the full nudge (stuck or miswired switch).
bool nudgeAwayFromPressedLimits(int rpm, bool trapezoidalSpeed, int accelerationRpmPerSecond) {
  long ignoredSteps = 0;
  bool stopRequested = false;
  bool limitHit = false;

  for (int index = 0; index < 4; index++) {
    int pin = index == 0 ? xAxis.minLimitPin
      : index == 1 ? xAxis.maxLimitPin
      : index == 2 ? yAxis.minLimitPin
      : yAxis.maxLimitPin;
    const char *name = index == 0 ? "X_MIN" : index == 1 ? "X_MAX" : index == 2 ? "Y_MIN" : "Y_MAX";
    bool isYSwitch = index >= 2;
    int awayStep = (index == 0 || index == 2) ? +1 : -1;

    if (!isLimitActive(pin)) {
      continue;
    }

    Serial.print("XY LIMIT PRESSED - NUDGING AWAY FROM ");
    Serial.println(name);

    // Back off one rotation at a time, re-reading the switch between each, so
    // the carriage travels no further than it takes to free the switch.
    int rotations = 0;
    while (rotations < XY_LIMIT_NUDGE_MAX_ROTATIONS && isLimitActive(pin)) {
      if (isYSwitch) {
        driveYAxis(
          rpm, stepsPerRevolution, awayStep, -1,
          trapezoidalSpeed, accelerationRpmPerSecond,
          ignoredSteps, stopRequested, limitHit);
      } else {
        driveXAxis(
          rpm,
          stepsPerRevolution,
          awayStep > 0 ? XY_DIR_TOWARD_X_MAX : XY_DIR_TOWARD_X_MIN,
          awayStep,
          -1,
          trapezoidalSpeed,
          accelerationRpmPerSecond,
          ignoredSteps,
          stopRequested,
          limitHit
        );
      }

      if (stopRequested) {
        Serial.println("ERR STOP CALIBRATE XY");
        return false;
      }
      rotations++;
    }

    if (isLimitActive(pin)) {
      Serial.print("ERR XY LIMIT STUCK ");
      Serial.print(name);
      Serial.print(" - STILL PRESSED AFTER ");
      Serial.print((long)rotations * stepsPerRevolution);
      Serial.print(" STEPS (");
      Serial.print(rotations);
      Serial.println(" ROTATIONS), CHECK SWITCH WIRING");
      return false;
    }

    Serial.print("XY LIMIT ");
    Serial.print(name);
    Serial.print(" FREED AFTER STEPS ");
    Serial.print((long)rotations * stepsPerRevolution);
    Serial.print(" ROTATIONS ");
    Serial.println(rotations);
  }

  return true;
}

// Pulses a single CoreXY motor so the operator can see which physical motor is A
// and which is B. On a CoreXY, driving one motor alone moves the carriage
// diagonally (both X and Y by half the step count) rather than along an axis --
// that diagonal is what tells the two motors apart by eye.
//
// The carriage moves without cartesian tracking, so any stored position stops
// being true; the calibration is dropped rather than left quietly wrong. Every
// limit switch is watched, since a diagonal can reach any of them.
bool testSingleMotor(char motor, long steps, bool forward, int rpm) {
  AxisChannel &axis = motor == 'A' ? xAxis : yAxis;

  if (steps <= 0) {
    Serial.println("ERR TEST MOTOR STEPS");
    return false;
  }

  Serial.print("ACTIVE TEST MOTOR ");
  Serial.print(motor);
  Serial.print(" STEPS ");
  Serial.print(steps);
  Serial.print(" DIR ");
  Serial.print(forward ? 1 : 0);
  Serial.print(" RPM ");
  Serial.print(rpm);
  Serial.print(" STEP_PIN ");
  Serial.print(axis.stepPin);
  Serial.print(" DIR_PIN ");
  Serial.println(axis.dirPin);
  printXYLimitState("TEST_START");

  invalidateXCalibrationState();
  setXYMotorsEnabled(true);

  digitalWrite(axis.dirPin, forward ? XY_DIR_TOWARD_X_MAX : XY_DIR_TOWARD_X_MIN);
  delayMicroseconds(20);

  long taken = 0;
  for (long step = 0; step < steps; step++) {
    if (consumeStopCommandIfPresent()) {
      return false;
    }
    if (isLimitActive(xAxis.minLimitPin) || isLimitActive(xAxis.maxLimitPin)
        || isLimitActive(yAxis.minLimitPin) || isLimitActive(yAxis.maxLimitPin)) {
      Serial.print("ERR TEST MOTOR LIMIT AFTER STEPS ");
      Serial.println(taken);
      return false;
    }

    digitalWrite(axis.stepPin, HIGH);
    delayMicroseconds(STEP_PULSE_WIDTH_US);
    digitalWrite(axis.stepPin, LOW);
    taken++;

    unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
    unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
      ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
      : (unsigned long)STEP_PULSE_WIDTH_US;
    delayMicroseconds(lowTimeMicros);
  }

  Serial.print("TEST MOTOR STEPPED ");
  Serial.println(taken);
  printXYLimitState("TEST_END");
  Serial.println("OK TEST MOTOR");
  return true;
}

bool handleTestMotorCommand(const String &cmd) {
  char motorBuffer[8] = "A";
  long steps = 2000;
  int dirFlag = 1;
  int rpm = 60;
  int parsed = sscanf(cmd.c_str(), "TEST MOTOR %7s %ld %d %d", motorBuffer, &steps, &dirFlag, &rpm);
  if (parsed < 1) {
    return false;
  }

  char motor = toupper(motorBuffer[0]);
  if (motor != 'A' && motor != 'B') {
    Serial.println("ERR TEST MOTOR NAME");
    return true;
  }

  testSingleMotor(
    motor,
    parsed >= 2 ? steps : 2000,
    parsed >= 3 ? dirFlag != 0 : true,
    parsed >= 4 ? rpm : 60
  );
  return true;
}

bool calibrateXY(
  float xTrackLengthCm,
  float yTrackLengthCm,
  int calibrationRPM,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond,
  int nextStepsPerRotation,
  int maxProbeRotations,
  float xCalibrationYRotations,
  float limitBufferCm
) {
  // Adopt the buffer before anything converts cm to steps: it sets where user
  // coordinate 0 sits, so the park, the X walk-back and every later move all
  // have to agree on it.
  xyLimitBufferCm = limitBufferCm >= 0.0f ? limitBufferCm : DEFAULT_XY_LIMIT_BUFFER_CM;
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
  Serial.print(maxProbeSteps);
  Serial.print(" LIMIT_BUFFER_CM ");
  Serial.println(xyLimitBufferCm, 3);
  printXYMotorPinState("CALIBRATE");
  printXYLimitState("START");

  // Drop any previous calibration before moving. Everything below shifts the
  // carriage, so a run that fails part way through leaves the stored position
  // wrong; keeping it would let the next move compute its path from a position
  // the machine is not at. Moves refuse with ERR X NOT CALIBRATED until a run
  // completes and re-establishes both origins.
  invalidateXCalibrationState();

  setXYMotorsEnabled(true);

  // If a switch is already pressed, nudge the carriage off it instead of
  // refusing. Only a switch that stays pressed after the nudge is an error.
  if (!nudgeAwayFromPressedLimits(calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond)) {
    return false;
  }

  // ---- Home Y-min first: this defines Y = 0 so the Y position is known
  //      before X homing, then park a fixed distance above the Y switch. ----
  long yMinFastSteps = 0;
  long yMinSlowSteps = 0;
  if (!homeYMinSwitch(
        calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, maxProbeSteps,
        yMinFastSteps, yMinSlowSteps)) {
    return false;
  }
  currentYSteps = 0;
  Serial.print("COREXY Y MIN HOMED FAST_STEPS ");
  Serial.print(yMinFastSteps);
  Serial.print(" SLOW_STEPS ");
  Serial.println(yMinSlowSteps);

  // Park clear of the Y switch so X is swept at a safe Y rather than hard against
  // the Y stop. The park is in motor rotations, so it is exact in steps with no
  // dependence on a measured (or guessed) steps-per-cm.
  long yParkTargetSteps = lroundf(xCalibrationYRotations * (float)stepsPerRevolution);
  if (yParkTargetSteps < 1) {
    yParkTargetSteps = 1;
  }
  long yParkSteps = 0;
  bool yParkStop = false;
  bool yParkLimit = false;
  driveYAxis(
    calibrationRPM, yParkTargetSteps, +1, -1,
    trapezoidalSpeed, accelerationRpmPerSecond, yParkSteps, yParkStop, yParkLimit);
  if (yParkStop) {
    Serial.println("ERR STOP CALIBRATE XY");
    return false;
  }
  Serial.print("COREXY Y PARKED STEPS ");
  Serial.print(currentYSteps);
  Serial.print(" ROTATIONS ");
  Serial.println(xCalibrationYRotations, 3);

  // ---- Home X-min: the refined slow touch defines X = 0. The Y position set
  //      above is preserved (pure-X moves do not change currentYSteps). ----
  long minFastSteps = 0;
  long minSlowSteps = 0;
  if (!homeXAgainstSwitch(
        "X_MIN", xAxis.minLimitPin,
        XY_DIR_TOWARD_X_MIN, XY_DIR_TOWARD_X_MAX,
        -1, +1,
        calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, maxProbeSteps,
        minFastSteps, minSlowSteps)) {
    return false;
  }
  xAxis.currentSteps = 0;
  yAxis.currentSteps = 0;
  currentXSteps = 0;
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
        calibrationRPM, trapezoidalSpeed, accelerationRpmPerSecond, maxProbeSteps,
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
  // Y was homed against its Y-min switch and parked at +XY_CALIBRATION_Y_PARK_STEPS,
  // so currentYSteps already holds the real position. Y reuses the X steps-per-cm
  // and takes its track length from the calibrate input.
  yAxis.trackLengthCm = yTrackLengthCm;
  yStepsPerCm = xStepsPerCm;
  yPositionKnown = true;

  // Homing deliberately leaves the carriage resting on the X-max switch. Walk it
  // back by one buffer so calibration never finishes with a limit pressed: this
  // releases the switch and lands exactly on the usable max (physical
  // trackLength - buffer), which is the highest X a later move can ask for.
  long xMaxBackoffSteps = lroundf(xyLimitBufferCm * xStepsPerCm);
  if (xMaxBackoffSteps > 0) {
    long backedOffSteps = 0;
    bool backoffStopRequested = false;
    bool backoffLimitHit = false;
    driveXAxis(
      calibrationRPM, xMaxBackoffSteps, XY_DIR_TOWARD_X_MIN, -1, -1,
      trapezoidalSpeed, accelerationRpmPerSecond,
      backedOffSteps, backoffStopRequested, backoffLimitHit);
    if (backoffStopRequested) {
      saveXCalibrationState();
      Serial.println("ERR STOP CALIBRATE XY");
      return false;
    }
    Serial.print("COREXY X MAX BACKED OFF STEPS ");
    Serial.print(backedOffSteps);
    Serial.print(" POSITION_STEPS ");
    Serial.println(currentXSteps);

    // The measurement is already valid, so a switch that stays pressed after the
    // back-off is reported without discarding the calibration.
    if (isLimitActive(xAxis.maxLimitPin)) {
      Serial.println("WARN XY X_MAX STILL PRESSED AFTER BACKOFF - CHECK SWITCH WIRING");
    }
  }

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
  driveXAxis(rpm, steps, dirLevel, positionStep, travelLimitPin, true, 600, stepsTaken, stopRequested, limitHit);

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

// Coordinated straight-line CoreXY move from the current position to (targetXCm,
// targetYCm), in cm. Y reuses the X steps-per-cm (same belt/motor) and its track
// length is provided per move. Trapezoidal ramping optional. Fails immediately
// (before moving) if the target is outside the workspace, and stops immediately
// if any limit switch in the travel direction trips.
bool moveGantryXYTo(
  float targetXCm,
  float targetYCm,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond
) {
  if (!xyCalibrated) {
    Serial.println("ERR X NOT CALIBRATED");
    return false;
  }

  // Steps-per-cm and the Y track length come from the last calibration.
  float stepsPerCm = xStepsPerCm;
  float yTrackCm = yAxis.trackLengthCm;

  // The usable coordinate space is inset from each limit switch by
  // xyLimitBufferCm: user coordinate 0 maps to xyLimitBufferCm away from
  // the min switch, and the usable max is trackLength - 2 * buffer. This keeps
  // moves to 0 or to the max clear of the switches.
  float usableXMaxCm = xAxis.trackLengthCm - 2.0f * xyLimitBufferCm;
  float usableYMaxCm = yTrackCm - 2.0f * xyLimitBufferCm;
  if (targetXCm < 0.0f || targetXCm > usableXMaxCm
      || targetYCm < 0.0f || targetYCm > usableYMaxCm) {
    Serial.print("ERR XY TARGET RANGE X ");
    Serial.print(targetXCm, 3);
    Serial.print(" Y ");
    Serial.print(targetYCm, 3);
    Serial.print(" USABLE_MAX ");
    Serial.print(usableXMaxCm, 3);
    Serial.print(" ");
    Serial.println(usableYMaxCm, 3);
    return false;
  }

  // Shift user coordinates into physical coordinates (0 -> buffer).
  long targetXSteps = lroundf((targetXCm + xyLimitBufferCm) * stepsPerCm);
  long targetYSteps = lroundf((targetYCm + xyLimitBufferCm) * stepsPerCm);
  long deltaX = targetXSteps - currentXSteps;
  long deltaY = targetYSteps - currentYSteps;

  // CoreXY: motor A = X + Y, motor B = X - Y (in steps).
  long deltaA = deltaX + deltaY;
  long deltaB = deltaX - deltaY;
  long absA = labs(deltaA);
  long absB = labs(deltaB);
  long absX = labs(deltaX);
  long absY = labs(deltaY);
  long totalIterations = max(absA, absB);

  int xSign = deltaX > 0 ? 1 : deltaX < 0 ? -1 : 0;
  int ySign = deltaY > 0 ? 1 : deltaY < 0 ? -1 : 0;

  // Positive motor delta -> LOW dir level (matches the +X = LOW wiring convention).
  bool aPositive = deltaA >= 0;
  bool bPositive = deltaB >= 0;
  digitalWrite(xAxis.dirPin, aPositive ? LOW : HIGH);
  digitalWrite(yAxis.dirPin, bPositive ? LOW : HIGH);
  delayMicroseconds(20);

  Serial.print("ACTIVE MOVE XY CM ");
  Serial.print(targetXCm, 3);
  Serial.print(" ");
  Serial.print(targetYCm, 3);
  Serial.print(" RPM ");
  Serial.print(rpm);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);

  setXYMotorsEnabled(true);

  if (totalIterations == 0) {
    saveXCalibrationState();
    Serial.println("OK MOVE XY");
    return true;
  }

  long accumulatorA = 0;
  long accumulatorB = 0;
  long accumulatorX = 0;
  long accumulatorY = 0;

  for (long iteration = 0; iteration < totalIterations; iteration++) {
    if (consumeStopCommandIfPresent()) {
      // Position was tracked incrementally, so it is already current.
      // consumeStopCommandIfPresent() has already acknowledged with "OK STOP";
      // printing it again would leave a second copy in the serial buffer, which
      // the host reads as the reply to whatever command it sends next and treats
      // as that command having been cancelled.
      saveXCalibrationState();
      return false;
    }

    // Immediate fault if a limit switch in the travel direction trips.
    if ((xSign > 0 && isLimitActive(xAxis.maxLimitPin))
        || (xSign < 0 && isLimitActive(xAxis.minLimitPin))
        || (ySign > 0 && isLimitActive(yAxis.maxLimitPin))
        || (ySign < 0 && isLimitActive(yAxis.minLimitPin))) {
      saveXCalibrationState();
      Serial.println("ERR ESTOP XY LIMIT");
      return false;
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

    // Track cartesian position alongside the motor motion.
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
      int activeRpm = rpmForTrapezoidIteration(iteration, totalIterations, rpm, trapezoidalSpeed, accelerationRpmPerSecond);
      unsigned long intervalMicros = stepIntervalMicrosForRPM(activeRpm);
      unsigned long lowTimeMicros = intervalMicros > (unsigned long)STEP_PULSE_WIDTH_US
        ? intervalMicros - (unsigned long)STEP_PULSE_WIDTH_US
        : (unsigned long)STEP_PULSE_WIDTH_US;
      delayMicroseconds(lowTimeMicros);
    }
  }

  currentXSteps = targetXSteps;
  currentYSteps = targetYSteps;
  saveXCalibrationState();

  Serial.print("XY POSITION CM ");
  Serial.print(stepsToCm(currentXSteps, stepsPerCm), 3);
  Serial.print(" ");
  Serial.println(stepsToCm(currentYSteps, stepsPerCm), 3);
  Serial.println("OK MOVE XY");
  return true;
}

bool circleGantryXY(
  float centerXCm,
  float centerYCm,
  float radiusCm,
  int rpm,
  bool trapezoidalSpeed,
  int accelerationRpmPerSecond
) {
  if (!xyCalibrated) {
    Serial.println("ERR X NOT CALIBRATED");
    return false;
  }

  if (radiusCm <= 0.0f) {
    Serial.println("ERR CIRCLE RADIUS");
    return false;
  }

  // The full circle must fit inside the usable (buffer-inset) workspace, where
  // user coordinate 0 is xyLimitBufferCm off the min switch and the usable
  // max is trackLength - 2 * buffer.
  float usableXMaxCm = xAxis.trackLengthCm - 2.0f * xyLimitBufferCm;
  float usableYMaxCm = yAxis.trackLengthCm - 2.0f * xyLimitBufferCm;
  if (centerXCm - radiusCm < 0.0f || centerXCm + radiusCm > usableXMaxCm
      || centerYCm - radiusCm < 0.0f || centerYCm + radiusCm > usableYMaxCm) {
    Serial.print("ERR CIRCLE RANGE CENTER ");
    Serial.print(centerXCm, 3);
    Serial.print(" ");
    Serial.print(centerYCm, 3);
    Serial.print(" RADIUS ");
    Serial.print(radiusCm, 3);
    Serial.print(" USABLE_MAX ");
    Serial.print(usableXMaxCm, 3);
    Serial.print(" ");
    Serial.println(usableYMaxCm, 3);
    return false;
  }

  // Travel to the circle start point (angle 0, right of center) as a normal
  // straight move with its own ramp.
  if (!moveGantryXYTo(centerXCm + radiusCm, centerYCm, rpm, trapezoidalSpeed, accelerationRpmPerSecond)) {
    return false;
  }

  Serial.print("ACTIVE CIRCLE XY CENTER ");
  Serial.print(centerXCm, 3);
  Serial.print(" ");
  Serial.print(centerYCm, 3);
  Serial.print(" RADIUS ");
  Serial.print(radiusCm, 3);
  Serial.print(" RPM ");
  Serial.print(rpm);
  Serial.print(" TRAPEZOID ");
  Serial.print(trapezoidalSpeed ? 1 : 0);
  Serial.print(" ACCEL ");
  Serial.println(accelerationRpmPerSecond);

  setXYMotorsEnabled(true);

  // Short chords approximate the arc; ~0.5 mm keeps the path visibly round.
  float circumferenceCm = 2.0f * PI * radiusCm;
  int segments = max(24, (int)ceilf(circumferenceCm / 0.05f));
  // Motor iterations per chord are |dx| + |dy| steps, which integrates to
  // (4 / pi) x circumference over a lap; used to shape one acceleration and
  // deceleration profile across the whole circle instead of per chord.
  long totalProfileIterations = lroundf(circumferenceCm * xStepsPerCm * 4.0f / PI);
  long profileIterationsDone = 0;

  // Circle points are in user coordinates; shift into physical (0 -> buffer) to
  // match the position tracked by the approach move above.
  for (int segment = 1; segment <= segments; segment++) {
    float angle = (2.0f * PI * segment) / segments;
    long targetXSteps = lroundf((centerXCm + xyLimitBufferCm + radiusCm * cosf(angle)) * xStepsPerCm);
    long targetYSteps = lroundf((centerYCm + xyLimitBufferCm + radiusCm * sinf(angle)) * yStepsPerCm);
    long deltaX = targetXSteps - currentXSteps;
    long deltaY = targetYSteps - currentYSteps;
    if (deltaX == 0 && deltaY == 0) {
      continue;
    }

    long chordIterations = labs(deltaX) + labs(deltaY);
    int segmentRpm = trapezoidalSpeed
      ? rpmForTrapezoidIteration(
          profileIterationsDone + chordIterations / 2,
          totalProfileIterations,
          rpm,
          true,
          accelerationRpmPerSecond
        )
      : rpm;

    bool xBlocked = false;
    bool yBlocked = false;
    bool stopRequested = false;
    bool moved = runCoreXYCartesianMove(
      deltaX,
      deltaY,
      segmentRpm,
      false,
      accelerationRpmPerSecond,
      true,
      xBlocked,
      yBlocked,
      stopRequested
    );

    if (!moved) {
      saveXCalibrationState();
      if (stopRequested) {
        // consumeStopCommandIfPresent already acknowledged with OK STOP.
        return false;
      }
      Serial.println("ERR ESTOP XY LIMIT");
      return false;
    }

    profileIterationsDone += chordIterations;
  }

  saveXCalibrationState();
  Serial.print("XY POSITION CM ");
  Serial.print(stepsToCm(currentXSteps, xStepsPerCm), 3);
  Serial.print(" ");
  Serial.println(stepsToCm(currentYSteps, xStepsPerCm), 3);
  Serial.println("OK CIRCLE XY");
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

bool handleGotoXYCommand(const String &cmd) {
  float targetXCm = 0.0f;
  float targetYCm = 0.0f;
  int rpm = 240;
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 600;
  int parsed = sscanf(
    cmd.c_str(),
    "GOTOXY %f %f %d %d %d",
    &targetXCm,
    &targetYCm,
    &rpm,
    &trapezoidFlag,
    &accelerationRpmPerSecond
  );
  if (parsed < 2) {
    return false;
  }

  moveGantryXYTo(
    targetXCm,
    targetYCm,
    parsed >= 3 ? rpm : 240,
    parsed >= 4 ? trapezoidFlag != 0 : true,
    parsed >= 5 ? accelerationRpmPerSecond : 600
  );
  return true;
}

bool handleCircleXYCommand(const String &cmd) {
  float centerXCm = 0.0f;
  float centerYCm = 0.0f;
  float radiusCm = 0.0f;
  int rpm = 400;
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 600;
  int parsed = sscanf(
    cmd.c_str(),
    "CIRCLEXY %f %f %f %d %d %d",
    &centerXCm,
    &centerYCm,
    &radiusCm,
    &rpm,
    &trapezoidFlag,
    &accelerationRpmPerSecond
  );
  if (parsed < 3) {
    return false;
  }

  circleGantryXY(
    centerXCm,
    centerYCm,
    radiusCm,
    parsed >= 4 ? rpm : 400,
    parsed >= 5 ? trapezoidFlag != 0 : true,
    parsed >= 6 ? accelerationRpmPerSecond : 600
  );
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

bool handleSetEncoderPinsCommand(const String &cmd) {
  int csA = -1;
  int csB = -1;
  int parsed = sscanf(cmd.c_str(), "SET ENCODER PINS %d %d", &csA, &csB);
  if (parsed != 2) {
    return false;
  }
  configureEncoderPins(csA, csB);
  Serial.print("OK ENCODER PINS ");
  Serial.print(csA);
  Serial.print(" ");
  Serial.println(csB);
  return true;
}

bool handleEncoderQueryCommand(const String &cmd) {
  if (cmd != "ENCODER?") {
    return false;
  }
  if (!encodersConfigured) {
    Serial.println("ERR ENCODER NOT CONFIGURED");
    return true;
  }
  bool okA = readEncoderChannel(encoderA);
  bool okB = readEncoderChannel(encoderB);
  Serial.print("OK ENCODER A ");
  Serial.print(encoderA.lastRaw);
  Serial.print(" ");
  Serial.print(encoderAccumulatedCounts(encoderA));
  Serial.print(" ");
  Serial.print(okA ? 1 : 0);
  Serial.print(" B ");
  Serial.print(encoderB.lastRaw);
  Serial.print(" ");
  Serial.print(encoderAccumulatedCounts(encoderB));
  Serial.print(" ");
  Serial.println(okB ? 1 : 0);
  return true;
}

bool handleSetXYPidCommand(const String &cmd) {
  float kp = 0.0f;
  float ki = 0.0f;
  float kd = 0.0f;
  int parsed = sscanf(cmd.c_str(), "SET XY PID %f %f %f", &kp, &ki, &kd);
  if (parsed != 3) {
    return false;
  }
  xyPid.kp = kp;
  xyPid.ki = ki;
  xyPid.kd = kd;
  // A gain change invalidates any accumulated integral - starting a new set
  // of gains with an old integral term would apply a correction the operator
  // never asked for.
  xyPid.integralA = 0.0f;
  xyPid.integralB = 0.0f;
  xyPid.primed = false;
  Serial.print("OK XY PID ");
  Serial.print(kp, 4);
  Serial.print(" ");
  Serial.print(ki, 4);
  Serial.print(" ");
  Serial.println(kd, 4);
  return true;
}

bool handleXYPidQueryCommand(const String &cmd) {
  if (cmd != "XY PID?") {
    return false;
  }
  Serial.print("OK XY PID ");
  Serial.print(xyPid.kp, 4);
  Serial.print(" ");
  Serial.print(xyPid.ki, 4);
  Serial.print(" ");
  Serial.print(xyPid.kd, 4);
  Serial.print(" LIMIT ");
  Serial.println(xyFollowLimitCounts, 2);
  return true;
}

bool handleSetXYFollowLimitCommand(const String &cmd) {
  float limitCounts = 0.0f;
  int parsed = sscanf(cmd.c_str(), "SET XY FOLLOW LIMIT %f", &limitCounts);
  if (parsed != 1) {
    return false;
  }
  if (limitCounts <= 0.0f) {
    Serial.println("ERR FOLLOW LIMIT RANGE");
    return true;
  }
  xyFollowLimitCounts = limitCounts;
  Serial.print("OK XY FOLLOW LIMIT ");
  Serial.println(limitCounts, 2);
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
  float yTrackLengthCm = DEFAULT_Y_WORKSPACE_CM;
  char speedBuffer[16] = "safe";
  int trapezoidFlag = 1;
  int accelerationRpmPerSecond = 300;
  int nextStepsPerRotation = DEFAULT_STEPS_PER_REVOLUTION;
  int maxProbeRotations = DEFAULT_MAX_PROBE_ROTATIONS;
  // Appended last so a command from an older host still parses, falling back to
  // the defaults.
  float xCalibrationYRotations = DEFAULT_X_CALIBRATION_Y_ROTATIONS;
  float limitBufferCm = DEFAULT_XY_LIMIT_BUFFER_CM;
  int parsed = sscanf(
    cmd.c_str(),
    "CALIBRATE XY %f %f %15s %d %d %d %d %f %f",
    &xTrackLengthCm,
    &yTrackLengthCm,
    speedBuffer,
    &trapezoidFlag,
    &accelerationRpmPerSecond,
    &nextStepsPerRotation,
    &maxProbeRotations,
    &xCalibrationYRotations,
    &limitBufferCm
  );
  if (parsed < 2) {
    return false;
  }

  String speedToken = parsed >= 3 ? String(speedBuffer) : String("safe");
  speedToken.toLowerCase();
  int rpm = isDigit(speedToken.charAt(0)) ? speedToken.toInt() : rpmForCalibrationProfile(speedToken);
  calibrateXY(
    xTrackLengthCm,
    yTrackLengthCm,
    rpm,
    parsed >= 4 ? trapezoidFlag != 0 : true,
    parsed >= 5 ? accelerationRpmPerSecond : 300,
    parsed >= 6 ? nextStepsPerRotation : DEFAULT_STEPS_PER_REVOLUTION,
    parsed >= 7 ? maxProbeRotations : DEFAULT_MAX_PROBE_ROTATIONS,
    parsed >= 8 ? xCalibrationYRotations : DEFAULT_X_CALIBRATION_Y_ROTATIONS,
    parsed >= 9 ? limitBufferCm : DEFAULT_XY_LIMIT_BUFFER_CM
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

  if (cmd == "ID?" || cmd == "ID") {
    printControllerIdentity();
  }
  else if (cmd == "PING") {
    Serial.println("PONG");
  }
  else if (cmd == "STOP") {
    Serial.println("OK STOP");
  }
  else if (handleTestMotorCommand(cmd)) {
  }
  else if (handleSetXYEnableCommand(cmd)) {
  }
  else if (handleSetXYPinsCommand(cmd)) {
  }
  else if (handleSetEncoderPinsCommand(cmd)) {
  }
  else if (handleEncoderQueryCommand(cmd)) {
  }
  else if (handleSetXYPidCommand(cmd)) {
  }
  else if (handleXYPidQueryCommand(cmd)) {
  }
  else if (handleSetXYFollowLimitCommand(cmd)) {
  }
  else if (handleSetXYLimitsCommand(cmd)) {
  }
  else if (handleMoveXYZCommand(cmd)) {
  }
  else if (handleMoveXYCommand(cmd)) {
  }
  else if (handleGotoXYCommand(cmd)) {
  }
  else if (handleCircleXYCommand(cmd)) {
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
