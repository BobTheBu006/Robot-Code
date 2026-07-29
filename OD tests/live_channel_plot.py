#!/usr/bin/env python3
"""
Live plot STM32 ADC rows from the serial port.

Example:
  /home/robot/Downloads/.venv/bin/python /home/robot/Downloads/live_channel_plot.py /dev/ttyACM0

The ADC-live board firmware streams once per second without any command:
  cd /home/robot/Downloads
  make flash-adc-live
  /home/robot/Downloads/.venv/bin/python /home/robot/Downloads/live_channel_plot.py /dev/ttyACM0
"""

import argparse
import re
import time
from collections import deque

import matplotlib.pyplot as plt
import serial


CHANNEL_COLUMNS = [
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
]

TRACKING_PREFIX = "CSV,tracking.csv,"
ADC_LIVE_PREFIX = "CSV,adc_live.csv,"
TRACKING_HEADER = (
    "timestamp_ms,cycle,led_index,duty,reference_adc,main_adc,normalized,delta_od,"
    "temperature_c,humidity_percent,"
    + ",".join(CHANNEL_COLUMNS)
)
ADC_LIVE_HEADER = "timestamp_ms," + ",".join(CHANNEL_COLUMNS)
TRACKING_FIELD_COUNT = len(TRACKING_HEADER.split(","))
ADC_LIVE_FIELD_COUNT = len(ADC_LIVE_HEADER.split(","))
LEGACY_SWEEP_FIELD_COUNT = 2 + len(CHANNEL_COLUMNS)


def parse_args():
    parser = argparse.ArgumentParser(description="Live plot all ADC channels from STM32 serial CSV rows.")
    parser.add_argument("port", help="Serial port, for example /dev/ttyACM0")
    parser.add_argument("--baud", type=int, default=115200, help="Serial baud rate. Default: 115200")
    parser.add_argument("--window", type=int, default=200, help="Number of recent samples to keep. Default: 200")
    parser.add_argument("--interval-ms", type=int, default=50, help="Plot refresh interval. Default: 50 ms")
    parser.add_argument("--ylim", type=int, nargs=2, default=(0, 4095), metavar=("MIN", "MAX"))
    parser.add_argument(
        "--reuse-calibration",
        action="store_true",
        help="Send REUSE_CALIBRATION to the board before plotting.",
    )
    parser.add_argument(
        "--reset-calibrate",
        action="store_true",
        help="Send RESET_CALIBRATE to the board before plotting.",
    )
    parser.add_argument(
        "--listen-only",
        action="store_true",
        help="Do not send a command to the board. This is the default unless --reuse-calibration or --reset-calibrate is used.",
    )
    return parser.parse_args()


def command_payload(command):
    if command == "RESET_CALIBRATE":
        return b"C"
    if command == "REUSE_CALIBRATION":
        return b"U"
    return command.encode("ascii") + b"\n"


def channel_number(column):
    match = re.match(r"ch(\d+)(?:_|$)", column)
    return int(match.group(1)) if match else None


def parse_tracking_row(line):
    if not line.startswith(TRACKING_PREFIX):
        return None

    payload = line[len(TRACKING_PREFIX):]
    if payload == TRACKING_HEADER:
        return None

    fields = payload.split(",")
    if len(fields) != TRACKING_FIELD_COUNT:
        return None

    try:
        cycle = int(fields[1])
        led_index = int(fields[2])
        values = [float(value) for value in fields[-len(CHANNEL_COLUMNS):]]
    except ValueError:
        return None

    return cycle, led_index, values


def parse_adc_live_row(line):
    if not line.startswith(ADC_LIVE_PREFIX):
        return None

    payload = line[len(ADC_LIVE_PREFIX):]
    if payload == ADC_LIVE_HEADER:
        return None

    fields = payload.split(",")
    if len(fields) != ADC_LIVE_FIELD_COUNT:
        return None

    try:
        timestamp_ms = int(fields[0])
        values = [float(value) for value in fields[1:]]
    except ValueError:
        return None

    return timestamp_ms, None, values


