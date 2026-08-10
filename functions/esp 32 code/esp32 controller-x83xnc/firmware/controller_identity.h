// Controller identity: who this board is, and exactly which firmware build is
// on it.
//
// The backend writes generated_identity.h into the sketch at flash time. A run
// then asks each board "ID?" and compares the answer against what the Hardware
// Map expects, so it can flash only the boards that are actually wrong instead
// of reflashing every controller before every workflow. It doubles as the
// liveness check: a board that answers is connected and running.
//
// The __has_include guard keeps this sketch compilable on its own, straight
// from the Arduino IDE, with no backend involved. Such a build reports an empty
// identity, which reads as "cannot be verified" and gets flashed once.

#pragma once

#include <Arduino.h>

#if defined(__has_include)
#  if __has_include("generated_identity.h")
#    include "generated_identity.h"
#  endif
#endif

#ifndef ROBOT_CONTROLLER_ID
#define ROBOT_CONTROLLER_ID ""
#endif

#ifndef ROBOT_CONTROLLER_NAME
#define ROBOT_CONTROLLER_NAME ""
#endif

#ifndef ROBOT_FIRMWARE_FINGERPRINT
#define ROBOT_FIRMWARE_FINGERPRINT ""
#endif

#ifndef ROBOT_IDENTITY_PROTOCOL
#define ROBOT_IDENTITY_PROTOCOL 1
#endif

#ifndef ROBOT_ROUTINE_COUNT
#define ROBOT_ROUTINE_COUNT 0
static const char* ROBOT_ROUTINES[] = {""};
#endif

// Answers ID? as a single JSON line. Kept to one line because the backend
// reads exactly one reply line per request.
inline void printControllerIdentity() {
  Serial.print("{\"controller_id\":\"");
  Serial.print(ROBOT_CONTROLLER_ID);
  Serial.print("\",\"name\":\"");
  Serial.print(ROBOT_CONTROLLER_NAME);
  Serial.print("\",\"fingerprint\":\"");
  Serial.print(ROBOT_FIRMWARE_FINGERPRINT);
  Serial.print("\",\"protocol\":");
  Serial.print(ROBOT_IDENTITY_PROTOCOL);
  Serial.print(",\"routines\":[");
  for (int i = 0; i < ROBOT_ROUTINE_COUNT; i++) {
    if (i > 0) {
      Serial.print(",");
    }
    Serial.print("\"");
    Serial.print(ROBOT_ROUTINES[i]);
    Serial.print("\"");
  }
  Serial.println("]}");
}
