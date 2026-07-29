/*
 * STM32 NUCLEO-G474RE bare-metal TLC59711 optical/OD calibration + tracking.
 *
 * Host commands over USART2 / ST-LINK VCP at 921600 baud:
 *   RESET_CALIBRATE     reset measurement state, calibrate all pairs, track
 *   REUSE_CALIBRATION   restart tracking from pair 0 with RAM calibration
 *   LOADZERO            clear host-restored calibration rows
 *   LOADROW,i,duty,ref_centi
 *                       restore one calibration row from host CSV
 *   STATUS              print calibration state
 *   BOARD_RESET         call NVIC_SystemReset()
 *
 * Pins:
 *   USART2 TX/RX: PA2/PA3, reserved for ST-LINK virtual COM port
 *   TLC59711 clock: PB6
 *   TLC59711 data:  Arduino D9 = PC7
 */

#include "stm32g474xx.h"

#include <math.h>
#include <stdbool.h>
#include <stdint.h>
#include <stdlib.h>
#include <string.h>

#define SYSCLK_HZ 16000000UL
#define UART_BAUD 115200UL

#define NUM_CHANNELS 24U
#define NUM_TLC_BOARDS 2U
#define TLC_OUTPUTS_PER_BOARD 12U
#define NUM_TLC_OUTPUTS (NUM_TLC_BOARDS * TLC_OUTPUTS_PER_BOARD)
#define TLC_OUTPUT_DISABLED 0xFFU
#define ADC_SAMPLES 32U
#define CALIBRATION_REPEATS 5U
#define TRACKING_REPEATS 8U
#define MAX_MEASUREMENT_REPEATS TRACKING_REPEATS
#define BETWEEN_ADC_US 200U

#define PWM_MAX 65535U
#define CALIBRATION_DUTY_STEP 512U
#define MAX_SWEEP_POINTS ((PWM_MAX / CALIBRATION_DUTY_STEP) + 3U)

#define ADC_LIMIT 4090.0f
#define TRACKING_FRACTION_OF_MAX 0.80f
#define MIN_TRACKING_FRACTION_OF_MAX 0.70f
#define TRACKING_FRACTION_STEP 0.05f
#define PWM_NOISE_MIN_DROP_ADC 40.0f
#define PWM_NOISE_MIN_DROP_FRACTION 0.02f
#define PWM_NOISE_DUTY_GUARD (CALIBRATION_DUTY_STEP * 2U)

#define MIN_LINEAR_POINTS 6
#define MIN_LINEAR_R_SQUARED 0.995f
#define MAX_LINEAR_RESIDUAL_FRACTION 0.06f
#define MIN_EDGE_SLOPE_RATIO 0.45f

#define LED_SETTLE_MS 12U
#define TRACKING_LED_ON_BEFORE_MEASURE_MS 1000U
#define TRACKING_LED_ON_AFTER_MEASURE_MS 1000U
#define CALIBRATION_PWM_SETTLE_MS 50U
#define CALIBRATION_AFTER_MEASURE_MS 20U
#define BETWEEN_REPEAT_MS 4U
#define BETWEEN_LED_MS 8U
#define BETWEEN_TRACKING_CYCLES_MS 120000U

#define TLC_CLOCK_PORT GPIOB
#define TLC_CLOCK_PIN 6U
#define TLC_DATA_PORT GPIOC
#define TLC_DATA_PIN 7U

#define AHT_SDA_PORT GPIOB
#define AHT_SDA_PIN 8U
#define AHT_SCL_PORT GPIOB
#define AHT_SCL_PIN 9U
#define AHT_I2C_ADDRESS 0x38U
#define AHT_I2C_DELAY_US 5U

typedef enum {
  ACTION_NONE = 0,
  ACTION_CALIBRATE,
  ACTION_REUSE_CALIBRATION,
} RequestedAction;

typedef struct {
  ADC_TypeDef *adc;
  uint8_t channel;
  bool enabled;
} AdcInput;

typedef struct {
  int start_index;
  int end_index;
  float slope;
  float intercept;
  float r_squared;
  float residual_fraction;
  bool valid;
  bool fallback_used;
} LinearRangeFit;

typedef struct {
  uint16_t peak_duty;
  float peak_adc;
  uint16_t linear_start_duty;
  uint16_t linear_end_duty;
  float linear_start_adc;
  float linear_end_adc;
  float fit_slope;
  float fit_intercept;
  float fit_r_squared;
  float target_adc;
  uint16_t tracking_duty;
  float tracking_reference_adc;
  int sweep_points;
  bool limit_reached;
  bool fallback_fit;
} CalibrationResult;

static const AdcInput adc_inputs[NUM_CHANNELS] = {
    {ADC1, 14, true},   /* ch0  PB11 ADC1_IN14 */
    {ADC1, 11, true},   /* ch1  PB12 ADC1_IN11 */
    {ADC1, 8, true},    /* ch2  PC2  ADC1_IN8 */
    {ADC1, 9, true},    /* ch3  PC3  ADC1_IN9 */
    {ADC2, 11, true},   /* ch4  PC5  ADC2_IN11 */
    {ADC2, 4, true},    /* ch5  PA7  ADC2_IN4 */
    {ADC2, 15, true},   /* ch6  PB15 ADC2_IN15 */
    {ADC1, 5, true},    /* ch7  PB14 ADC1_IN5 */
    {ADC5, 2, true},    /* ch8  PA9  ADC5_IN2 */
    {ADC5, 1, true},    /* ch9  PA8  ADC5_IN1 */
    {ADC2, 12, true},   /* ch10 PB2  ADC2_IN12 */
    {ADC1, 12, true},   /* ch11 PB1  ADC1_IN12 */
    {ADC2, 5, true},    /* ch12 PC4  ADC2_IN5 */
    {ADC3, 5, true},    /* ch13 PB13 ADC3_IN5 */
    {ADC1, 7, true},    /* ch14 PC1  ADC1_IN7 */
    {ADC1, 6, true},    /* ch15 PC0  ADC1_IN6 */
    {ADC2, 3, true},    /* ch16 PA6  ADC2_IN3 */
    {ADC2, 13, true},   /* ch17 PA5  ADC2_IN13 */
    {ADC2, 17, true},   /* ch18 PA4  ADC2_IN17 */
    {ADC1, 15, true},   /* ch19 PB0  ADC1_IN15 */
    {NULL, 0, false},   /* ch20 off, no ADC */
    {NULL, 0, false},   /* ch21 off, no ADC */
    {ADC1, 1, true},    /* ch22 PA0  ADC1_IN1 */
    {ADC1, 2, true},    /* ch23 PA1  ADC1_IN2 */
};

static const char *channel_columns[NUM_CHANNELS] = {
    "ch0_pb11",
    "ch1_pb12",
    "ch2_pc2",
    "ch3_pc3",
    "ch4_pc5",
    "ch5_pa7",
    "ch6_pb15",
    "ch7_pb14",
    "ch8_pa9",
    "ch9_pa8",
    "ch10_pb2",
    "ch11_pb1",
    "ch12_pc4",
    "ch13_pb13",
    "ch14_pc1",
    "ch15_pc0",
    "ch16_pa6",
    "ch17_pa5",
    "ch18_pa4",
    "ch19_pb0",
    "ch20_off",
    "ch21_off",
    "ch22_pa0",
    "ch23_pa1",
};

/*
 * TLC channel order follows the Adafruit TLC59711 convention:
 *   0=R0, 1=G0, 2=B0, 3=R1, 4=G1, 5=B1,
 *   6=R2, 7=G2, 8=B2, 9=R3, 10=G3, 11=B3.
 */
