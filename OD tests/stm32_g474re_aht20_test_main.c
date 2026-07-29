/*
 * AHT20 temperature/humidity serial test for STM32 NUCLEO-G474RE.
 *
 * Wiring used here:
 *   AHT20 SDA -> PB8
 *   AHT20 SCL -> PB9
 *   AHT20 VCC -> 3V3
 *   AHT20 GND -> GND
 *
 * Serial:
 *   USART2 PA2/PA3 through ST-LINK VCP, 115200 baud.
 */

#include "stm32g474xx.h"

#include <stdbool.h>
#include <stdint.h>

#define SYSCLK_HZ 16000000UL
#define UART_BAUD 115200UL

#define AHT_SDA_PORT GPIOB
#define AHT_SDA_PIN 8U
#define AHT_SCL_PORT GPIOB
#define AHT_SCL_PIN 9U
#define AHT_I2C_ADDRESS 0x38U
#define AHT_I2C_DELAY_US 5U

static volatile uint32_t system_millis = 0;

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

static void gpio_init(void) {
  RCC->AHB2ENR |= RCC_AHB2ENR_GPIOAEN | RCC_AHB2ENR_GPIOBEN;
  (void)RCC->AHB2ENR;

  gpio_set_mode(GPIOA, 2U, 0x2UL);
  gpio_set_mode(GPIOA, 3U, 0x2UL);
  gpio_set_af(GPIOA, 2U, 7U);
  gpio_set_af(GPIOA, 3U, 7U);
  GPIOA->OSPEEDR |= (0x3UL << (2U * 2U)) | (0x3UL << (3U * 2U));
  GPIOA->PUPDR &= ~((0x3UL << (2U * 2U)) | (0x3UL << (3U * 2U)));

  gpio_make_input(AHT_SDA_PORT, AHT_SDA_PIN);
  gpio_make_input(AHT_SCL_PORT, AHT_SCL_PIN);
}

static void usart2_init(void) {
  RCC->APB1ENR1 |= RCC_APB1ENR1_USART2EN;
  (void)RCC->APB1ENR1;

  USART2->CR1 = 0U;
  USART2->BRR = (SYSCLK_HZ + (UART_BAUD / 2UL)) / UART_BAUD;
  USART2->CR1 = USART_CR1_TE | USART_CR1_UE;
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
  if (value < 0.0f) {
    uart_write_char('-');
    value = -value;
  }

  uint32_t scale = 1U;
  for (uint8_t i = 0U; i < decimals; i++) {
    scale *= 10U;
  }

  uint32_t integer = (uint32_t)value;
  uint32_t fractional = (uint32_t)(((value - (float)integer) * (float)scale) + 0.5f);
  if (fractional >= scale) {
    integer++;
    fractional -= scale;
  }

  uart_write_u32(integer);
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

int main(void) {
  clock_init_hsi16();
  dwt_init();
  SysTick_Config(SYSCLK_HZ / 1000UL);
  gpio_init();
  usart2_init();

  uart_write_str("AHT20 test on PB8=SDA PB9=SCL\r\n");
  aht_init();

  while (1) {
    float temperature_c = 0.0f;
    float humidity_percent = 0.0f;

    if (aht_read(&temperature_c, &humidity_percent)) {
      uart_write_str("temperature_c,");
      uart_write_float(temperature_c, 2U);
      uart_write_str(",humidity_percent,");
      uart_write_float(humidity_percent, 2U);
      uart_write_str("\r\n");
    } else {
      uart_write_str("AHT20 read failed\r\n");
    }

    delay_ms(2000U);
  }
}
