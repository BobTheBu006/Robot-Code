#include <Arduino.h>
#include <FS.h>
#include <LittleFS.h>
#include <math.h>

const int NUM_CHANNELS = 6;

const int diode_channels[NUM_CHANNELS] = {32, 34, 36, 33, 35, 39};
const int led_channels[NUM_CHANNELS]   = {23, 13, 14, 27, 26, 25};

const uint32_t PWM_FREQ = 20000;
const uint8_t PWM_BITS = 10;
const uint16_t PWM_MAX = (1 << PWM_BITS) - 1;

const int ADC_BITS = 12;
const int ADC_SAMPLES = 32;
const int CALIBRATION_REPEATS = 5;
const int TRACKING_REPEATS = 8;
const int MAX_MEASUREMENT_REPEATS = TRACKING_REPEATS > CALIBRATION_REPEATS ? TRACKING_REPEATS : CALIBRATION_REPEATS;
const int BETWEEN_ADC_US = 200;

const uint16_t CALIBRATION_DUTY_STEP = 8;
const float ADC_LIMIT = 2420.0f;
const float TRACKING_FRACTION_OF_MAX = 0.85f;
const float MIN_TRACKING_FRACTION_OF_MAX = 0.70f;
const float TRACKING_FRACTION_STEP = 0.05f;
const float PWM_NOISE_MIN_DROP_ADC = 40.0f;
const float PWM_NOISE_MIN_DROP_FRACTION = 0.02f;
const uint16_t PWM_NOISE_DUTY_GUARD = CALIBRATION_DUTY_STEP * 2;

const int MIN_LINEAR_POINTS = 6;
const float MIN_LINEAR_R_SQUARED = 0.995f;
const float MAX_LINEAR_RESIDUAL_FRACTION = 0.06f;
const float MIN_EDGE_SLOPE_RATIO = 0.45f;

const int LED_SETTLE_MS = 12;
const int BETWEEN_REPEAT_MS = 4;
const int BETWEEN_LED_MS = 8;
const unsigned long TRACKING_INTERVAL_MS = 5000;

const char *CALIBRATION_SWEEP_FILE = "/calibration_sweep.csv";
const char *CALIBRATION_SUMMARY_FILE = "/calibration_summary.csv";
const char *TRACKING_FILE = "/tracking.csv";
const char *TRACKING_REPEATS_FILE = "/tracking_repeats.csv";

const int MAX_SWEEP_POINTS = (PWM_MAX / CALIBRATION_DUTY_STEP) + 3;

struct LinearRangeFit {
  int startIndex;
  int endIndex;
  float slope;
  float intercept;
  float rSquared;
  float residualFraction;
  bool valid;
  bool fallbackUsed;
};

struct CalibrationResult {
  uint16_t peakDuty;
  float peakAdc;
  uint16_t linearStartDuty;
  uint16_t linearEndDuty;
  float linearStartAdc;
  float linearEndAdc;
  float fitSlope;
  float fitIntercept;
  float fitRSquared;
  float targetAdc;
  uint16_t trackingDuty;
  float trackingReferenceAdc;
  int sweepPoints;
  bool limitReached;
  bool fallbackFit;
};

CalibrationResult calibration[NUM_CHANNELS];

File calibrationSweepFile;
File calibrationSummaryFile;
File trackingFile;
File trackingRepeatsFile;

void allLedsOff();
void printChannels(Print &out, const float values[NUM_CHANNELS], int decimals);
void printRawChannels(Print &out, const uint16_t values[NUM_CHANNELS]);
void printStatusPrefix();
void logStatus(const char *message);
void logCalibrationStart(int activeLed);
void logCalibrationDone(int activeLed, const CalibrationResult &result);
void logTrackingStarted();
void logTrackingCycle(unsigned long cycleIndex);
void writeCalibrationSweepHeader(Print &out);
void writeCalibrationSummaryHeader(Print &out);
void writeTrackingHeader(Print &out);
void writeTrackingRepeatsHeader(Print &out);
void mirrorCsvHeader(const char *name, void (*writer)(Print &));
void writeCalibrationSweepRow(Print &out, int activeLed, uint16_t duty, const float means[NUM_CHANNELS]);
void writeCalibrationSummaryRow(Print &out, int activeLed, const CalibrationResult &result);
void writeTrackingRepeatsRow(Print &out, unsigned long timestampMs, unsigned long cycleIndex, int activeLed, uint16_t duty, int repeatIndex, const uint16_t rawValues[NUM_CHANNELS]);
void writeTrackingRow(Print &out, unsigned long timestampMs, unsigned long cycleIndex, int activeLed, const float means[NUM_CHANNELS]);
void mirrorCalibrationSweepRow(int activeLed, uint16_t duty, const float means[NUM_CHANNELS]);
void mirrorCalibrationSummaryRow(int activeLed, const CalibrationResult &result);
void mirrorTrackingRepeatsRow(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, uint16_t duty, int repeatIndex, const uint16_t rawValues[NUM_CHANNELS]);
void mirrorTrackingRow(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, const float means[NUM_CHANNELS]);