static const uint8_t tlc_output_for_pair[NUM_CHANNELS] = {
    8,                   /* pair 0:  PB11 with board 1 G1 */
    9,                   /* pair 1:  PB12 with board 1 B1 */
    3,                   /* pair 2:  PC2  with board 2 G0 */
    2,                   /* pair 3:  PC3  with board 2 R0 */
    4,                   /* pair 4:  PC5  with board 1 B0 */
    5,                   /* pair 5:  PA7  with board 1 R1 */
    7,                   /* pair 6:  PB15 with board 2 R1 */
    6,                   /* pair 7:  PB14 with board 2 B0 */
    0,                   /* pair 8:  PA9  with board 1 R0 */
    1,                   /* pair 9:  PA8  with board 1 G0 */
    11,                  /* pair 10: PB2  with board 2 B1 */
    10,                  /* pair 11: PB1  with board 2 G1 */
    20,                  /* pair 12: PC4  with board 1 R2 */
    21,                  /* pair 13: PB13 with board 1 G2 */
    22,                  /* pair 14: PC1  with board 2 G3 */
    23,                  /* pair 15: PC0  with board 2 B3 */
    16,                  /* pair 16: PA6  with board 1 B2 */
    17,                  /* pair 17: PA5  with board 1 R3 */
    18,                  /* pair 18: PA4  with board 2 B2 */
    19,                  /* pair 19: PB0  with board 2 R3 */
    12,                  /* pair 20: no ADC with board 1 G3, skipped in measurement */
    13,                  /* pair 21: no ADC with board 1 B3, skipped in measurement */
    14,                  /* pair 22: PA0  with board 2 R2 */
    15,                  /* pair 23: PA1  with board 2 G2 */
};

static const uint8_t tlc_logical_output_for_board_channel[NUM_TLC_BOARDS][TLC_OUTPUTS_PER_BOARD] = {
    {0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20, 21},      /* board 1 */
    {2, 3, 6, 7, 10, 11, 14, 15, 18, 19, 22, 23},    /* board 2 */
};

static uint16_t tlc_pwm[NUM_TLC_OUTPUTS];
static CalibrationResult calibration[NUM_CHANNELS];
static bool calibration_valid = false;
static uint32_t calibration_loaded_mask = 0U;
static volatile uint32_t system_millis = 0;
static RequestedAction requested_action = ACTION_NONE;
static char command_buffer[64];
static uint32_t command_length = 0;

void SysTick_Handler(void) {
  system_millis++;
}

static uint32_t millis(void) {
  return system_millis;
}

static void delay_us(uint32_t us) {
  const uint32_t cycles = (SYSCLK_HZ / 1000000UL) * us;
  const uint32_t start = DWT->CYCCNT;
  while ((DWT->CYCCNT - start) < cycles) {
  }
}

static void delay_ms(uint32_t ms) {
  const uint32_t start = millis();
  while ((millis() - start) < ms) {
  }
}

static void dwt_init(void) {
  CoreDebug->DEMCR |= CoreDebug_DEMCR_TRCENA_Msk;
  DWT->CYCCNT = 0;
  DWT->CTRL |= DWT_CTRL_CYCCNTENA_Msk;
}

static void clock_init_hsi16(void) {
  RCC->CR |= RCC_CR_HSION;
  while ((RCC->CR & RCC_CR_HSIRDY) == 0U) {
  }

  FLASH->ACR = (FLASH->ACR & ~FLASH_ACR_LATENCY) |
               FLASH_ACR_LATENCY_0WS |
               FLASH_ACR_PRFTEN |
               FLASH_ACR_ICEN |
               FLASH_ACR_DCEN;

  RCC->CFGR = (RCC->CFGR & ~(RCC_CFGR_SW | RCC_CFGR_HPRE | RCC_CFGR_PPRE1 | RCC_CFGR_PPRE2)) |
              RCC_CFGR_SW_HSI |
              RCC_CFGR_HPRE_DIV1 |
              RCC_CFGR_PPRE1_DIV1 |
              RCC_CFGR_PPRE2_DIV1;
  while ((RCC->CFGR & RCC_CFGR_SWS) != RCC_CFGR_SWS_HSI) {
  }
}

static void gpio_set_mode(GPIO_TypeDef *gpio, uint32_t pin, uint32_t mode) {
  gpio->MODER = (gpio->MODER & ~(0x3UL << (pin * 2U))) |
                (mode << (pin * 2U));
}

static void gpio_set_af(GPIO_TypeDef *gpio, uint32_t pin, uint32_t af) {
  const uint32_t index = pin >> 3U;
  const uint32_t shift = (pin & 0x7U) * 4U;
  gpio->AFR[index] = (gpio->AFR[index] & ~(0xFUL << shift)) |
                     (af << shift);
}

static void gpio_make_output(GPIO_TypeDef *gpio, uint32_t pin) {
  gpio_set_mode(gpio, pin, 0x1UL);
  gpio->OTYPER &= ~(1UL << pin);
  gpio->PUPDR &= ~(0x3UL << (pin * 2U));
  gpio->OSPEEDR |= (0x3UL << (pin * 2U));
}

static void gpio_make_open_drain_output(GPIO_TypeDef *gpio, uint32_t pin) {
  gpio_set_mode(gpio, pin, 0x1UL);
  gpio->OTYPER |= (1UL << pin);
  gpio->PUPDR &= ~(0x3UL << (pin * 2U));
  gpio->OSPEEDR |= (0x3UL << (pin * 2U));
}

static void gpio_make_input(GPIO_TypeDef *gpio, uint32_t pin) {
  gpio_set_mode(gpio, pin, 0x0UL);
  gpio->PUPDR &= ~(0x3UL << (pin * 2U));
}

static void gpio_make_analog_adc(GPIO_TypeDef *gpio, uint32_t pin) {
  gpio_set_mode(gpio, pin, 0x3UL);
  gpio->PUPDR &= ~(0x3UL << (pin * 2U));
}

static void gpio_init(void) {
  RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN |
                  RCC_AHB2ENR_GPIOBEN |
                  RCC_AHB2ENR_GPIOCEN;
  (void)RCC->AHB2ENR;

  gpio_set_mode(GPIOA, 2U, 0x2UL);
  gpio_set_mode(GPIOA, 3U, 0x2UL);
  gpio_set_af(GPIOA, 2U, 7U);
  gpio_set_af(GPIOA, 3U, 7U);
  GPIOA->OSPEEDR |= (0x3UL << (2U * 2U)) | (0x3UL << (3U * 2U));
  GPIOA->PUPDR &= ~((0x3UL << (2U * 2U)) | (0x3UL << (3U * 2U)));

  gpio_make_output(TLC_CLOCK_PORT, TLC_CLOCK_PIN);
  gpio_make_output(TLC_DATA_PORT, TLC_DATA_PIN);
  gpio_make_input(AHT_SDA_PORT, AHT_SDA_PIN);
  gpio_make_input(AHT_SCL_PORT, AHT_SCL_PIN);

  gpio_make_analog_adc(GPIOA, 0U);
  gpio_make_analog_adc(GPIOA, 1U);
  gpio_make_analog_adc(GPIOA, 4U);
  gpio_make_analog_adc(GPIOA, 5U);
  gpio_make_analog_adc(GPIOA, 6U);
  gpio_make_analog_adc(GPIOA, 7U);
  gpio_make_analog_adc(GPIOA, 8U);
  gpio_make_analog_adc(GPIOA, 9U);
  gpio_make_analog_adc(GPIOB, 0U);
  gpio_make_analog_adc(GPIOB, 1U);
  gpio_make_analog_adc(GPIOB, 2U);
  gpio_make_analog_adc(GPIOB, 11U);
  gpio_make_analog_adc(GPIOB, 12U);
  gpio_make_analog_adc(GPIOB, 13U);
  gpio_make_analog_adc(GPIOB, 14U);
  gpio_make_analog_adc(GPIOB, 15U);
  gpio_make_analog_adc(GPIOC, 0U);
  gpio_make_analog_adc(GPIOC, 1U);
  gpio_make_analog_adc(GPIOC, 2U);
  gpio_make_analog_adc(GPIOC, 3U);
  gpio_make_analog_adc(GPIOC, 4U);
  gpio_make_analog_adc(GPIOC, 5U);
}

