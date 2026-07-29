PROJECT := stm32_g474re_tlc59711
LED_TEST_PROJECT := stm32_g474re_tlc59711_led_test
ALL_LEDS_PROJECT := stm32_g474re_tlc59711_all_leds
AHT20_TEST_PROJECT := stm32_g474re_aht20_test
ADC_LIVE_PROJECT := stm32_g474re_adc_live
BUILD_DIR := build

CMSIS_CORE := STM32CubeG4/Drivers/CMSIS/Core/Include
CMSIS_DEVICE := STM32CubeG4/Drivers/CMSIS/Device/ST/STM32G4xx/Include

CC := arm-none-eabi-gcc
OBJCOPY := arm-none-eabi-objcopy
SIZE := arm-none-eabi-size

CFLAGS := \
	-mcpu=cortex-m4 \
	-mthumb \
	-std=c11 \
	-O2 \
	-g3 \
	-ffunction-sections \
	-fdata-sections \
	-Wall \
	-Wextra \
	-Werror \
	-DSTM32G474xx \
	-I$(CMSIS_CORE) \
	-I$(CMSIS_DEVICE)

LDFLAGS_COMMON := \
	-mcpu=cortex-m4 \
	-mthumb \
	-Tstm32_g474re.ld \
	-Wl,--gc-sections \
	--specs=nosys.specs

LDFLAGS := \
	$(LDFLAGS_COMMON) \
	-Wl,-Map=$(BUILD_DIR)/$(PROJECT).map

LED_TEST_LDFLAGS := \
	$(LDFLAGS_COMMON) \
	-Wl,-Map=$(BUILD_DIR)/$(LED_TEST_PROJECT).map

ALL_LEDS_LDFLAGS := \
	$(LDFLAGS_COMMON) \
	-Wl,-Map=$(BUILD_DIR)/$(ALL_LEDS_PROJECT).map

AHT20_TEST_LDFLAGS := \
	$(LDFLAGS_COMMON) \
	-Wl,-Map=$(BUILD_DIR)/$(AHT20_TEST_PROJECT).map

ADC_LIVE_LDFLAGS := \
	$(LDFLAGS_COMMON) \
	-Wl,-Map=$(BUILD_DIR)/$(ADC_LIVE_PROJECT).map

LDLIBS := -lm

SOURCES := stm32_g474re_startup.c stm32_g474re_tlc59711_sweep_main.c stm32_nosys.c
OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(SOURCES))
LED_TEST_SOURCES := stm32_g474re_startup.c stm32_g474re_tlc59711_led_test_main.c stm32_nosys.c
LED_TEST_OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(LED_TEST_SOURCES))
ALL_LEDS_SOURCES := stm32_g474re_startup.c stm32_g474re_tlc59711_all_leds_main.c stm32_nosys.c
ALL_LEDS_OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(ALL_LEDS_SOURCES))
AHT20_TEST_SOURCES := stm32_g474re_startup.c stm32_g474re_aht20_test_main.c stm32_nosys.c
AHT20_TEST_OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(AHT20_TEST_SOURCES))
ADC_LIVE_SOURCES := stm32_g474re_startup.c stm32_g474re_adc_live_main.c stm32_nosys.c
ADC_LIVE_OBJECTS := $(patsubst %.c,$(BUILD_DIR)/%.o,$(ADC_LIVE_SOURCES))

.PHONY: all clean flash led-test flash-led-test all-leds flash-all-leds aht20-test flash-aht20-test adc-live flash-adc-live

all: $(BUILD_DIR)/$(PROJECT).bin

$(BUILD_DIR):
	mkdir -p $@

$(BUILD_DIR)/%.o: %.c | $(BUILD_DIR)
	$(CC) $(CFLAGS) -c $< -o $@

$(BUILD_DIR)/$(PROJECT).elf: $(OBJECTS)
	$(CC) $(LDFLAGS) $(OBJECTS) $(LDLIBS) -o $@
	$(SIZE) $@

$(BUILD_DIR)/$(PROJECT).bin: $(BUILD_DIR)/$(PROJECT).elf
	$(OBJCOPY) -O binary $< $@

$(BUILD_DIR)/$(LED_TEST_PROJECT).elf: $(LED_TEST_OBJECTS)
	$(CC) $(LED_TEST_LDFLAGS) $(LED_TEST_OBJECTS) $(LDLIBS) -o $@
	$(SIZE) $@

$(BUILD_DIR)/$(LED_TEST_PROJECT).bin: $(BUILD_DIR)/$(LED_TEST_PROJECT).elf
	$(OBJCOPY) -O binary $< $@

led-test: $(BUILD_DIR)/$(LED_TEST_PROJECT).bin

$(BUILD_DIR)/$(ALL_LEDS_PROJECT).elf: $(ALL_LEDS_OBJECTS)
	$(CC) $(ALL_LEDS_LDFLAGS) $(ALL_LEDS_OBJECTS) $(LDLIBS) -o $@
	$(SIZE) $@

$(BUILD_DIR)/$(ALL_LEDS_PROJECT).bin: $(BUILD_DIR)/$(ALL_LEDS_PROJECT).elf
	$(OBJCOPY) -O binary $< $@

all-leds: $(BUILD_DIR)/$(ALL_LEDS_PROJECT).bin

$(BUILD_DIR)/$(AHT20_TEST_PROJECT).elf: $(AHT20_TEST_OBJECTS)
	$(CC) $(AHT20_TEST_LDFLAGS) $(AHT20_TEST_OBJECTS) $(LDLIBS) -o $@
	$(SIZE) $@

$(BUILD_DIR)/$(AHT20_TEST_PROJECT).bin: $(BUILD_DIR)/$(AHT20_TEST_PROJECT).elf
	$(OBJCOPY) -O binary $< $@

aht20-test: $(BUILD_DIR)/$(AHT20_TEST_PROJECT).bin

$(BUILD_DIR)/$(ADC_LIVE_PROJECT).elf: $(ADC_LIVE_OBJECTS)
	$(CC) $(ADC_LIVE_LDFLAGS) $(ADC_LIVE_OBJECTS) $(LDLIBS) -o $@
	$(SIZE) $@

$(BUILD_DIR)/$(ADC_LIVE_PROJECT).bin: $(BUILD_DIR)/$(ADC_LIVE_PROJECT).elf
	$(OBJCOPY) -O binary $< $@

adc-live: $(BUILD_DIR)/$(ADC_LIVE_PROJECT).bin

flash: $(BUILD_DIR)/$(PROJECT).bin
	st-flash write $< 0x08000000

flash-led-test: $(BUILD_DIR)/$(LED_TEST_PROJECT).bin
	st-flash write $< 0x08000000

flash-all-leds: $(BUILD_DIR)/$(ALL_LEDS_PROJECT).bin
	st-flash write $< 0x08000000

flash-aht20-test: $(BUILD_DIR)/$(AHT20_TEST_PROJECT).bin
	st-flash write $< 0x08000000

flash-adc-live: $(BUILD_DIR)/$(ADC_LIVE_PROJECT).bin
	st-flash write $< 0x08000000

clean:
	rm -rf $(BUILD_DIR)