void haltForever() {
  allLedsOff();
  while (true) {
    delay(1000);
  }
}

void fatalError(const char *message) {
  Serial.println(message);
  haltForever();
}

void allLedsOff() {
  for (int i = 0; i < NUM_CHANNELS; i++) {
    ledcWrite(led_channels[i], 0);
  }
}

int readAdcAverage(int pin, int samples) {
  long sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(pin);
    delayMicroseconds(BETWEEN_ADC_US);
  }
  return sum / samples;
}

void measureLedToAllDiodes(int activeLed, uint16_t duty, int repeats, float means[NUM_CHANNELS], uint16_t (*rawSamples)[NUM_CHANNELS] = nullptr) {
  uint32_t sums[NUM_CHANNELS] = {0};

  allLedsOff();
  delay(BETWEEN_LED_MS);

  ledcWrite(led_channels[activeLed], duty);
  delay(LED_SETTLE_MS);

  for (int rep = 0; rep < repeats; rep++) {
    for (int ch = 0; ch < NUM_CHANNELS; ch++) {
      uint16_t reading = readAdcAverage(diode_channels[ch], ADC_SAMPLES);
      sums[ch] += reading;

      if (rawSamples != nullptr) {
        rawSamples[rep][ch] = reading;
      }
    }

    if (rep < repeats - 1) {
      delay(BETWEEN_REPEAT_MS);
    }
  }

  ledcWrite(led_channels[activeLed], 0);
  delay(BETWEEN_LED_MS);

  for (int ch = 0; ch < NUM_CHANNELS; ch++) {
    means[ch] = sums[ch] / static_cast<float>(repeats);
  }
}

void printChannels(Print &out, const float values[NUM_CHANNELS], int decimals) {
  for (int ch = 0; ch < NUM_CHANNELS; ch++) {
    out.print(",");
    out.print(values[ch], decimals);
  }
}

void printRawChannels(Print &out, const uint16_t values[NUM_CHANNELS]) {
  for (int ch = 0; ch < NUM_CHANNELS; ch++) {
    out.print(",");
    out.print(values[ch]);
  }
}

void printStatusPrefix() {
  Serial.print("STATUS: ");
}

void logStatus(const char *message) {
  printStatusPrefix();
  Serial.println(message);
}

void logCalibrationStart(int activeLed) {
  printStatusPrefix();
  Serial.print("calibration started on pair ");
  Serial.print(activeLed + 1);
  Serial.print("/");
  Serial.println(NUM_CHANNELS);
}

void logCalibrationDone(int activeLed, const CalibrationResult &result) {
  printStatusPrefix();
  Serial.print("calibration done on pair ");
  Serial.print(activeLed + 1);
  Serial.print("/");
  Serial.print(NUM_CHANNELS);
  Serial.print(", tracking duty=");
  Serial.print(result.trackingDuty);
  Serial.print(", reference adc=");
  Serial.println(result.trackingReferenceAdc, 2);
}

void logTrackingStarted() {
  logStatus("calibration complete, tracking started");
}

void logTrackingCycle(unsigned long cycleIndex) {
  printStatusPrefix();
  Serial.print("tracking cycle ");
  Serial.println(cycleIndex);
}

void writeCalibrationSweepHeader(Print &out) {
  out.println("led_index,duty,main_adc,ch0,ch1,ch2,ch3,ch4,ch5");
}

void writeCalibrationSummaryHeader(Print &out) {
  out.println("led_index,paired_diode,peak_duty,peak_adc,linear_start_duty,linear_end_duty,linear_start_adc,linear_end_adc,fit_slope,fit_intercept,fit_r_squared,target_adc,tracking_duty,tracking_reference_adc,limit_reached,fallback_fit,sweep_points");
}