static void usart2_init(void) {
  RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
  (void)RCC->APB1ENR1;

  USART2->CR1 = 0U;
  USART2->BRR = (SYSCLK_HZ + (UART_BAUD / 2UL)) / UART_BAUD;
  USART2->CR1 = USART_CR1_TE | USART_CR1_RE | USART_CR1_UE;
}

static void uart_write_char(char c) {
#ifdef USART_ISR_TXE_TXFNF
  while ((USART2->ISR & USART_ISR_TXE_TXFNF) == 0U) {
  }
#else
  while ((USART2->ISR & USART_ISR_TXE) == 0U) {
  }
#endif
  USART2->TDR = (uint32_t)(uint8_t)c;
}

static bool uart_read_char(char *out) {
#ifdef USART_ISR_RXNE_RXFNE
  if ((USART2->ISR & USART_ISR_RXNE_RXFNE) == 0U) {
    return false;
  }
#else
  if ((USART2->ISR & USART_ISR_RXNE) == 0U) {
    return false;
  }
#endif

  *out = (char)(USART2->RDR & 0xFFU);
  return true;
}

static void uart_write_str(const char *s) {
  while (*s != '\0') {
    uart_write_char(*s++);
  }
}

static void uart_write_u32(uint32_t value) {
  char buffer[10];
  uint32_t index = 0U;

  if (value == 0U) {
    uart_write_char('0');
    return;
  }

  while (value > 0U && index < sizeof(buffer)) {
    buffer[index++] = (char)('0' + (value % 10U));
    value /= 10U;
  }

  while (index > 0U) {
    uart_write_char(buffer[--index]);
  }
}

static void uart_write_float(float value, uint8_t decimals) {
  if (isnan(value)) {
    uart_write_str("nan");
    return;
  }

  if (value < 0.0f) {
    uart_write_char('-');
    value = -value;
  }

  uint32_t scale = 1U;
  for (uint8_t i = 0U; i < decimals; i++) {
    scale *= 10U;
  }

  uint32_t integer = (uint32_t)value;
  float fractional_value = (value - (float)integer) * (float)scale;
  uint32_t fractional = (uint32_t)(fractional_value + 0.5f);
  if (fractional >= scale) {
    integer++;
    fractional -= scale;
  }

  uart_write_u32(integer);
  if (decimals == 0U) {
    return;
  }

  uart_write_char('.');
  uint32_t divisor = scale / 10U;
  while (divisor > 0U) {
    uart_write_char((char)('0' + ((fractional / divisor) % 10U)));
    divisor /= 10U;
  }
}

static void aht_sda_low(void) {
  AHT_SDA_PORT->BSRR = (1UL << (AHT_SDA_PIN + 16U));
  gpio_make_open_drain_output(AHT_SDA_PORT, AHT_SDA_PIN);
}

static void aht_sda_release(void) {
  gpio_make_input(AHT_SDA_PORT, AHT_SDA_PIN);
}

static bool aht_sda_read(void) {
  return (AHT_SDA_PORT->IDR & (1UL << AHT_SDA_PIN)) != 0U;
}

static void aht_scl_low(void) {
  AHT_SCL_PORT->BSRR = (1UL << (AHT_SCL_PIN + 16U));
  gpio_make_open_drain_output(AHT_SCL_PORT, AHT_SCL_PIN);
}

static void aht_scl_release(void) {
  gpio_make_input(AHT_SCL_PORT, AHT_SCL_PIN);
}

static void aht_i2c_delay(void) {
  delay_us(AHT_I2C_DELAY_US);
}

static void aht_i2c_start(void) {
  aht_sda_release();
  aht_scl_release();
  aht_i2c_delay();
  aht_sda_low();
  aht_i2c_delay();
  aht_scl_low();
}

static void aht_i2c_stop(void) {
  aht_sda_low();
  aht_i2c_delay();
  aht_scl_release();
  aht_i2c_delay();
  aht_sda_release();
  aht_i2c_delay();
}

static bool aht_i2c_write_byte(uint8_t value) {
  for (int32_t bit = 7; bit >= 0; bit--) {
    if (((uint32_t)value & (1UL << (uint32_t)bit)) != 0U) {
      aht_sda_release();
    } else {
      aht_sda_low();
    }

    aht_i2c_delay();
    aht_scl_release();
    aht_i2c_delay();
    aht_scl_low();
  }

  aht_sda_release();
  aht_i2c_delay();
  aht_scl_release();
  aht_i2c_delay();
  const bool ack = !aht_sda_read();
  aht_scl_low();
  return ack;
}

static uint8_t aht_i2c_read_byte(bool ack) {
  uint8_t value = 0U;

  aht_sda_release();
  for (int32_t bit = 7; bit >= 0; bit--) {
    aht_i2c_delay();
    aht_scl_release();
    aht_i2c_delay();
    if (aht_sda_read()) {
      value |= (uint8_t)(1U << (uint32_t)bit);
    }
    aht_scl_low();
  }

  if (ack) {
    aht_sda_low();
  } else {
    aht_sda_release();
  }

  aht_i2c_delay();
  aht_scl_release();
  aht_i2c_delay();
  aht_scl_low();
  aht_sda_release();
  return value;
}

static bool aht_write_command(uint8_t command, uint8_t arg0, uint8_t arg1) {
  aht_i2c_start();
  bool ok = aht_i2c_write_byte((uint8_t)(AHT_I2C_ADDRESS << 1U));
  ok = aht_i2c_write_byte(command) && ok;
  ok = aht_i2c_write_byte(arg0) && ok;
  ok = aht_i2c_write_byte(arg1) && ok;
  aht_i2c_stop();
  return ok;
}

static bool aht_read_bytes(uint8_t data[6]) {
  aht_i2c_start();
  bool ok = aht_i2c_write_byte((uint8_t)((AHT_I2C_ADDRESS << 1U) | 1U));
  for (uint32_t i = 0U; i < 6U; i++) {
    data[i] = aht_i2c_read_byte(i + 1U < 6U);
  }
  aht_i2c_stop();
  return ok;
}

static void aht_init(void) {
  aht_sda_release();
  aht_scl_release();
  delay_ms(40U);
  (void)aht_write_command(0xBEU, 0x08U, 0x00U);
  delay_ms(10U);
}

