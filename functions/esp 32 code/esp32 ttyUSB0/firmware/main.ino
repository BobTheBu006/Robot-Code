#include <Arduino.h>
#include "A4988.h"

const int NUM_SYRINGES = 7;
const int spr = 200;
int RPM = 100;
int Microsteps = 1;

int stepPins[NUM_SYRINGES] = {33, 25, 26, 27, 14, 12, 13};
int dirPins[NUM_SYRINGES]  = {32, 4, 5, 18, 19, 21, 22};

int dirSign[NUM_SYRINGES] = {-1, -1, -1, -1, -1, -1, -1};

A4988 stepper0(spr, dirPins[0], stepPins[0]);
A4988 stepper1(spr, dirPins[1], stepPins[1]);
A4988 stepper2(spr, dirPins[2], stepPins[2]);
A4988 stepper3(spr, dirPins[3], stepPins[3]);
A4988 stepper4(spr, dirPins[4], stepPins[4]);
A4988 stepper5(spr, dirPins[5], stepPins[5]);
A4988 stepper6(spr, dirPins[6], stepPins[6]);

A4988* steppers[NUM_SYRINGES] = {
  &stepper0, &stepper1, &stepper2, &stepper3,
  &stepper4, &stepper5, &stepper6
};

void applyRPM(int nextRPM) {
  if (nextRPM <= 0) {
    return;
  }

  RPM = nextRPM;
  for (int i = 0; i < NUM_SYRINGES; i++) {
    steppers[i]->begin(RPM, Microsteps);
  }

  Serial.print("OK SPEED ");
  Serial.println(RPM);
}

void dispenseSteps(long s0, long s1, long s2, long s3, long s4, long s5, long s6) {
  long steps[NUM_SYRINGES] = {s0, s1, s2, s3, s4, s5, s6};

  for (int i = 0; i < NUM_SYRINGES; i++) {
    if (steps[i] != 0) {
      steppers[i]->move(dirSign[i] * steps[i]);
      delay(100);
      steppers[i]->move(-dirSign[i] * steps[i]);

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

  return false;
}

void setup() {
  Serial.begin(115200);

  for (int i = 0; i < NUM_SYRINGES; i++) {
    pinMode(stepPins[i], OUTPUT);
    pinMode(dirPins[i], OUTPUT);
    steppers[i]->begin(RPM, Microsteps);
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