void writeTrackingHeader(Print &out) {
  out.println("timestamp_ms,cycle,led_index,duty,reference_adc,main_adc,normalized,delta_od,ch0,ch1,ch2,ch3,ch4,ch5");
}

void writeTrackingRepeatsHeader(Print &out) {
  out.println("timestamp_ms,cycle,led_index,duty,repeat,ch0,ch1,ch2,ch3,ch4,ch5");
}

void mirrorCsvHeader(const char *name, void (*writer)(Print &)) {
  Serial.print("CSV,");
  Serial.print(name);
  Serial.print(",");
  writer(Serial);
}

void writeCalibrationSweepRow(Print &out, int activeLed, uint16_t duty, const float means[NUM_CHANNELS]) {
  out.print(activeLed);
  out.print(",");
  out.print(duty);
  out.print(",");
  out.print(means[activeLed], 2);
  printChannels(out, means, 2);
  out.println();
}

void writeCalibrationSummaryRow(Print &out, int activeLed, const CalibrationResult &result) {
  out.print(activeLed);
  out.print(",");
  out.print(activeLed);
  out.print(",");
  out.print(result.peakDuty);
  out.print(",");
  out.print(result.peakAdc, 2);
  out.print(",");
  out.print(result.linearStartDuty);
  out.print(",");
  out.print(result.linearEndDuty);
  out.print(",");
  out.print(result.linearStartAdc, 2);
  out.print(",");
  out.print(result.linearEndAdc, 2);
  out.print(",");
  out.print(result.fitSlope, 6);
  out.print(",");
  out.print(result.fitIntercept, 6);
  out.print(",");
  out.print(result.fitRSquared, 6);
  out.print(",");
  out.print(result.targetAdc, 2);
  out.print(",");
  out.print(result.trackingDuty);
  out.print(",");
  out.print(result.trackingReferenceAdc, 2);
  out.print(",");
  out.print(result.limitReached ? 1 : 0);
  out.print(",");
  out.print(result.fallbackFit ? 1 : 0);
  out.print(",");
  out.print(result.sweepPoints);
  out.println();
}

void writeTrackingRepeatsRow(Print &out, unsigned long timestampMs, unsigned long cycleIndex, int activeLed, uint16_t duty, int repeatIndex, const uint16_t rawValues[NUM_CHANNELS]) {
  out.print(timestampMs);
  out.print(",");
  out.print(cycleIndex);
  out.print(",");
  out.print(activeLed);
  out.print(",");
  out.print(duty);
  out.print(",");
  out.print(repeatIndex);
  printRawChannels(out, rawValues);
  out.println();
}

void writeTrackingRow(Print &out, unsigned long timestampMs, unsigned long cycleIndex, int activeLed, const float means[NUM_CHANNELS]) {
  float reference = calibration[activeLed].trackingReferenceAdc;
  float mainAdc = means[activeLed];
  float normalized = reference > 0.0f ? mainAdc / reference : 0.0f;
  float deltaOd = normalized > 0.0f ? -log10f(normalized) : NAN;

  out.print(timestampMs);
  out.print(",");
  out.print(cycleIndex);
  out.print(",");
  out.print(activeLed);
  out.print(",");
  out.print(calibration[activeLed].trackingDuty);
  out.print(",");
  out.print(reference, 2);
  out.print(",");
  out.print(mainAdc, 2);
  out.print(",");
  out.print(normalized, 6);
  out.print(",");
  out.print(deltaOd, 6);
  printChannels(out, means, 2);
  out.println();
}

void mirrorCalibrationSweepRow(int activeLed, uint16_t duty, const float means[NUM_CHANNELS]) {
  Serial.print("CSV,calibration_sweep.csv,");
  writeCalibrationSweepRow(Serial, activeLed, duty, means);
}

void mirrorCalibrationSummaryRow(int activeLed, const CalibrationResult &result) {
  Serial.print("CSV,calibration_summary.csv,");
  writeCalibrationSummaryRow(Serial, activeLed, result);
}