static bool aht_read(float *temperature_c, float *humidity_percent) {
  uint8_t data[6] = {0U};

  if (!aht_write_command(0xACU, 0x33U, 0x00U)) {
    return false;
  }

  delay_ms(80U);

  if (!aht_read_bytes(data) || (data[0] & 0x80U) != 0U) {
    return false;
  }

  const uint32_t humidity_raw =
      ((uint32_t)data[1] << 12U) |
      ((uint32_t)data[2] << 4U) |
      ((uint32_t)data[3] >> 4U);
  const uint32_t temperature_raw =
      (((uint32_t)data[3] & 0x0FU) << 16U) |
      ((uint32_t)data[4] << 8U) |
      (uint32_t)data[5];

  *humidity_percent = ((float)humidity_raw * 100.0f) / 1048576.0f;
  *temperature_c = (((float)temperature_raw * 200.0f) / 1048576.0f) - 50.0f;
  return true;
}

static void adc_set_sample_time(ADC_TypeDef *adc, uint8_t channel) {
  const uint32_t sample_time = 6U; /* 247.5 ADC cycles */

  if (channel <= 9U) {
    const uint32_t shift = (uint32_t)channel * 3U;
    adc->SMPR1 = (adc->SMPR1 & ~(0x7UL << shift)) |
                 (sample_time << shift);
  } else {
    const uint32_t shift = ((uint32_t)channel - 10U) * 3U;
    adc->SMPR2 = (adc->SMPR2 & ~(0x7UL << shift)) |
                 (sample_time << shift);
  }
}

static void adc_enable_single_ended(ADC_TypeDef *adc) {
  if ((adc->CR & ADC_CR_ADEN) != 0U) {
    adc->CR |= ADC_CR_ADDIS;
    while ((adc->CR & ADC_CR_ADEN) != 0U) {
    }
  }

  adc->CR &= ~ADC_CR_DEEPPWD;
  adc->CR |= ADC_CR_ADVREGEN;
  delay_us(20U);

  adc->DIFSEL = 0U;
  adc->CFGR = 0U;
  adc->SMPR1 = 0U;
  adc->SMPR2 = 0U;

  for (uint32_t i = 0U; i < NUM_CHANNELS; i++) {
    if (adc_inputs[i].enabled && adc_inputs[i].adc == adc) {
      adc_set_sample_time(adc, adc_inputs[i].channel);
    }
  }

  adc->CR &= ~ADC_CR_ADCALDIF;
  adc->CR |= ADC_CR_ADCAL;
  while ((adc->CR & ADC_CR_ADCAL) != 0U) {
  }

  adc->ISR = ADC_ISR_ADRDY;
  adc->CR |= ADC_CR_ADEN;
  while ((adc->ISR & ADC_ISR_ADRDY) == 0U) {
  }
}

static void adc_init_all(void) {
  RCC->AHB2ENR |= RCC_AHB2ENR_ADC12EN | RCC_AHB2ENR_ADC345EN;
  (void)RCC->AHB2ENR;

  ADC12_COMMON->CCR = (ADC12_COMMON->CCR & ~ADC_CCR_CKMODE) |
                      ADC_CCR_CKMODE_0; /* HCLK / 1 = 16 MHz */
  ADC345_COMMON->CCR = (ADC345_COMMON->CCR & ~ADC_CCR_CKMODE) |
                       ADC_CCR_CKMODE_0; /* HCLK / 1 = 16 MHz */

  adc_enable_single_ended(ADC1);
  adc_enable_single_ended(ADC2);
  adc_enable_single_ended(ADC3);
  adc_enable_single_ended(ADC5);
}

static uint16_t adc_read_once(ADC_TypeDef *adc, uint8_t channel) {
  while ((adc->CR & ADC_CR_ADSTART) != 0U) {
  }

  adc->ISR = ADC_ISR_EOC | ADC_ISR_EOS | ADC_ISR_OVR;
  adc->SQR1 = ((uint32_t)channel << 6U);
  adc->CR |= ADC_CR_ADSTART;

  while ((adc->ISR & ADC_ISR_EOC) == 0U) {
  }

  return (uint16_t)(adc->DR & 0x0FFFU);
}

static uint16_t adc_read_average(uint32_t index) {
  uint32_t sum = 0U;
  const AdcInput *input = &adc_inputs[index];

  if (!input->enabled) {
    return 0U;
  }

  for (uint32_t i = 0U; i < ADC_SAMPLES; i++) {
    sum += adc_read_once(input->adc, input->channel);
    if (i + 1U < ADC_SAMPLES) {
      delay_us(BETWEEN_ADC_US);
    }
  }

  return (uint16_t)((sum + (ADC_SAMPLES / 2U)) / ADC_SAMPLES);
}

static void tlc_clock_low(void) {
  TLC_CLOCK_PORT->BSRR = (1UL << (TLC_CLOCK_PIN + 16U));
}

static void tlc_clock_high(void) {
  TLC_CLOCK_PORT->BSRR = (1UL << TLC_CLOCK_PIN);
}

static void tlc_data_low(void) {
  TLC_DATA_PORT->BSRR = (1UL << (TLC_DATA_PIN + 16U));
}

static void tlc_data_high(void) {
  TLC_DATA_PORT->BSRR = (1UL << TLC_DATA_PIN);
}

static void tlc_write_bit(uint32_t bit) {
  if (bit != 0U) {
    tlc_data_high();
  } else {
    tlc_data_low();
  }

  tlc_clock_high();
  tlc_clock_low();
}

static void tlc_write_u32(uint32_t value) {
  for (int32_t bit = 31; bit >= 0; bit--) {
    tlc_write_bit((value >> (uint32_t)bit) & 0x1UL);
  }
}

static void tlc_write_u16(uint16_t value) {
  for (int32_t bit = 15; bit >= 0; bit--) {
    tlc_write_bit(((uint32_t)value >> (uint32_t)bit) & 0x1UL);
  }
}

static void tlc_write(void) {
  const uint32_t write_command = 0x25UL;
  const uint32_t function_control = 0x16UL;
  const uint32_t brightness = 127UL;
  const uint32_t header = (write_command << 26U) |
                          (function_control << 21U) |
                          (brightness << 14U) |
                          (brightness << 7U) |
                          brightness;

  for (int32_t board = (int32_t)NUM_TLC_BOARDS - 1; board >= 0; board--) {
    tlc_write_u32(header);
    for (int32_t channel = (int32_t)TLC_OUTPUTS_PER_BOARD - 1; channel >= 0; channel--) {
      const uint8_t logical_output =
          tlc_logical_output_for_board_channel[board][channel];
      tlc_write_u16(tlc_pwm[logical_output]);
    }
  }

  delay_us(200U);
}

static void all_leds_off(void) {
  for (uint32_t i = 0U; i < NUM_TLC_OUTPUTS; i++) {
    tlc_pwm[i] = 0U;
  }
  tlc_write();
}

static void set_active_pair(uint8_t active_channel, uint16_t pwm) {
  for (uint32_t i = 0U; i < NUM_TLC_OUTPUTS; i++) {
    tlc_pwm[i] = 0U;
  }

  const uint8_t output = tlc_output_for_pair[active_channel];
  if (output != TLC_OUTPUT_DISABLED && output < NUM_TLC_OUTPUTS) {
    tlc_pwm[output] = pwm;
  }
  tlc_write();
}

static void poll_commands(void);

