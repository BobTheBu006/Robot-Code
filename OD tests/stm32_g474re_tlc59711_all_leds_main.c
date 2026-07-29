/*
 * TLC59711 all-LEDs-on test for STM32 NUCLEO-G474RE.
 *
 * Pins:
 *   USART2 TX/RX: PA2/PA3, ST-LINK virtual COM port
 *   TLC59711 clock: PB6
 *   TLC59711 data:  PC7
 *
 * Behavior:
 *   Blinks all 24 logical TLC outputs together forever.
 */

#include "stm32g474xx.h"

#include <stdint.h>

#define SYSCLK_HZ 16000000UL
#define UART_BAUD 115200UL

#define NUM_TLC_BOARDS 2U
#define TLC_OUTPUTS_PER_BOARD 12U
#define NUM_TLC_OUTPUTS (NUM_TLC_BOARDS * TLC_OUTPUTS_PER_BOARD)
#define ALL_LED_PWM 8192U
#define ON_MS 700U
#define OFF_MS 700U

#define TLC_CLOCK_PORT GPIOB
#define TLC_CLOCK_PIN 6U
#define TLC_DATA_PORT GPIOC
#define TLC_DATA_PIN 7U

static uint16_t tlc_pwm[NUM_TLC_OUTPUTS];
static volatile uint32_t system_millis = 0;

static const uint8_t tlc_logical_output_for_board_channel[NUM_TLC_BOARDS][TLC_OUTPUTS_PER_BOARD] = {
    {0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20, 21},
    {2, 3, 6, 7, 10, 11, 14, 15, 18, 19, 22, 23},
};

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

static void all_leds_on(void) {
  for (uint32_t i = 0U; i < NUM_TLC_OUTPUTS; i++) {
    tlc_pwm[i] = ALL_LED_PWM;
  }
  tlc_write();
}

static void all_leds_off(void) {
  for (uint32_t i = 0U; i < NUM_TLC_OUTPUTS; i++) {
    tlc_pwm[i] = 0U;
  }
  tlc_write();
}

int main(void) {
  clock_init_hsi16();
  dwt_init();
  SysTick_Config(SYSCLK_HZ / 1000UL);
  gpio_init();

  while (1) {
    all_leds_on();
    delay_ms(ON_MS);
    all_leds_off();
    delay_ms(OFF_MS);
  }
}