void mirrorTrackingRepeatsRow(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, uint16_t duty, int repeatIndex, const uint16_t rawValues[NUM_CHANNELS]) {
  Serial.print("CSV,tracking_repeats.csv,");
  writeTrackingRepeatsRow(Serial, timestampMs, cycleIndex, activeLed, duty, repeatIndex, rawValues);
}

void mirrorTrackingRow(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, const float means[NUM_CHANNELS]) {
  Serial.print("CSV,tracking.csv,");
  writeTrackingRow(Serial, timestampMs, cycleIndex, activeLed, means);
}

void prepareLogFiles() {
  LittleFS.remove(CALIBRATION_SWEEP_FILE);
  LittleFS.remove(CALIBRATION_SUMMARY_FILE);
  LittleFS.remove(TRACKING_FILE);
  LittleFS.remove(TRACKING_REPEATS_FILE);

  calibrationSweepFile = LittleFS.open(CALIBRATION_SWEEP_FILE, FILE_WRITE);
  calibrationSummaryFile = LittleFS.open(CALIBRATION_SUMMARY_FILE, FILE_WRITE);
  trackingFile = LittleFS.open(TRACKING_FILE, FILE_WRITE);
  trackingRepeatsFile = LittleFS.open(TRACKING_REPEATS_FILE, FILE_WRITE);

  if (!calibrationSweepFile || !calibrationSummaryFile || !trackingFile || !trackingRepeatsFile) {
    fatalError("Failed to open log files in LittleFS.");
  }

  writeCalibrationSweepHeader(calibrationSweepFile);
  writeCalibrationSummaryHeader(calibrationSummaryFile);
  writeTrackingHeader(trackingFile);
  writeTrackingRepeatsHeader(trackingRepeatsFile);

  mirrorCsvHeader("calibration_sweep.csv", writeCalibrationSweepHeader);
  mirrorCsvHeader("calibration_summary.csv", writeCalibrationSummaryHeader);
  mirrorCsvHeader("tracking.csv", writeTrackingHeader);
  mirrorCsvHeader("tracking_repeats.csv", writeTrackingRepeatsHeader);

  calibrationSweepFile.flush();
  calibrationSummaryFile.flush();
  trackingFile.flush();
  trackingRepeatsFile.flush();
}

bool isBetterLinearFit(const LinearRangeFit &candidate, const LinearRangeFit &current, const uint16_t sweepDuty[MAX_SWEEP_POINTS]) {
  if (!current.valid) {
    return true;
  }

  int candidatePoints = candidate.endIndex - candidate.startIndex + 1;
  int currentPoints = current.endIndex - current.startIndex + 1;
  if (candidatePoints != currentPoints) {
    return candidatePoints > currentPoints;
  }

  uint16_t candidateSpan = sweepDuty[candidate.endIndex] - sweepDuty[candidate.startIndex];
  uint16_t currentSpan = sweepDuty[current.endIndex] - sweepDuty[current.startIndex];
  if (candidateSpan != currentSpan) {
    return candidateSpan > currentSpan;
  }

  if (candidate.rSquared != current.rSquared) {
    return candidate.rSquared > current.rSquared;
  }

  return candidate.residualFraction < current.residualFraction;
}