static void measure_pair_to_all_channels(
    uint8_t active_channel,
    uint16_t pwm,
    uint32_t repeats,
    float means[NUM_CHANNELS],
    uint16_t raw_samples[MAX_MEASUREMENT_REPEATS][NUM_CHANNELS]) {
  uint32_t sums[NUM_CHANNELS] = {0U};

  all_leds_off();
  delay_ms(BETWEEN_LED_MS);
  set_active_pair(active_channel, pwm);
  delay_ms(TRACKING_LED_ON_BEFORE_MEASURE_MS);

  for (uint32_t repeat = 0U; repeat < repeats; repeat++) {
    for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
      uint16_t reading = adc_read_average(ch);
      sums[ch] += reading;
      if (raw_samples != NULL && repeat < MAX_MEASUREMENT_REPEATS) {
        raw_samples[repeat][ch] = reading;
      }
    }

    poll_commands();
    if (repeat + 1U < repeats) {
      delay_ms(BETWEEN_REPEAT_MS);
    }
  }

  delay_ms(TRACKING_LED_ON_AFTER_MEASURE_MS);
  all_leds_off();
  delay_ms(BETWEEN_LED_MS);

  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    means[ch] = (float)sums[ch] / (float)repeats;
  }
}

static void measure_current_calibration_pwm_to_all_channels(
    uint32_t repeats,
    float means[NUM_CHANNELS]) {
  uint32_t sums[NUM_CHANNELS] = {0U};

  delay_ms(CALIBRATION_PWM_SETTLE_MS);

  for (uint32_t repeat = 0U; repeat < repeats; repeat++) {
    for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
      sums[ch] += adc_read_average(ch);
    }

    poll_commands();
    if (repeat + 1U < repeats) {
      delay_ms(BETWEEN_REPEAT_MS);
    }
  }

  delay_ms(CALIBRATION_AFTER_MEASURE_MS);

  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    means[ch] = (float)sums[ch] / (float)repeats;
  }
}

static void write_channel_floats(const float values[NUM_CHANNELS], uint8_t decimals) {
  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    uart_write_char(',');
    uart_write_float(values[ch], decimals);
  }
}

static void write_channel_raw(const uint16_t values[NUM_CHANNELS]) {
  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    uart_write_char(',');
    uart_write_u32(values[ch]);
  }
}

static void status(const char *message) {
  uart_write_str("STATUS: ");
  uart_write_str(message);
  uart_write_str("\r\n");
}

static void write_channel_column_names(void) {
  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    uart_write_char(',');
    uart_write_str(channel_columns[ch]);
  }
}

static void write_calibration_sweep_header(void) {
  uart_write_str("CSV,calibration_sweep.csv,");
  uart_write_str("led_index,duty,main_adc");
  write_channel_column_names();
  uart_write_str("\r\n");
}

static void write_calibration_summary_header(void) {
  uart_write_str("CSV,calibration_summary.csv,");
  uart_write_str("led_index,paired_diode,peak_duty,peak_adc,linear_start_duty,");
  uart_write_str("linear_end_duty,linear_start_adc,linear_end_adc,fit_slope,");
  uart_write_str("fit_intercept,fit_r_squared,target_adc,tracking_duty,");
  uart_write_str("tracking_reference_adc,limit_reached,fallback_fit,sweep_points\r\n");
}

static void write_tracking_header(void) {
  uart_write_str("CSV,tracking.csv,");
  uart_write_str("timestamp_ms,cycle,led_index,duty,reference_adc,main_adc,");
  uart_write_str("normalized,delta_od,temperature_c,humidity_percent");
  write_channel_column_names();
  uart_write_str("\r\n");
}

static void write_tracking_repeats_header(void) {
  uart_write_str("CSV,tracking_repeats.csv,");
  uart_write_str("timestamp_ms,cycle,led_index,duty,repeat");
  write_channel_column_names();
  uart_write_str("\r\n");
}

static void write_all_headers(void) {
  write_calibration_sweep_header();
  write_calibration_summary_header();
  write_tracking_header();
  write_tracking_repeats_header();
}

static void write_calibration_sweep_row(uint8_t active_channel, uint16_t duty,
                                        const float means[NUM_CHANNELS]) {
  uart_write_str("CSV,calibration_sweep.csv,");
  uart_write_u32(active_channel);
  uart_write_char(',');
  uart_write_u32(duty);
  uart_write_char(',');
  uart_write_float(means[active_channel], 2U);
  write_channel_floats(means, 2U);
  uart_write_str("\r\n");
}

static void write_calibration_summary_row(uint8_t active_channel,
                                          const CalibrationResult *result) {
  uart_write_str("CSV,calibration_summary.csv,");
  uart_write_u32(active_channel);
  uart_write_char(',');
  uart_write_u32(active_channel);
  uart_write_char(',');
  uart_write_u32(result->peak_duty);
  uart_write_char(',');
  uart_write_float(result->peak_adc, 2U);
  uart_write_char(',');
  uart_write_u32(result->linear_start_duty);
  uart_write_char(',');
  uart_write_u32(result->linear_end_duty);
  uart_write_char(',');
  uart_write_float(result->linear_start_adc, 2U);
  uart_write_char(',');
  uart_write_float(result->linear_end_adc, 2U);
  uart_write_char(',');
  uart_write_float(result->fit_slope, 6U);
  uart_write_char(',');
  uart_write_float(result->fit_intercept, 6U);
  uart_write_char(',');
  uart_write_float(result->fit_r_squared, 6U);
  uart_write_char(',');
  uart_write_float(result->target_adc, 2U);
  uart_write_char(',');
  uart_write_u32(result->tracking_duty);
  uart_write_char(',');
  uart_write_float(result->tracking_reference_adc, 2U);
  uart_write_char(',');
  uart_write_u32(result->limit_reached ? 1U : 0U);
  uart_write_char(',');
  uart_write_u32(result->fallback_fit ? 1U : 0U);
  uart_write_char(',');
  uart_write_u32((uint32_t)result->sweep_points);
  uart_write_str("\r\n");
}

static void write_tracking_repeats_row(uint32_t timestamp_ms, uint32_t cycle,
                                       uint8_t active_channel, uint16_t duty,
                                       uint32_t repeat,
                                       const uint16_t raw_values[NUM_CHANNELS]) {
  uart_write_str("CSV,tracking_repeats.csv,");
  uart_write_u32(timestamp_ms);
  uart_write_char(',');
  uart_write_u32(cycle);
  uart_write_char(',');
  uart_write_u32(active_channel);
  uart_write_char(',');
  uart_write_u32(duty);
  uart_write_char(',');
  uart_write_u32(repeat);
  write_channel_raw(raw_values);
  uart_write_str("\r\n");
}

static void write_tracking_row(uint32_t timestamp_ms, uint32_t cycle,
                               uint8_t active_channel,
                               const float means[NUM_CHANNELS],
                               float temperature_c,
                               float humidity_percent) {
  const float reference = calibration[active_channel].tracking_reference_adc;
  const float main_adc = means[active_channel];
  const float normalized = reference > 0.0f ? main_adc / reference : 0.0f;
  const float delta_od = normalized > 0.0f ? -log10f(normalized) : NAN;

  uart_write_str("CSV,tracking.csv,");
  uart_write_u32(timestamp_ms);
  uart_write_char(',');
  uart_write_u32(cycle);
  uart_write_char(',');
  uart_write_u32(active_channel);
  uart_write_char(',');
  uart_write_u32(calibration[active_channel].tracking_duty);
  uart_write_char(',');
  uart_write_float(reference, 2U);
  uart_write_char(',');
  uart_write_float(main_adc, 2U);
  uart_write_char(',');
  uart_write_float(normalized, 6U);
  uart_write_char(',');
  uart_write_float(delta_od, 6U);
  uart_write_char(',');
  uart_write_float(temperature_c, 2U);
  uart_write_char(',');
  uart_write_float(humidity_percent, 2U);
  write_channel_floats(means, 2U);
  uart_write_str("\r\n");
}

