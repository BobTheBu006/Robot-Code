#include <Arduino.h>
#include "controller_identity.h"

const int NUM_SYRINGES = 7;
const int spr = 200;
int RPM = 100;
int IntakeRPM = 100;
int OuttakeRPM = 100;
int Microsteps = 1;
int StepPulseWidthMicros = 8;
int SettleDelayMs = 20;

int stepPins[NUM_SYRINGES] = {33, 25, 26, 27, 14, 12, 13};
int dirPins[NUM_SYRINGES]  = {32, 4, 5, 18, 19, 21, 22};

int dirSign[NUM_SYRINGES] = {-1, -1, -1, -1, -1, -1, -1};

int headIndexFromName(char headName) {
  char normalized = toupper(headName);
  if (normalized < 'A' || normalized > 'G') {
    return -1;
  }

  return normalized - 'A';
}

void applyHeadPins(int index, int stepPin, int dirPin) {
  if (index < 0 || index >= NUM_SYRINGES) {
    return;
  }

  stepPins[index] = stepPin;
  dirPins[index] = dirPin;

  pinMode(stepPins[index], OUTPUT);
  pinMode(dirPins[index], OUTPUT);
  digitalWrite(stepPins[index], LOW);
  digitalWrite(dirPins[index], LOW);
}

void applyRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  RPM = nextRPM;
  IntakeRPM = nextRPM;
  OuttakeRPM = nextRPM;

  Serial.print("OK SPEED ");
  Serial.println(RPM);
}

void applyIntakeRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  IntakeRPM = nextRPM;
  Serial.print("OK INTAKE SPEED ");
  Serial.println(IntakeRPM);
}

void applyOuttakeRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  OuttakeRPM = nextRPM;
  Serial.print("OK OUTTAKE SPEED ");
  Serial.println(OuttakeRPM);
}

unsigned long stepIntervalMicrosForRPM(int rpm) {
  float stepsPerSecond = (rpm * spr * Microsteps) / 60.0f;
  if (stepsPerSecond <= 0.0f) {
    stepsPerSecond = 1.0f;
  }

  unsigned long interval = (unsigned long)(1000000.0f / stepsPerSecond);
  unsigned long minimumInterval = (unsigned long)(StepPulseWidthMicros * 2);
  if (interval < minimumInterval) {
    return minimumInterval;
  }

  return interval;
}

void moveSteppersBySteps(const long signedSteps[NUM_SYRINGES], int rpm) {
  unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
  unsigned long lowTimeMicros = intervalMicros > (unsigned long)StepPulseWidthMicros
    ? intervalMicros - (unsigned long)StepPulseWidthMicros
    : (unsigned long)StepPulseWidthMicros;

  long maxSteps = 0;
  for (int i = 0; i < NUM_SYRINGES; i++) {
    long totalSteps = labs(signedSteps[i]);
    if (totalSteps > 0) {
      bool forward = signedSteps[i] >= 0;
      digitalWrite(dirPins[i], forward ? HIGH : LOW);
      if (totalSteps > maxSteps) {
        maxSteps = totalSteps;
      }
    }
  }

  if (maxSteps == 0) {
    return;
  }

  delayMicroseconds(20);

  for (long step = 0; step < maxSteps; step++) {
    for (int i = 0; i < NUM_SYRINGES; i++) {
      if (labs(signedSteps[i]) > step) {
        digitalWrite(stepPins[i], HIGH);
      }
    }

    delayMicroseconds(StepPulseWidthMicros);

    for (int i = 0; i < NUM_SYRINGES; i++) {
      if (labs(signedSteps[i]) > step) {
        digitalWrite(stepPins[i], LOW);
      }
    }

    delayMicroseconds(lowTimeMicros);
  }
}

void dispenseSteps(long s0, long s1, long s2, long s3, long s4, long s5, long s6) {
  long steps[NUM_SYRINGES] = {s0, s1, s2, s3, s4, s5, s6};
  long forwardSteps[NUM_SYRINGES] = {0, 0, 0, 0, 0, 0, 0};
  long returnSteps[NUM_SYRINGES] = {0, 0, 0, 0, 0, 0, 0};

  Serial.print("ACTIVE INTAKE RPM ");
  Serial.println(IntakeRPM);
  Serial.print("ACTIVE OUTTAKE RPM ");
  Serial.println(OuttakeRPM);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      forwardSteps[i] = dirSign[i] * steps[i];
      returnSteps[i] = -forwardSteps[i];
    }
  }

  moveSteppersBySteps(forwardSteps, IntakeRPM);

  if (SettleDelayMs > 0) {
    delay(SettleDelayMs);
  }

  moveSteppersBySteps(returnSteps, OuttakeRPM);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      Serial.print("SYRINGE ");
      Serial.print(i);
      Serial.println(" DONE");
    }
  }

  Serial.println("OK DISPENSE");
}