LinearRangeFit findLinearRange(const uint16_t sweepDuty[MAX_SWEEP_POINTS], const float sweepMainAdc[MAX_SWEEP_POINTS], int points) {
  float prefixX[MAX_SWEEP_POINTS + 1] = {0.0f};
  float prefixY[MAX_SWEEP_POINTS + 1] = {0.0f};
  float prefixXX[MAX_SWEEP_POINTS + 1] = {0.0f};
  float prefixYY[MAX_SWEEP_POINTS + 1] = {0.0f};
  float prefixXY[MAX_SWEEP_POINTS + 1] = {0.0f};

  for (int i = 0; i < points; i++) {
    float x = sweepDuty[i];
    float y = sweepMainAdc[i];
    prefixX[i + 1] = prefixX[i] + x;
    prefixY[i + 1] = prefixY[i] + y;
    prefixXX[i + 1] = prefixXX[i] + (x * x);
    prefixYY[i + 1] = prefixYY[i] + (y * y);
    prefixXY[i + 1] = prefixXY[i] + (x * y);
  }

  LinearRangeFit bestValid = {};
  LinearRangeFit bestFallback = {};

  for (int start = 0; start <= points - MIN_LINEAR_POINTS; start++) {
    for (int end = start + MIN_LINEAR_POINTS - 1; end < points; end++) {
      int count = end - start + 1;
      float sumX = prefixX[end + 1] - prefixX[start];
      float sumY = prefixY[end + 1] - prefixY[start];
      float sumXX = prefixXX[end + 1] - prefixXX[start];
      float sumYY = prefixYY[end + 1] - prefixYY[start];
      float sumXY = prefixXY[end + 1] - prefixXY[start];

      float denominator = (count * sumXX) - (sumX * sumX);
      if (fabsf(denominator) < 1e-6f) {
        continue;
      }

      float slope = ((count * sumXY) - (sumX * sumY)) / denominator;
      if (slope <= 0.0f) {
        continue;
      }

      float intercept = (sumY - (slope * sumX)) / count;
      float sse = sumYY + (slope * slope * sumXX) + (count * intercept * intercept)
                - (2.0f * slope * sumXY) - (2.0f * intercept * sumY)
                + (2.0f * slope * intercept * sumX);
      float sst = sumYY - ((sumY * sumY) / count);
      float rSquared = sst <= 1e-6f ? 1.0f : 1.0f - (fmaxf(sse, 0.0f) / sst);

      float minAdc = sweepMainAdc[start];
      float maxAdc = sweepMainAdc[start];
      float maxResidual = 0.0f;
      for (int i = start; i <= end; i++) {
        float adc = sweepMainAdc[i];
        if (adc < minAdc) {
          minAdc = adc;
        }
        if (adc > maxAdc) {
          maxAdc = adc;
        }

        float fitAdc = (slope * sweepDuty[i]) + intercept;
        float residual = fabsf(adc - fitAdc);
        if (residual > maxResidual) {
          maxResidual = residual;
        }
      }

      float adcSpan = maxAdc - minAdc;
      if (adcSpan <= 1.0f) {
        continue;
      }

      float residualFraction = maxResidual / adcSpan;
      float firstSlope = (sweepMainAdc[start + 1] - sweepMainAdc[start]) / (sweepDuty[start + 1] - sweepDuty[start]);
      float lastSlope = (sweepMainAdc[end] - sweepMainAdc[end - 1]) / (sweepDuty[end] - sweepDuty[end - 1]);

      LinearRangeFit candidate = {};
      candidate.startIndex = start;
      candidate.endIndex = end;
      candidate.slope = slope;
      candidate.intercept = intercept;
      candidate.rSquared = rSquared;
      candidate.residualFraction = residualFraction;
      candidate.valid = true;

      if (isBetterLinearFit(candidate, bestFallback, sweepDuty)) {
        bestFallback = candidate;
      }

      bool matchesLinearShape = rSquared >= MIN_LINEAR_R_SQUARED
                             && residualFraction <= MAX_LINEAR_RESIDUAL_FRACTION
                             && firstSlope >= (slope * MIN_EDGE_SLOPE_RATIO)
                             && lastSlope >= (slope * MIN_EDGE_SLOPE_RATIO);
      if (matchesLinearShape && isBetterLinearFit(candidate, bestValid, sweepDuty)) {
        bestValid = candidate;
      }
    }
  }

  if (bestValid.valid) {
    return bestValid;
  }

  if (bestFallback.valid) {
    bestFallback.fallbackUsed = true;
    return bestFallback;
  }

  LinearRangeFit fallback = {};
  fallback.startIndex = 0;
  fallback.endIndex = points - 1;
  fallback.valid = true;
  fallback.fallbackUsed = true;

  if (points >= 2) {
    float deltaDuty = sweepDuty[points - 1] - sweepDuty[0];
    fallback.slope = deltaDuty > 0.0f ? (sweepMainAdc[points - 1] - sweepMainAdc[0]) / deltaDuty : 0.0f;
    fallback.intercept = sweepMainAdc[0] - (fallback.slope * sweepDuty[0]);
  } else {
    fallback.slope = 0.0f;
    fallback.intercept = sweepMainAdc[0];
  }

  return fallback;
}