static bool is_better_linear_fit(const LinearRangeFit *candidate,
                                 const LinearRangeFit *current,
                                 const uint16_t sweep_duty[MAX_SWEEP_POINTS]) {
  if (!current->valid) {
    return true;
  }

  const int candidate_points = candidate->end_index - candidate->start_index + 1;
  const int current_points = current->end_index - current->start_index + 1;
  if (candidate_points != current_points) {
    return candidate_points > current_points;
  }

  const uint16_t candidate_span =
      sweep_duty[candidate->end_index] - sweep_duty[candidate->start_index];
  const uint16_t current_span =
      sweep_duty[current->end_index] - sweep_duty[current->start_index];
  if (candidate_span != current_span) {
    return candidate_span > current_span;
  }

  if (candidate->r_squared != current->r_squared) {
    return candidate->r_squared > current->r_squared;
  }

  return candidate->residual_fraction < current->residual_fraction;
}

static LinearRangeFit find_linear_range(const uint16_t sweep_duty[MAX_SWEEP_POINTS],
                                        const float sweep_main_adc[MAX_SWEEP_POINTS],
                                        int points) {
  float prefix_x[MAX_SWEEP_POINTS + 1U] = {0.0f};
  float prefix_y[MAX_SWEEP_POINTS + 1U] = {0.0f};
  float prefix_xx[MAX_SWEEP_POINTS + 1U] = {0.0f};
  float prefix_yy[MAX_SWEEP_POINTS + 1U] = {0.0f};
  float prefix_xy[MAX_SWEEP_POINTS + 1U] = {0.0f};

  for (int i = 0; i < points; i++) {
    const float x = (float)sweep_duty[i];
    const float y = sweep_main_adc[i];
    prefix_x[i + 1] = prefix_x[i] + x;
    prefix_y[i + 1] = prefix_y[i] + y;
    prefix_xx[i + 1] = prefix_xx[i] + (x * x);
    prefix_yy[i + 1] = prefix_yy[i] + (y * y);
    prefix_xy[i + 1] = prefix_xy[i] + (x * y);
  }

  LinearRangeFit best_valid = {0};
  LinearRangeFit best_fallback = {0};

  for (int start = 0; start <= points - MIN_LINEAR_POINTS; start++) {
    for (int end = start + MIN_LINEAR_POINTS - 1; end < points; end++) {
      const int count = end - start + 1;
      const float sum_x = prefix_x[end + 1] - prefix_x[start];
      const float sum_y = prefix_y[end + 1] - prefix_y[start];
      const float sum_xx = prefix_xx[end + 1] - prefix_xx[start];
      const float sum_yy = prefix_yy[end + 1] - prefix_yy[start];
      const float sum_xy = prefix_xy[end + 1] - prefix_xy[start];

      const float denominator = ((float)count * sum_xx) - (sum_x * sum_x);
      if (fabsf(denominator) < 1e-6f) {
        continue;
      }

      const float slope = (((float)count * sum_xy) - (sum_x * sum_y)) / denominator;
      if (slope <= 0.0f) {
        continue;
      }

      const float intercept = (sum_y - (slope * sum_x)) / (float)count;
      const float sse = sum_yy + (slope * slope * sum_xx) +
                        ((float)count * intercept * intercept) -
                        (2.0f * slope * sum_xy) -
                        (2.0f * intercept * sum_y) +
                        (2.0f * slope * intercept * sum_x);
      const float sst = sum_yy - ((sum_y * sum_y) / (float)count);
      const float r_squared = sst <= 1e-6f ? 1.0f : 1.0f - (fmaxf(sse, 0.0f) / sst);

      float min_adc = sweep_main_adc[start];
      float max_adc = sweep_main_adc[start];
      float max_residual = 0.0f;
      for (int i = start; i <= end; i++) {
        const float adc = sweep_main_adc[i];
        if (adc < min_adc) {
          min_adc = adc;
        }
        if (adc > max_adc) {
          max_adc = adc;
        }

        const float fit_adc = (slope * (float)sweep_duty[i]) + intercept;
        const float residual = fabsf(adc - fit_adc);
        if (residual > max_residual) {
          max_residual = residual;
        }
      }

      const float adc_span = max_adc - min_adc;
      if (adc_span <= 1.0f) {
        continue;
      }

      const float residual_fraction = max_residual / adc_span;
      const float first_slope =
          (sweep_main_adc[start + 1] - sweep_main_adc[start]) /
          (float)(sweep_duty[start + 1] - sweep_duty[start]);
      const float last_slope =
          (sweep_main_adc[end] - sweep_main_adc[end - 1]) /
          (float)(sweep_duty[end] - sweep_duty[end - 1]);

      LinearRangeFit candidate = {
          .start_index = start,
          .end_index = end,
          .slope = slope,
          .intercept = intercept,
          .r_squared = r_squared,
          .residual_fraction = residual_fraction,
          .valid = true,
          .fallback_used = false,
      };

      if (is_better_linear_fit(&candidate, &best_fallback, sweep_duty)) {
        best_fallback = candidate;
      }

      const bool matches_linear_shape =
          r_squared >= MIN_LINEAR_R_SQUARED &&
          residual_fraction <= MAX_LINEAR_RESIDUAL_FRACTION &&
          first_slope >= (slope * MIN_EDGE_SLOPE_RATIO) &&
          last_slope >= (slope * MIN_EDGE_SLOPE_RATIO);
      if (matches_linear_shape &&
          is_better_linear_fit(&candidate, &best_valid, sweep_duty)) {
        best_valid = candidate;
      }
    }
  }

  if (best_valid.valid) {
    return best_valid;
  }

  if (best_fallback.valid) {
    best_fallback.fallback_used = true;
    return best_fallback;
  }

  LinearRangeFit fallback = {0};
  fallback.start_index = 0;
  fallback.end_index = points - 1;
  fallback.valid = true;
  fallback.fallback_used = true;

  if (points >= 2) {
    const float delta_duty = (float)(sweep_duty[points - 1] - sweep_duty[0]);
    fallback.slope = delta_duty > 0.0f
                         ? (sweep_main_adc[points - 1] - sweep_main_adc[0]) / delta_duty
                         : 0.0f;
    fallback.intercept = sweep_main_adc[0] - (fallback.slope * (float)sweep_duty[0]);
  } else {
    fallback.slope = 0.0f;
    fallback.intercept = sweep_main_adc[0];
  }

  return fallback;
}

static bool is_noisy_pwm_duty_from_sweep(const float sweep_main_adc[MAX_SWEEP_POINTS],
                                         int points, int index) {
  if (index <= 0 || index >= points - 1) {
    return false;
  }

  const float expected_from_neighbors =
      (sweep_main_adc[index - 1] + sweep_main_adc[index + 1]) * 0.5f;
  const float dip = expected_from_neighbors - sweep_main_adc[index];
  const float required_dip =
      fmaxf(PWM_NOISE_MIN_DROP_ADC,
            expected_from_neighbors * PWM_NOISE_MIN_DROP_FRACTION);
  return dip >= required_dip;
}

static bool is_duty_in_noisy_pwm_band(uint16_t duty,
                                      const uint16_t sweep_duty[MAX_SWEEP_POINTS],
                                      const float sweep_main_adc[MAX_SWEEP_POINTS],
                                      int points) {
  for (int i = 1; i < points - 1; i++) {
    if (!is_noisy_pwm_duty_from_sweep(sweep_main_adc, points, i)) {
      continue;
    }

    const uint16_t distance = duty > sweep_duty[i] ? duty - sweep_duty[i]
                                                   : sweep_duty[i] - duty;
    if (distance <= PWM_NOISE_DUTY_GUARD) {
      return true;
    }
  }

  return false;
}