def parse_legacy_sweep_row(line):
    fields = line.split(",")
    if len(fields) != LEGACY_SWEEP_FIELD_COUNT:
        return None

    try:
        led_index = int(fields[0])
        values = [float(value) for value in fields[2:]]
    except ValueError:
        return None

    if not (0 <= led_index < len(CHANNEL_COLUMNS)):
        return None

    return None, led_index, values


def make_plot(window, ylim):
    fig, ax = plt.subplots(figsize=(13.5, 7.5))
    lines = []

    cmap = plt.get_cmap("tab20")
    for index, column in enumerate(CHANNEL_COLUMNS):
        channel = channel_number(column)
        label = f"ch{channel} {column.split('_', 1)[1].upper()}"
        (line,) = ax.plot(
            [],
            [],
            linewidth=1.8,
            color=cmap(index % cmap.N),
            label=label,
        )
        lines.append(line)

    ax.set_title("Live ADC channels")
    ax.set_xlabel("Sample")
    ax.set_ylabel("Raw ADC count")
    ax.set_ylim(*ylim)
    ax.set_xlim(0, max(1, window - 1))
    ax.grid(True, linewidth=0.6, color="0.85")
    ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.11),
        ncol=6,
        frameon=False,
        fontsize=8,
    )
    status_text = fig.text(
        0.01,
        0.01,
        "Waiting for serial data",
        ha="left",
        va="bottom",
        fontsize=9,
        family="monospace",
    )
    fig.tight_layout(rect=(0, 0.08, 1, 1))
    return fig, ax, lines, status_text


def main():
    args = parse_args()
    if sum([args.reuse_calibration, args.reset_calibrate, args.listen_only]) > 1:
        raise SystemExit("Use only one of --reuse-calibration, --reset-calibrate, or --listen-only.")

    command = None
    if args.reuse_calibration:
        command = "REUSE_CALIBRATION"
    elif args.reset_calibrate:
        command = "RESET_CALIBRATE"

    sample_numbers = deque(maxlen=args.window)
    samples = [deque(maxlen=args.window) for _ in CHANNEL_COLUMNS]
    fig, ax, lines, status_text = make_plot(args.window, args.ylim)
    plt.ion()
    plt.show(block=False)

    print(f"Listening on {args.port} at {args.baud} baud")
    if command:
        print(f"Board command: {command}")
    else:
        print("Board command: disabled")

    with serial.Serial(args.port, args.baud, timeout=0.05) as ser:
        if command:
            time.sleep(0.25)
            ser.write(command_payload(command))
            ser.flush()

        last_draw = 0.0
        last_status = 0.0
        row_count = 0
        sample = 0
        last_serial_line = "Waiting for serial data"

        while plt.fignum_exists(fig.number):
            raw = ser.readline()
            if raw:
                line = raw.decode("utf-8", errors="replace").strip()
                parsed = (
                    parse_adc_live_row(line)
                    or parse_tracking_row(line)
                    or parse_legacy_sweep_row(line)
                )

                if parsed is not None:
                    cycle, led_index, values = parsed
                    sample += 1
                    sample_numbers.append(sample)
                    for channel_samples, value in zip(samples, values):
                        channel_samples.append(value)
                    row_count += 1
                    last_serial_line = line

                    now = time.monotonic()
                    if now - last_status >= 2.0:
                        if led_index is None:
                            print(f"Rows: {row_count}, latest timestamp {cycle} ms")
                        else:
                            cycle_text = "?" if cycle is None else str(cycle)
                            print(f"Rows: {row_count}, latest cycle {cycle_text}, led {led_index}")
                        last_status = now
                elif line and not line.startswith("CSV,"):
                    print(f"[board] {line}")

            now = time.monotonic()
            if now - last_draw >= args.interval_ms / 1000:
                for line, channel_samples in zip(lines, samples):
                    y_values = list(channel_samples)
                    x_values = list(sample_numbers)[-len(y_values):]
                    line.set_data(x_values, y_values)

                if sample_numbers:
                    right = max(args.window, sample_numbers[-1])
                    left = max(0, right - args.window + 1)
                    ax.set_xlim(left, right)
                status_text.set_text(last_serial_line[:220])

                fig.canvas.draw_idle()
                plt.pause(0.001)
                last_draw = now


if __name__ == "__main__":
    main()