bool handleSpeedCommand(const String& cmd) {
  long nextRPM = 0;

  if (cmd.startsWith("SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("INTAKE_SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "INTAKE_SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("INTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "INTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_INTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_INTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET INTAKE SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET INTAKE SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyIntakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("OUTTAKE_SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "OUTTAKE_SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("OUTTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "OUTTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET_OUTTAKE_SPEED,")) {
    int parsed = sscanf(cmd.c_str(), "SET_OUTTAKE_SPEED,%ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  if (cmd.startsWith("SET OUTTAKE SPEED ")) {
    int parsed = sscanf(cmd.c_str(), "SET OUTTAKE SPEED %ld", &nextRPM);
    if (parsed == 1) {
      applyOuttakeRPM((int)nextRPM);
      return true;
    }
  }

  return false;
}

bool handlePinCommand(const String& cmd) {
  char headName = '\0';
  long stepPin = 0;
  long dirPin = 0;

  if (cmd.startsWith("SET HEAD PINS ")) {
    int parsed = sscanf(cmd.c_str(), "SET HEAD PINS %c %ld %ld", &headName, &stepPin, &dirPin);
    if (parsed == 3) {
      int headIndex = headIndexFromName(headName);
      if (headIndex >= 0) {
        applyHeadPins(headIndex, (int)stepPin, (int)dirPin);
        Serial.print("OK HEAD ");
        Serial.print((char)toupper(headName));
        Serial.print(" PINS ");
        Serial.print(stepPin);
        Serial.print(" ");
        Serial.println(dirPin);
      } else {
        Serial.println("ERR BAD HEAD");
      }
      return true;
    }
  }

  if (cmd.startsWith("HEAD PINS ")) {
    int parsed = sscanf(cmd.c_str(), "HEAD PINS %c %ld %ld", &headName, &stepPin, &dirPin);
    if (parsed == 3) {
      int headIndex = headIndexFromName(headName);
      if (headIndex >= 0) {
        applyHeadPins(headIndex, (int)stepPin, (int)dirPin);
        Serial.print("OK HEAD ");
        Serial.print((char)toupper(headName));
        Serial.print(" PINS ");
        Serial.print(stepPin);
        Serial.print(" ");
        Serial.println(dirPin);
      } else {
        Serial.println("ERR BAD HEAD");
      }
      return true;
    }
  }

  return false;
}

// One-directional signed move in dispense coordinates: positive pushes the
// plunger (same physical direction as the first stroke of DISPENSE), negative
// draws. Unlike DISPENSE there is no automatic return stroke - this is the
// primitive that homing against the bottom stop and priming cycles are built
// from on the backend side.
void moveSyringesOneWay(const long dispenseDirectionSteps[NUM_SYRINGES], int rpm) {
  long signedSteps[NUM_SYRINGES];
  for (int i = 0; i < NUM_SYRINGES; i++) {
    signedSteps[i] = dispenseDirectionSteps[i] * dirSign[i];
  }

  moveSteppersBySteps(signedSteps, rpm);
  Serial.println("OK MOVE");
}

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    applyHeadPins(i, stepPins[i], dirPins[i]);
  }

  Serial.println("READY");
}

void loop() {
  if (Serial.available()) {
    String cmd = Serial.readStringUntil('\n');
    cmd.trim();

    if (cmd.startsWith("DISPENSE ")) {
      long s[NUM_SYRINGES] = {0, 0, 0, 0, 0, 0, 0};

      int parsed = sscanf(
        cmd.c_str(),
        "DISPENSE %ld %ld %ld %ld %ld %ld %ld",
        &s[0], &s[1], &s[2], &s[3], &s[4], &s[5], &s[6]
      );

      if (parsed == 7) {
        dispenseSteps(s[0], s[1], s[2], s[3], s[4], s[5], s[6]);
      } else {
        Serial.println("ERR BAD DISPENSE CMD");
      }
    }
    else if (cmd.startsWith("MOVE ")) {
      long s[NUM_SYRINGES] = {0, 0, 0, 0, 0, 0, 0};
      long rpm = 0;

      int parsed = sscanf(
        cmd.c_str(),
        "MOVE %ld %ld %ld %ld %ld %ld %ld %ld",
        &s[0], &s[1], &s[2], &s[3], &s[4], &s[5], &s[6], &rpm
      );

      if (parsed == 8 && rpm > 0) {
        moveSyringesOneWay(s, (int)rpm);
      } else {
        Serial.println("ERR BAD MOVE CMD");
      }
    }
    else if (handlePinCommand(cmd)) {
      // pin command handled above
    }
    else if (handleSpeedCommand(cmd)) {
      // speed command handled above
    }
    else if (cmd == "ID?" || cmd == "ID") {
      printControllerIdentity();
    }
    else if (cmd == "PING") {
      Serial.println("PONG");
    }
    else {
      Serial.println("ERR UNKNOWN CMD");
    }
  }
}
