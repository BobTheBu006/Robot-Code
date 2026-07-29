#include <Arduino.h>  

const int NUM_CHANNELS = 6;

const int diode_channels[NUM_CHANNELS] = {32, 34, 36, 33, 35, 39};
const int led_channels[NUM_CHANNELS]   = {23, 13, 14, 27, 26, 25};

// Use true 0..1023 PWM range
const uint32_t PWM_FREQ = 20000;
const uint8_t  PWM_BITS = 10;
const uint16_t PWM_MAX  = (1 << PWM_BITS) - 1;

// Sweep settings
const uint16_t DUTY_STEP = 8;
const int REPEATS_PER_DUTY = 5;

// Timing
const int BETWEEN_CHANNEL_MS = 200;
const int LED_SETTLE_MS = 12;
const int BETWEEN_REPEAT_MS = 4;
const int BETWEEN_ADC_US = 200;

// ADC
const int ADC_BITS = 12;
const int ADC_SAMPLES = 32;   // multisampling count

void allLedsOff() {
  for (int i = 0; i < NUM_CHANNELS; i++) {
    ledcWrite(led_channels[i], 0);
  }
}

int readAdcOnce(int pin) {
  return analogRead(pin);
}

int readAdcAverage(int pin, int samples) {
  long sum = 0;
  for (int i = 0; i < samples; i++) {
    sum += analogRead(pin);
    delayMicroseconds(BETWEEN_ADC_US);
  }
  return sum / samples;
}

void setup() {
  Serial.begin(115200);
  delay(800);

  analogReadResolution(ADC_BITS);
  for (int i = 0; i < NUM_CHANNELS; i++) {
    analogSetPinAttenuation(diode_channels[i], ADC_6db);
  }

  bool allOk = true;
  for (int i = 0; i < NUM_CHANNELS; i++) {
    bool ok = ledcAttach(led_channels[i], PWM_FREQ, PWM_BITS);
    Serial.print("LED pin ");
    Serial.print(led_channels[i]);
    Serial.print(" attach: ");
    Serial.println(ok ? "OK" : "FAIL");
    allOk &= ok;
  }

  allLedsOff();

  Serial.print("PWM bits: ");
  Serial.println(PWM_BITS);
  Serial.print("PWM max duty: ");
  Serial.println(PWM_MAX);
  Serial.print("PWM freq actual: ");
  Serial.println(ledcReadFreq(led_channels[0]));
  Serial.print("ADC samples per reading: ");
  Serial.println(ADC_SAMPLES);

  if (!allOk) {
    Serial.println("PWM setup failed.");
    while (true) delay(1000);
  }

  // CSV header
  Serial.println("active_led,duty,repeat,ch0,ch1,ch2,ch3,ch4,ch5");
}

void loop() {
  for (int active = 0; active < NUM_CHANNELS; active++) {
    allLedsOff();
    delay(BETWEEN_CHANNEL_MS);

    for (uint16_t duty = 0; duty <= PWM_MAX; duty += DUTY_STEP) {
      allLedsOff();

      // Turn on only the active LED and keep it on
      ledcWrite(led_channels[active], duty);
      delay(LED_SETTLE_MS);

      // Take repeated measurements while PWM stays on
      for (int rep = 0; rep < REPEATS_PER_DUTY; rep++) {
        int vals[NUM_CHANNELS];

        for (int ch = 0; ch < NUM_CHANNELS; ch++) {
          vals[ch] = readAdcAverage(diode_channels[ch], ADC_SAMPLES);
        }

        Serial.print(active);
        Serial.print(",");
        Serial.print(duty);
        Serial.print(",");
        Serial.print(rep);

        for (int ch = 0; ch < NUM_CHANNELS; ch++) {
          Serial.print(",");
          Serial.print(vals[ch]);
        }
        Serial.println();

        delay(BETWEEN_REPEAT_MS);
      }

      // Turn LED off before next duty
      ledcWrite(led_channels[active], 0);
      delay(4);
    }
  }

  allLedsOff();
  Serial.println("DONE");

  while (true) delay(1000);
}
