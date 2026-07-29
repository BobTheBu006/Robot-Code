/*
 * Quick TLC59711 daisy-chain LED output order test for STM32 NUCLEO-G474RE.
 *
 * Pins:
 *   USART2 TX/RX: PA2/PA3, ST-LINK virtual COM port
 *   TLC59711 clock: PB6
 *   TLC59711 data:  PC7
 *
 * Behavior:
 *   Repeats logical LED outputs 0..23 forever.
 *   One output turns on, its index is printed over serial, then it turns off.
 */

#include "stm32g474xx.h"

#include <stdint.h>

#define SYSCLK_HZ 16000000UL
#define UART_BAUD 115200UL

#define NUM_TLC_BOARDS 2U
#define TLC_OUTPUTS_PER_BOARD 12U
#define NUM_TLC_OUTPUTS (NUM_TLC_BOARDS * TLC_OUTPUTS_PER_BOARD)
#define NUM_CHANNELS 24U
#define TEST_PWM 32768U
#define ON_MS 700U
#define OFF_MS 250U

#define TLC_CLOCK_PORT GPIOB
#define TLC_CLOCK_PIN 6U
#define TLC_DATA_PORT GPIOC
#define TLC_DATA_PIN 7U

static volatile uint32_t system_millis = 0;
static uint16_t tlc_pwm[NUM_TLC_OUTPUTS];

static const uint8_t tlc_logical_output_for_board_channel[NUM_TLC_BOARDS][TLC_OUTPUTS_PER_BOARD] = {
    {0, 1, 4, 5, 8, 9, 12, 13, 16, 17, 20, 21},      /* board 1 */
    {2, 3, 6, 7, 10, 11, 14, 15, 18, 19, 22, 23},    /* board 2 */
};

static const char *logical_output_label[NUM_TLC_OUTPUTS] = {
    "board1,R0",
    "board1,G0",
    "board2,R0",
    "board2,G0",
    "board1,B0",
    "board1,R1",
    "board2,B0",
    "board2,R1",
    "board1,G1",
    "board1,B1",
    "board2,G1",
    "board2,B1",
    "board1,G3",
    "board1,B3",
    "board2,R2",
    "board2,G2",
    "board1,B2",
    "board1,R3",
    "board2,B2",
    "board2,R3",
    "board1,R2",
    "board1,G2",
    "board2,G3",
    "board2,B3",
};

static const uint8_t tlc_output_for_pair[NUM_CHANNELS] = {
    8,   /* pair 0:  PB11 with board 1 G1 */
    9,   /* pair 1:  PB12 with board 1 B1 */
    3,   /* pair 2:  PC2  with board 2 G0 */
    2,   /* pair 3:  PC3  with board 2 R0 */
    4,   /* pair 4:  PC5  with board 1 B0 */
    5,   /* pair 5:  PA7  with board 1 R1 */
    7,   /* pair 6:  PB15 with board 2 R1 */
    6,   /* pair 7:  PB14 with board 2 B0 */
    0,   /* pair 8:  PA9  with board 1 R0 */
    1,   /* pair 9:  PA8  with board 1 G0 */
    11,  /* pair 10: PB2  with board 2 B1 */
    10,  /* pair 11: PB1  with board 2 G1 */
    20,  /* pair 12: PC4  with board 1 R2 */
    21,  /* pair 13: PB13 with board 1 G2 */
    22,  /* pair 14: PC1  with board 2 G3 */
    23,  /* pair 15: PC0  with board 2 B3 */
    16,  /* pair 16: PA6  with board 1 B2 */
    17,  /* pair 17: PA5  with board 1 R3 */
    18,  /* pair 18: PA4  with board 2 B2 */
    19,  /* pair 19: PB0  with board 2 R3 */
    12,  /* pair 20: no ADC with board 1 G3 */
    13,  /* pair 21: no ADC with board 1 B3 */
    14,  /* pair 22: PA0  with board 2 R2 */
    15,  /* pair 23: PA1  with board 2 G2 */
};

static const char *pair_adc_label[NUM_CHANNELS] = {
    "PB11",
    "PB12",
    "PC2",
    "PC3",
    "PC5",
    "PA7",
    "PB15",
    "PB14",
    "PA9",
    "PA8",
    "PB2",
    "PB1",
    "PC4",
    "PB13",
    "PC1",
    "PC0",
    "PA6",
    "PA5",
    "PA4",
    "PB0",
    "OFF",
    "OFF",
    "PA0",
    "PA1",
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

static void set_one_led(uint32_t logical_output, uint16_t pwm) {
  for (uint32_t i = 0U; i < NUM_TLC_OUTPUTS; i++) {
    tlc_pwm[i] = 0U;
  }

  if (logical_output < NUM_TLC_OUTPUTS) {
    tlc_pwm[logical_output] = pwm;
  }
  tlc_write();
}

int main(void) {
  clock_init_hsi16();
  dwt_init();
  SysTick_Config(SYSCLK_HZ / 1000UL);
  gpio_init();
  usart2_init();

  all_leds_off();
  uart_write_str("STATUS: TLC59711 channel/pair LED test 0..23\r\n");
  uart_write_str("STATUS: clock=PB6 data=PC7 baud=115200\r\n");

  while (1) {
    for (uint32_t pair = 0U; pair < NUM_CHANNELS; pair++) {
      const uint8_t output = tlc_output_for_pair[pair];

      uart_write_str("PAIR_TEST,");
      uart_write_u32(pair);
      uart_write_str(",adc=");
      uart_write_str(pair_adc_label[pair]);
      uart_write_str(",output=");
      uart_write_u32(output);
      uart_write_char(',');
      uart_write_str(logical_output_label[output]);
      uart_write_str("\r\n");

      set_one_led(output, TEST_PWM);
      delay_ms(ON_MS);
      all_leds_off();
      delay_ms(OFF_MS);
    }
  }
}
