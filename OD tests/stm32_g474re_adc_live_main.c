/*
 * STM32 NUCLEO-G474RE bare-metal live ADC stream.
 *
 * No LED driver, no calibration, no commands. Reads the configured ADC channels
 * once per second and prints:
 *   CSV,adc_live.csv,timestamp_ms,ch0_pb11,...,ch23_pa1
 *   CSV,adc_live.csv,<millis>,<adc0>,...,<adc23>
 *
 * USART2 TX/RX: PA2/PA3 through ST-LINK virtual COM port.
 */

#include "stm32g474xx.h"

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define SYSCLK_HZ 16000000UL
#define UART_BAUD 115200UL

#define NUM_CHANNELS 24U
#define ADC_SAMPLES 8U
#define BETWEEN_ADC_US 50U
#define STREAM_INTERVAL_MS 100U

typedef struct {
  ADC_TypeDef *adc;
  uint8_t channel;
  bool enabled;
} AdcInput;

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
    {ADC5, 1, true},    /* ch9  PA8 ADC5_IN1 */
    {ADC2, 12, true},   /* ch10 PB2 ADC2_IN12 */
    {ADC1, 12, true},   /* ch11 PB1 ADC1_IN12 */
    {ADC2, 5, true},    /* ch12 PC4 ADC2_IN5 */
    {ADC3, 5, true},    /* ch13 PB13 ADC3_IN5 */
    {ADC1, 7, true},    /* ch14 PC1 ADC1_IN7 */
    {ADC1, 6, true},    /* ch15 PC0 ADC1_IN6 */
    {ADC2, 3, true},    /* ch16 PA6 ADC2_IN3 */
    {ADC2, 13, true},   /* ch17 PA5 ADC2_IN13 */
    {ADC2, 17, true},   /* ch18 PA4 ADC2_IN17 */
    {ADC1, 15, true},   /* ch19 PB0 ADC1_IN15 */
    {NULL, 0, false},   /* ch20 off, no ADC */
    {NULL, 0, false},   /* ch21 off, no ADC */
    {ADC1, 1, true},    /* ch22 PA0 ADC1_IN1 */
    {ADC1, 2, true},    /* ch23 PA1 ADC1_IN2 */
};

static const char *channel_columns[NUM_CHANNELS] = {
    "ch0_pb11",  "ch1_pb12",  "ch2_pc2",  "ch3_pc3",
    "ch4_pc5",   "ch5_pa7",   "ch6_pb15", "ch7_pb14",
    "ch8_pa9",   "ch9_pa8",   "ch10_pb2", "ch11_pb1",
    "ch12_pc4",  "ch13_pb13", "ch14_pc1", "ch15_pc0",
    "ch16_pa6",  "ch17_pa5",  "ch18_pa4", "ch19_pb0",
    "ch20_off",  "ch21_off",  "ch22_pa0", "ch23_pa1",
};

static volatile uint32_t system_millis = 0U;

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
  DWT->CYCCNT = 0U;
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
                      ADC_CCR_CKMODE_0;
  ADC345_COMMON->CCR = (ADC345_COMMON->CCR & ~ADC_CCR_CKMODE) |
                       ADC_CCR_CKMODE_0;

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

static void write_header(void) {
  uart_write_str("CSV,adc_live.csv,timestamp_ms");
  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    uart_write_char(',');
    uart_write_str(channel_columns[ch]);
  }
  uart_write_str("\r\n");
}

static void write_adc_row(void) {
  uart_write_str("CSV,adc_live.csv,");
  uart_write_u32(millis());

  for (uint32_t ch = 0U; ch < NUM_CHANNELS; ch++) {
    uart_write_char(',');
    uart_write_u32(adc_read_average(ch));
  }

  uart_write_str("\r\n");
}

int main(void) {
  clock_init_hsi16();
  dwt_init();
  SysTick_Config(SYSCLK_HZ / 1000UL);
  gpio_init();
  usart2_init();
  adc_init_all();

  uart_write_str("STATUS: STM32G474RE ADC live stream ready\r\n");
  write_header();

  while (true) {
    const uint32_t started_at = millis();
    write_adc_row();
    const uint32_t elapsed = millis() - started_at;
    if (elapsed < STREAM_INTERVAL_MS) {
      delay_ms(STREAM_INTERVAL_MS - elapsed);
    }
  }
}