static int find_closest_sweep_index_to_target(
    const uint16_t sweep_duty[MAX_SWEEP_POINTS],
    const float sweep_main_adc[MAX_SWEEP_POINTS],
    int start_index,
    int end_index,
    float target_adc) {
  (void)sweep_duty;
  int best_index = start_index;
  float best_error = fabsf(sweep_main_adc[start_index] - target_adc);

  for (int i = start_index + 1; i <= end_index; i++) {
    const float current_error = fabsf(sweep_main_adc[i] - target_adc);
    if (current_error < best_error) {
      best_error = current_error;
      best_index = i;
    }
  }

  return best_index;
}

static bool pair_is_enabled(uint8_t active_channel) {
  return adc_inputs[active_channel].enabled &&
         tlc_output_for_pair[active_channel] != TLC_OUTPUT_DISABLED;
}

static CalibrationResult calibrate_one_pair(uint8_t active_channel) {
  uint16_t sweep_duty[MAX_SWEEP_POINTS];
  float sweep_main_adc[MAX_SWEEP_POINTS];
  float means[NUM_CHANNELS];
  int points = 0;
  uint16_t next_progress_duty = 0U;

  CalibrationResult result = {0};
  result.peak_adc = -1.0f;

  if (!pair_is_enabled(active_channel)) {
    for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
      means[ch] = 0.0f;
    }

    status("pair disabled; leaving LED off and ADC at zero");
    write_calibration_sweep_row(active_channel, 0U, means);

    result.peak_adc = 0.0f;
    result.linear_start_adc = 0.0f;
    result.linear_end_adc = 0.0f;
    result.fit_r_squared = 0.0f;
    result.sweep_points = 1;
    write_calibration_summary_row(active_channel, &result);
    return result;
  }

  all_leds_off();
  delay_ms(BETWEEN_LED_MS);

  for (uint16_t duty = 0U;;) {
    if (duty >= next_progress_duty || duty == 0U || duty == PWM_MAX) {
      uart_write_str("STATUS: calibrating pair ");
      uart_write_u32((uint32_t)active_channel + 1U);
      uart_write_char('/');
      uart_write_u32(NUM_CHANNELS);
      uart_write_str(", pwm=");
      uart_write_u32(duty);
      uart_write_str("\r\n");

      const uint32_t next_duty = (uint32_t)duty + 8192U;
      next_progress_duty = next_duty > PWM_MAX ? PWM_MAX : (uint16_t)next_duty;
    }

    set_active_pair(active_channel, duty);
    measure_current_calibration_pwm_to_all_channels(CALIBRATION_REPEATS, means);
    write_calibration_sweep_row(active_channel, duty, means);

    sweep_duty[points] = duty;
    sweep_main_adc[points] = means[active_channel];
    points++;

    if (means[active_channel] > result.peak_adc) {
      result.peak_adc = means[active_channel];
      result.peak_duty = duty;
    }

    if (means[active_channel] >= ADC_LIMIT) {
      result.limit_reached = true;
      break;
    }

    if (duty == PWM_MAX || points >= (int)MAX_SWEEP_POINTS) {
      break;
    }

    const uint32_t next_duty = (uint32_t)duty + CALIBRATION_DUTY_STEP;
    duty = next_duty > PWM_MAX ? PWM_MAX : (uint16_t)next_duty;
  }

  all_leds_off();
  delay_ms(BETWEEN_LED_MS);

  LinearRangeFit fit = find_linear_range(sweep_duty, sweep_main_adc, points);
  result.linear_start_duty = sweep_duty[fit.start_index];
  result.linear_end_duty = sweep_duty[fit.end_index];
  result.linear_start_adc = (fit.slope * (float)result.linear_start_duty) + fit.intercept;
  result.linear_end_adc = (fit.slope * (float)result.linear_end_duty) + fit.intercept;
  result.fit_slope = fit.slope;
  result.fit_intercept = fit.intercept;
  result.fit_r_squared = fit.r_squared;
  result.fallback_fit = fit.fallback_used;
  result.sweep_points = points;

  float usable_max_adc = result.linear_end_adc;
  if (result.peak_adc > 0.0f &&
      (usable_max_adc <= 0.0f || usable_max_adc > result.peak_adc)) {
    usable_max_adc = result.peak_adc;
  }

  float selected_fraction = TRACKING_FRACTION_OF_MAX;
  int selected_index = find_closest_sweep_index_to_target(
      sweep_duty, sweep_main_adc, fit.start_index, fit.end_index,
      usable_max_adc * selected_fraction);

  for (float fraction = TRACKING_FRACTION_OF_MAX;
       fraction >= MIN_TRACKING_FRACTION_OF_MAX - 0.001f;
       fraction -= TRACKING_FRACTION_STEP) {
    const float target_adc = usable_max_adc * fraction;
    const int candidate_index = find_closest_sweep_index_to_target(
        sweep_duty, sweep_main_adc, fit.start_index, fit.end_index, target_adc);

    if (is_duty_in_noisy_pwm_band(sweep_duty[candidate_index],
                                  sweep_duty, sweep_main_adc, points)) {
      continue;
    }

    selected_fraction = fraction;
    selected_index = candidate_index;
    break;
  }

  if (is_duty_in_noisy_pwm_band(sweep_duty[selected_index],
                                sweep_duty, sweep_main_adc, points)) {
    for (int i = selected_index - 1; i >= fit.start_index; i--) {
      if (!is_duty_in_noisy_pwm_band(sweep_duty[i], sweep_duty,
                                     sweep_main_adc, points)) {
        selected_index = i;
        selected_fraction = usable_max_adc > 0.0f
                                ? sweep_main_adc[i] / usable_max_adc
                                : 0.0f;
        break;
      }
    }
  }

  result.target_adc = usable_max_adc * selected_fraction;
  result.tracking_duty = sweep_duty[selected_index];
  result.tracking_reference_adc = sweep_main_adc[selected_index];

  write_calibration_summary_row(active_channel, &result);
  return result;
}

static void run_calibration(void) {
  calibration_valid = false;
  calibration_loaded_mask = 0U;
  for (uint32_t channel = 0U; channel < NUM_CHANNELS; channel++) {
    uart_write_str("STATUS: calibrating pair ");
    uart_write_u32(channel + 1U);
    uart_write_char('/');
    uart_write_u32(NUM_CHANNELS);
    uart_write_str("\r\n");

    calibration[channel] = calibrate_one_pair((uint8_t)channel);

    uart_write_str("STATUS: calibration done on pair ");
    uart_write_u32(channel + 1U);
    uart_write_char('/');
    uart_write_u32(NUM_CHANNELS);
    uart_write_str(", tracking duty=");
    uart_write_u32(calibration[channel].tracking_duty);
    uart_write_str(", reference adc=");
    uart_write_float(calibration[channel].tracking_reference_adc, 2U);
    uart_write_str("\r\n");
  }
  calibration_valid = true;
  calibration_loaded_mask = (1UL << NUM_CHANNELS) - 1UL;
}

static void log_tracking_repeats(
    uint32_t timestamp_ms,
    uint32_t cycle,
    uint8_t active_channel,
    uint16_t duty,
    const uint16_t raw_samples[MAX_MEASUREMENT_REPEATS][NUM_CHANNELS]) {
  for (uint32_t repeat = 0U; repeat < TRACKING_REPEATS; repeat++) {
    write_tracking_repeats_row(timestamp_ms, cycle, active_channel, duty,
                               repeat, raw_samples[repeat]);
  }
}