bool isNoisyPwmDutyFromSweep(const float sweepMainAdc[MAX_SWEEP_POINTS], int points, int index) {
  if (index <= 0 || index >= points - 1) {
    return false;
  }

  // The ADC drop identifies a bad PWM duty; tracking avoidance is based on duty distance.
  float expectedFromNeighbors = (sweepMainAdc[index - 1] + sweepMainAdc[index + 1]) * 0.5f;
  float dip = expectedFromNeighbors - sweepMainAdc[index];
  float requiredDip = fmaxf(PWM_NOISE_MIN_DROP_ADC, expectedFromNeighbors * PWM_NOISE_MIN_DROP_FRACTION);
  return dip >= requiredDip;
}

bool isDutyInNoisyPwmBand(uint16_t duty, const uint16_t sweepDuty[MAX_SWEEP_POINTS], const float sweepMainAdc[MAX_SWEEP_POINTS], int points) {
  for (int i = 1; i < points - 1; i++) {
    if (!isNoisyPwmDutyFromSweep(sweepMainAdc, points, i)) {
      continue;
    }

    uint16_t distance = duty > sweepDuty[i] ? duty - sweepDuty[i] : sweepDuty[i] - duty;
    if (distance <= PWM_NOISE_DUTY_GUARD) {
      return true;
    }
  }

  return false;
}

int findClosestSweepIndexToTarget(const uint16_t sweepDuty[MAX_SWEEP_POINTS], const float sweepMainAdc[MAX_SWEEP_POINTS], int startIndex, int endIndex, float targetAdc) {
  int bestIndex = startIndex;
  float bestError = fabsf(sweepMainAdc[startIndex] - targetAdc);

  for (int i = startIndex + 1; i <= endIndex; i++) {
    float currentError = fabsf(sweepMainAdc[i] - targetAdc);
    if (currentError < bestError) {
      bestError = currentError;
      bestIndex = i;
    }
  }

  return bestIndex;
}

CalibrationResult calibrateOnePair(int activeLed) {
  uint16_t sweepDuty[MAX_SWEEP_POINTS];
  float sweepMainAdc[MAX_SWEEP_POINTS];
  float means[NUM_CHANNELS];
  int points = 0;

  CalibrationResult result = {};
  result.peakAdc = -1.0f;

  for (uint16_t duty = 0;;) {
    measureLedToAllDiodes(activeLed, duty, CALIBRATION_REPEATS, means);

    writeCalibrationSweepRow(calibrationSweepFile, activeLed, duty, means);
    mirrorCalibrationSweepRow(activeLed, duty, means);
    calibrationSweepFile.flush();

    sweepDuty[points] = duty;
    sweepMainAdc[points] = means[activeLed];
    points++;

    if (means[activeLed] > result.peakAdc) {
      result.peakAdc = means[activeLed];
      result.peakDuty = duty;
    }

    if (means[activeLed] >= ADC_LIMIT) {
      result.limitReached = true;
      break;
    }

    if (duty == PWM_MAX) {
      break;
    }

    uint32_t nextDuty = duty + CALIBRATION_DUTY_STEP;
    duty = nextDuty > PWM_MAX ? PWM_MAX : nextDuty;
  }

  LinearRangeFit fit = findLinearRange(sweepDuty, sweepMainAdc, points);
  result.linearStartDuty = sweepDuty[fit.startIndex];
  result.linearEndDuty = sweepDuty[fit.endIndex];
  result.linearStartAdc = (fit.slope * result.linearStartDuty) + fit.intercept;
  result.linearEndAdc = (fit.slope * result.linearEndDuty) + fit.intercept;
  result.fitSlope = fit.slope;
  result.fitIntercept = fit.intercept;
  result.fitRSquared = fit.rSquared;
  result.fallbackFit = fit.fallbackUsed;
  result.sweepPoints = points;

  float usableMaxAdc = result.linearEndAdc;
  if (result.peakAdc > 0.0f && (usableMaxAdc <= 0.0f || usableMaxAdc > result.peakAdc)) {
    usableMaxAdc = result.peakAdc;
  }
  float selectedFraction = TRACKING_FRACTION_OF_MAX;
  int selectedIndex = findClosestSweepIndexToTarget(sweepDuty, sweepMainAdc, fit.startIndex, fit.endIndex, usableMaxAdc * selectedFraction);

  for (float fraction = TRACKING_FRACTION_OF_MAX; fraction >= MIN_TRACKING_FRACTION_OF_MAX - 0.001f; fraction -= TRACKING_FRACTION_STEP) {
    float targetAdc = usableMaxAdc * fraction;
    int candidateIndex = findClosestSweepIndexToTarget(sweepDuty, sweepMainAdc, fit.startIndex, fit.endIndex, targetAdc);

    if (isDutyInNoisyPwmBand(sweepDuty[candidateIndex], sweepDuty, sweepMainAdc, points)) {
      continue;
    }

    selectedFraction = fraction;
    selectedIndex = candidateIndex;
    break;
  }

  if (isDutyInNoisyPwmBand(sweepDuty[selectedIndex], sweepDuty, sweepMainAdc, points)) {
    for (int i = selectedIndex - 1; i >= fit.startIndex; i--) {
      if (!isDutyInNoisyPwmBand(sweepDuty[i], sweepDuty, sweepMainAdc, points)) {
        selectedIndex = i;
        selectedFraction = usableMaxAdc > 0.0f ? sweepMainAdc[i] / usableMaxAdc : 0.0f;
        break;
      }
    }
  }

  result.targetAdc = usableMaxAdc * selectedFraction;
  result.trackingDuty = sweepDuty[selectedIndex];
  result.trackingReferenceAdc = sweepMainAdc[selectedIndex];

  writeCalibrationSummaryRow(calibrationSummaryFile, activeLed, result);
  mirrorCalibrationSummaryRow(activeLed, result);
  calibrationSummaryFile.flush();

  return result;
}

