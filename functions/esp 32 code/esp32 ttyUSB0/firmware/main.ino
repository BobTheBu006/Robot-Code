#include <Arduino.h>

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

void moveStepperBySteps(int index, long signedSteps, int rpm) {
  long totalSteps = labs(signedSteps);
  if (totalSteps == 0) {
    return;
  }

  bool forward = signedSteps >= 0;
  digitalWrite(dirPins[index], forward ? HIGH : LOW);
  delayMicroseconds(20);

  unsigned long intervalMicros = stepIntervalMicrosForRPM(rpm);
  unsigned long lowTimeMicros = intervalMicros > (unsigned long)StepPulseWidthMicros
    ? intervalMicros - (unsigned long)StepPulseWidthMicros
    : (unsigned long)StepPulseWidthMicros;

  for (long step = 0; step < totalSteps; step++) {
    digitalWrite(stepPins[index], HIGH);
    delayMicroseconds(StepPulseWidthMicros);
    digitalWrite(stepPins[index], LOW);
    delayMicroseconds(lowTimeMicros);
  }
}

void dispenseSteps(long s0, long s1, long s2, long s3, long s4, long s5, long s6) {
  long steps[NUM_SYRINGES] = {s0, s1, s2, s3, s4, s5, s6};

  Serial.print("ACTIVE INTAKE RPM ");
  Serial.println(IntakeRPM);
  Serial.print("ACTIVE OUTTAKE RPM ");
  Serial.println(OuttakeRPM);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      long signedSteps = dirSign[i] * steps[i];
      moveStepperBySteps(i, signedSteps, IntakeRPM);

      if (SettleDelayMs > 0) {
        delay(SettleDelayMs);
      }

      moveStepperBySteps(i, -signedSteps, OuttakeRPM);

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

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    pinMode(stepPins[i], OUTPUT);
    pinMode(dirPins[i], OUTPUT);
    digitalWrite(stepPins[i], LOW);
    digitalWrite(dirPins[i], LOW);
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
    else if (handleSpeedCommand(cmd)) {
      // speed command handled above
    }
    else if (cmd == "PING") {
      Serial.println("PONG");
    }
    else {
      Serial.println("ERR UNKNOWN CMD");
    }
  }
}