static bool parse_u32_field(char **cursor, uint32_t *value) {
  char *end = NULL;
  const unsigned long parsed = strtoul(*cursor, &end, 10);
  if (end == *cursor) {
    return false;
  }

  *value = (uint32_t)parsed;
  *cursor = end;
  return true;
}

static bool consume_comma(char **cursor) {
  if (**cursor != ',') {
    return false;
  }

  (*cursor)++;
  return true;
}

static void clear_host_calibration(void) {
  memset(calibration, 0, sizeof(calibration));
  calibration_valid = false;
  calibration_loaded_mask = 0U;
  status("command accepted: LOADZERO");
}

static void restore_calibration_row(char *payload) {
  uint32_t led_index = 0U;
  uint32_t tracking_duty = 0U;
  uint32_t reference_adc_centi = 0U;
  char *cursor = payload;

  if (!parse_u32_field(&cursor, &led_index) || !consume_comma(&cursor) ||
      !parse_u32_field(&cursor, &tracking_duty) || !consume_comma(&cursor) ||
      !parse_u32_field(&cursor, &reference_adc_centi) || *cursor != '\0') {
    status("invalid LOADROW command");
    return;
  }

  if (led_index >= NUM_CHANNELS || tracking_duty > PWM_MAX ||
      reference_adc_centi > 409500U) {
    status("invalid LOADROW value");
    return;
  }

  CalibrationResult *result = &calibration[led_index];
  memset(result, 0, sizeof(*result));
  result->peak_duty = (uint16_t)tracking_duty;
  result->peak_adc = (float)reference_adc_centi / 100.0f;
  result->target_adc = result->peak_adc;
  result->tracking_duty = (uint16_t)tracking_duty;
  result->tracking_reference_adc = result->peak_adc;
  result->sweep_points = 1;

  calibration_loaded_mask |= (1UL << led_index);
  if (calibration_loaded_mask == ((1UL << NUM_CHANNELS) - 1UL)) {
    calibration_valid = true;
    status("calibration restored from host CSV");
  }
}

static void complete_command(const char *command) {
  if (strcmp(command, "C") == 0 ||
      strcmp(command, "RESET_CALIBRATE") == 0 ||
      strcmp(command, "CALIBRATE") == 0 ||
      strcmp(command, "RUN_CALIBRATE") == 0) {
    requested_action = ACTION_CALIBRATE;
    status("command accepted: RESET_CALIBRATE");
  } else if (strcmp(command, "U") == 0 ||
             strcmp(command, "REUSE_CALIBRATION") == 0 ||
             strcmp(command, "RESTART") == 0 ||
             strcmp(command, "RUN_REUSE") == 0) {
    requested_action = ACTION_REUSE_CALIBRATION;
    status("command accepted: REUSE_CALIBRATION");
  } else if (strcmp(command, "STATUS") == 0) {
    uart_write_str("STATUS: calibration_valid=");
    uart_write_u32(calibration_valid ? 1U : 0U);
    uart_write_str(", restored_rows=");
    uart_write_u32(__builtin_popcount(calibration_loaded_mask));
    uart_write_str("\r\n");
  } else if (strcmp(command, "LOADZERO") == 0) {
    clear_host_calibration();
  } else if (strncmp(command, "LOADROW,", 8U) == 0) {
    restore_calibration_row((char *)command + 8U);
  } else if (strcmp(command, "BOARD_RESET") == 0) {
    status("command accepted: BOARD_RESET");
    all_leds_off();
    delay_ms(10U);
    NVIC_SystemReset();
  } else if (command[0] != '\0') {
    uart_write_str("STATUS: unknown command: ");
    uart_write_str(command);
    uart_write_str("\r\n");
  }
}

static void poll_commands(void) {
  char c;
  while (uart_read_char(&c)) {
    if (c == 'C' && command_length == 0U) {
      requested_action = ACTION_CALIBRATE;
      command_length = 0U;
      status("command accepted: RESET_CALIBRATE");
      continue;
    }

    if (c == 'U' && command_length == 0U) {
      requested_action = ACTION_REUSE_CALIBRATION;
      command_length = 0U;
      status("command accepted: REUSE_CALIBRATION");
      continue;
    }

    if (c == '\r') {
      continue;
    }

    if (c == '\n') {
      command_buffer[command_length] = '\0';
      complete_command(command_buffer);
      command_length = 0U;
      continue;
    }

    if (command_length + 1U < sizeof(command_buffer)) {
      command_buffer[command_length++] = c;
    } else {
      command_length = 0U;
      status("command buffer overflow");
    }
  }
}

static RequestedAction take_requested_action(void) {
  poll_commands();
  RequestedAction action = requested_action;
  requested_action = ACTION_NONE;
  return action;
}

static RequestedAction wait_for_action(void) {
  while (1) {
    RequestedAction action = take_requested_action();
    if (action != ACTION_NONE) {
      return action;
    }
  }
}

static RequestedAction run_tracking_until_command(void) {
  uint32_t cycle = 0U;
  float means[NUM_CHANNELS];
  uint16_t raw_samples[MAX_MEASUREMENT_REPEATS][NUM_CHANNELS];

  status("tracking started");
  while (1) {
    float temperature_c = NAN;
    float humidity_percent = NAN;
    uart_write_str("STATUS: tracking cycle ");
    uart_write_u32(cycle);
    uart_write_str("\r\n");

    (void)aht_read(&temperature_c, &humidity_percent);

    for (uint32_t channel = 0U; channel < NUM_CHANNELS; channel++) {
      RequestedAction action = take_requested_action();
      if (action != ACTION_NONE) {
        return action;
      }

      measure_pair_to_all_channels((uint8_t)channel,
                                   calibration[channel].tracking_duty,
                                   TRACKING_REPEATS, means, raw_samples);

      const uint32_t timestamp_ms = millis();
      log_tracking_repeats(timestamp_ms, cycle, (uint8_t)channel,
                           calibration[channel].tracking_duty, raw_samples);
      write_tracking_row(timestamp_ms, cycle, (uint8_t)channel, means,
                         temperature_c, humidity_percent);
    }

    cycle++;
    status("tracking cycle complete; waiting 120 seconds");
    const uint32_t wait_start = millis();
    while ((millis() - wait_start) < BETWEEN_TRACKING_CYCLES_MS) {
      RequestedAction action = take_requested_action();
      if (action != ACTION_NONE) {
        return action;
      }
      delay_ms(10U);
    }
  }
}

int main(void) {
  clock_init_hsi16();
  dwt_init();
  SysTick_Config(SYSCLK_HZ / 1000UL);
  gpio_init();
  usart2_init();
  status("boot: USART2 ready");
  status("boot: AHT init starting");
  aht_init();
  status("boot: AHT init done");
  status("boot: ADC init starting");
  adc_init_all();
  status("boot: ADC init done");
  status("boot: TLC off starting");
  all_leds_off();
  status("boot: TLC off done");

  status("STM32G474RE ready; waiting for RESET_CALIBRATE or REUSE_CALIBRATION");

  RequestedAction action = wait_for_action();
  while (1) {
    write_all_headers();

    if (action == ACTION_CALIBRATE) {
      status("measurement state reset; calibration starting at pair 0");
      run_calibration();
    } else if (action == ACTION_REUSE_CALIBRATION && !calibration_valid) {
      status("no RAM calibration available; calibration starting at pair 0");
      run_calibration();
    } else {
      status("reusing RAM calibration; tracking restarting at pair 0");
    }

    action = run_tracking_until_command();
  }
}