void runCalibration() {
  for (int led = 0; led < NUM_CHANNELS; led++) {
    logCalibrationStart(led);
    calibration[led] = calibrateOnePair(led);
    logCalibrationDone(led, calibration[led]);
  }

  calibrationSweepFile.close();
  calibrationSummaryFile.close();
}

void logTrackingRepeats(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, uint16_t duty, int repeats, const uint16_t rawSamples[MAX_MEASUREMENT_REPEATS][NUM_CHANNELS]) {
  for (int rep = 0; rep < repeats; rep++) {
    writeTrackingRepeatsRow(trackingRepeatsFile, timestampMs, cycleIndex, activeLed, duty, rep, rawSamples[rep]);
    mirrorTrackingRepeatsRow(timestampMs, cycleIndex, activeLed, duty, rep, rawSamples[rep]);
  }
}

void logTrackingRow(unsigned long timestampMs, unsigned long cycleIndex, int activeLed, const float means[NUM_CHANNELS]) {
  writeTrackingRow(trackingFile, timestampMs, cycleIndex, activeLed, means);
  mirrorTrackingRow(timestampMs, cycleIndex, activeLed, means);
}

void setup() {
  Serial.begin(115200);
  delay(500);
  logStatus("board booted");

  analogReadResolution(ADC_BITS);
  for (int i = 0; i < NUM_CHANNELS; i++) {
    analogSetPinAttenuation(diode_channels[i], ADC_6db);
  }

  bool pwmOk = true;
  for (int i = 0; i < NUM_CHANNELS; i++) {
    pwmOk &= ledcAttach(led_channels[i], PWM_FREQ, PWM_BITS);
  }

  if (!pwmOk) {
    fatalError("PWM setup failed.");
  }

  allLedsOff();

  if (!LittleFS.begin(true)) {
    fatalError("LittleFS mount failed.");
  }

  prepareLogFiles();
  logStatus("csv headers sent, calibration starting");
  runCalibration();
  logTrackingStarted();
}

void loop() {
  static unsigned long cycleIndex = 0;
  float means[NUM_CHANNELS];
  uint16_t rawSamples[MAX_MEASUREMENT_REPEATS][NUM_CHANNELS] = {};
  unsigned long cycleStart = millis();

  logTrackingCycle(cycleIndex);

  for (int led = 0; led < NUM_CHANNELS; led++) {
    measureLedToAllDiodes(led, calibration[led].trackingDuty, TRACKING_REPEATS, means, rawSamples);

    unsigned long timestampMs = millis();
    logTrackingRepeats(timestampMs, cycleIndex, led, calibration[led].trackingDuty, TRACKING_REPEATS, rawSamples);
    logTrackingRow(timestampMs, cycleIndex, led, means);

    trackingRepeatsFile.flush();
    trackingFile.flush();
  }

  cycleIndex++;

  unsigned long elapsed = millis() - cycleStart;
  if (elapsed < TRACKING_INTERVAL_MS) {
    delay(TRACKING_INTERVAL_MS - elapsed);
  }
}
