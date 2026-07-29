#!/usr/bin/env python3
# STM32 NUCLEO-G474RE / ST-LINK VCP example:
#   /home/robot/Downloads/.venv/bin/python /home/robot/Downloads/serial_csv_logger.py /dev/ttyACM0 --outdir /home/robot/Downloads/serial_logs
# start the looging and calibrate: /home/robot/Downloads/.venv/bin/python /home/robot/Downloads/serial_csv_logger.py /dev/ttyACM0 --outdir /home/robot/Downloads/serial_logs
# reuse the current calibration: /home/robot/Downloads/.venv/bin/python /home/robot/Downloads/serial_csv_logger.py /dev/ttyACM0 --outdir /home/robot/Downloads/serial_logs --reuse-calibration


"""
cd /home/robot/Downloads
make clean
make
make flash
"""



import argparse
import csv
import sys
import time
from datetime import datetime
from pathlib import Path

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
STM32_SWEEP_HEADER = "active_channel,led_pwm," + ",".join(CHANNEL_COLUMNS)
STM32_SWEEP_FIELD_COUNT = 2 + len(CHANNEL_COLUMNS)
STM32_SWEEP_DEFAULT_FILE = "stm32_sweep.csv"
CALIBRATION_SWEEP_HEADER = "led_index,duty,main_adc," + ",".join(CHANNEL_COLUMNS)
TRACKING_REPEATS_HEADER = "timestamp_ms,cycle,led_index,duty,repeat," + ",".join(CHANNEL_COLUMNS)
TRACKING_HEADER = (
    "timestamp_ms,cycle,led_index,duty,reference_adc,main_adc,normalized,delta_od,"
    "temperature_c,humidity_percent,"
    + ",".join(CHANNEL_COLUMNS)
)

EXPECTED_HEADERS = {
    "calibration_sweep.csv": CALIBRATION_SWEEP_HEADER,
    "calibration_summary.csv": "led_index,paired_diode,peak_duty,peak_adc,linear_start_duty,linear_end_duty,linear_start_adc,linear_end_adc,fit_slope,fit_intercept,fit_r_squared,target_adc,tracking_duty,tracking_reference_adc,limit_reached,fallback_fit,sweep_points",
    "tracking.csv": TRACKING_HEADER,
    "tracking_repeats.csv": TRACKING_REPEATS_HEADER,
}

TRACKING_FILES = {"tracking.csv", "tracking_repeats.csv"}
LAST_LED_INDEX = len(CHANNEL_COLUMNS) - 1


def parse_args():
    parser = argparse.ArgumentParser(
        description=(
            "Append plain STM32 sweep rows or tagged CSV rows from the board's "
            "serial output into local CSV files."
        )
    )
    parser.add_argument("port", help="Serial port, for example /dev/ttyUSB0 or /dev/ttyACM0")
    parser.add_argument(
        "--baud",
        type=int,
        default=115200,
        help="Serial baud rate. Default: 115200",
    )
    parser.add_argument(
        "--outdir",
        default="serial_logs",
        help=(
            "Base directory for log runs. A new timestamped subfolder is created "
            "for normal runs. --reuse-calibration appends to the latest subfolder. "
            "Default: ./serial_logs"
        ),
    )
    parser.add_argument(
        "--direct-file",
        default=STM32_SWEEP_DEFAULT_FILE,
        help=(
            "CSV filename for the legacy plain STM32 sweep stream. "
            f"Default: {STM32_SWEEP_DEFAULT_FILE}"
        ),
    )
    parser.add_argument(
        "--accept-direct-sweep",
        action="store_true",
        help=(
            "Accept legacy plain sweep rows and append them to --direct-file. "
            "The command-driven calibration firmware does not use this format."
        ),
    )
    parser.add_argument(
        "--reuse-calibration",
        action="store_true",
        help=(
            "Load calibration_summary.csv from the latest log subfolder into "
            "board RAM, then restart tracking without recalibrating."
        ),
    )
    parser.add_argument(
        "--listen-only",
        action="store_true",
        help="Do not send a startup command to the board; only log incoming serial rows.",
    )
    parser.add_argument(
        "--command-delay",
        type=float,
        default=0.25,
        help="Seconds to wait after opening the serial port before sending the board command.",
    )
    parser.add_argument(
        "--command-retry-interval",
        type=float,
        default=1.0,
        help="Seconds between startup command retries until the board acknowledges it.",
    )
    parser.add_argument(
        "--cycle-start",
        type=int,
        default=None,
        help=(
            "Local cycle number to use for the first incoming tagged tracking cycle. "
            "Default: last cycle in local tracking.csv plus 1."
        ),
    )
    args = parser.parse_args()
    if args.reuse_calibration and args.listen_only:
        parser.error("--reuse-calibration and --listen-only cannot be used together")
    return args


def startup_command(args):
    if args.listen_only:
        return None
    if args.reuse_calibration:
        return "REUSE_CALIBRATION"
    return "RESET_CALIBRATE"


def command_wire_payload(command):
    if command == "RESET_CALIBRATE":
        return b"C"
    if command == "REUSE_CALIBRATION":
        return b"U"
    return command.encode("ascii") + b"\n"


def command_log_label(command):
    if command.startswith("LOADROW,"):
        parts = command.split(",", 3)
        if len(parts) >= 2:
            return f"LOADROW row {parts[1]}"
    return command


def send_board_command(ser, command, reason):
    ser.write(command_wire_payload(command))
    ser.flush()
    print(f"Sent board command: {command_log_label(command)} ({reason})")


def line_confirms_command(line):
    return (
        "command accepted:" in line
        or "calibration restored from host CSV" in line
        or "measurement state reset;" in line
        or "calibration starting at pair 0" in line
        or "calibrating pair" in line
        or "tracking started" in line
        or line.startswith("CSV,")
    )


def line_requests_command(line):
    return (
        "STM32G474RE ready; waiting" in line
        or "waiting for RESET_CALIBRATE" in line
    )


def is_header_row(filename, payload):
    return EXPECTED_HEADERS.get(filename) == payload


def is_stm32_sweep_header(payload):
    return payload == STM32_SWEEP_HEADER


def is_stm32_sweep_row(payload):
    fields = payload.split(",")
    if len(fields) != STM32_SWEEP_FIELD_COUNT:
        return False

    try:
        values = [int(field) for field in fields]
    except ValueError:
        return False

    active_channel = values[0]
    led_pwm = values[1]
    adc_values = values[2:]
    return (
        0 <= active_channel < len(CHANNEL_COLUMNS)
        and 0 <= led_pwm <= 65535
        and all(0 <= value <= 4095 for value in adc_values)
    )


def close_handles(handles):
    for handle in handles.values():
        handle.close()
    handles.clear()


def make_timestamped_outdir(base_dir):
    timestamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    candidate = base_dir / timestamp
    suffix = 1
    while candidate.exists():
        candidate = base_dir / f"{timestamp}_{suffix:02d}"
        suffix += 1

    candidate.mkdir(parents=True, exist_ok=False)
    return candidate


def latest_log_subdir(base_dir):
    if not base_dir.exists():
        return None

    subdirs = [path for path in base_dir.iterdir() if path.is_dir()]
    if not subdirs:
        return None

    return max(subdirs, key=lambda path: (path.stat().st_mtime, path.name))


def resolve_run_outdir(base_dir, reuse_calibration):
    base_dir.mkdir(parents=True, exist_ok=True)

    if reuse_calibration:
        latest = latest_log_subdir(base_dir)
        if latest is not None:
            return latest, "latest existing log subfolder"

        created = make_timestamped_outdir(base_dir)
        return created, "new timestamped log subfolder because none existed"

    return make_timestamped_outdir(base_dir), "new timestamped log subfolder"


def load_calibration_restore_commands(summary_path):
    if not summary_path.exists():
        raise FileNotFoundError(f"Calibration summary not found: {summary_path}")

    rows_by_led = {}
    with summary_path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        required_columns = {"led_index", "tracking_duty", "tracking_reference_adc"}
        missing_columns = required_columns.difference(reader.fieldnames or [])
        if missing_columns:
            missing = ", ".join(sorted(missing_columns))
            raise ValueError(f"{summary_path} is missing required column(s): {missing}")

        for row in reader:
            try:
                led_index = int(row["led_index"])
                tracking_duty = int(row["tracking_duty"])
                reference_adc_centi = round(float(row["tracking_reference_adc"]) * 100.0)
            except (TypeError, ValueError) as exc:
                raise ValueError(f"Invalid calibration row in {summary_path}: {row}") from exc

            if not 0 <= led_index < len(CHANNEL_COLUMNS):
                raise ValueError(f"Invalid led_index {led_index} in {summary_path}")
            if not 0 <= tracking_duty <= 65535:
                raise ValueError(f"Invalid tracking_duty {tracking_duty} for led_index {led_index}")
            if not 0 <= reference_adc_centi <= 409500:
                raise ValueError(
                    f"Invalid tracking_reference_adc {row['tracking_reference_adc']} "
                    f"for led_index {led_index}"
                )

            rows_by_led[led_index] = (tracking_duty, reference_adc_centi)

    missing_leds = [index for index in range(len(CHANNEL_COLUMNS)) if index not in rows_by_led]
    if missing_leds:
        missing = ", ".join(str(index) for index in missing_leds)
        raise ValueError(f"{summary_path} is missing calibration rows for led_index: {missing}")

    commands = ["LOADZERO"]
    for led_index in range(len(CHANNEL_COLUMNS)):
        tracking_duty, reference_adc_centi = rows_by_led[led_index]
        commands.append(f"LOADROW,{led_index},{tracking_duty},{reference_adc_centi}")
    return commands


def parse_cycle(payload):
    fields = payload.split(",")
    if len(fields) < 2:
        return None

    try:
        return int(fields[1])
    except ValueError:
        return None


def parse_timestamp(payload):
    fields = payload.split(",")
    if not fields:
        return None

    try:
        return int(fields[0])
    except ValueError:
        return None


def parse_led_index(payload):
    fields = payload.split(",")
    if len(fields) < 3:
        return None

    try:
        return int(fields[2])
    except ValueError:
        return None


def replace_cycle(payload, cycle):
    fields = payload.split(",")
    if len(fields) < 2:
        return payload

    fields[1] = str(cycle)
    return ",".join(fields)


def load_last_tracking_position(tracking_path):
    if not tracking_path.exists() or tracking_path.stat().st_size == 0:
        return None, None, None

    last_timestamp = None
    last_cycle = None
    last_led = None
    with tracking_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            line = line.strip()
            if not line or is_header_row("tracking.csv", line):
                continue

            timestamp = parse_timestamp(line)
            cycle = parse_cycle(line)
            led_index = parse_led_index(line)
            if timestamp is None or cycle is None or led_index is None:
                continue

            last_timestamp = timestamp
            last_cycle = cycle
            last_led = led_index

    return last_timestamp, last_cycle, last_led


def map_cycle_from_led_order(payload, state):
    timestamp = parse_timestamp(payload)
    led_index = parse_led_index(payload)
    if timestamp is None or led_index is None:
        return None

    same_measurement = (
        timestamp == state["last_timestamp"]
        and led_index == state["last_led"]
    )

    if state["last_led"] is not None and not same_measurement:
        if led_index <= state["last_led"]:
            state["cycle"] += 1

    state["last_timestamp"] = timestamp
    state["last_led"] = led_index
    return state["cycle"]


def main():
    args = parse_args()
    base_outdir = Path(args.outdir).expanduser().resolve()
    outdir, outdir_reason = resolve_run_outdir(base_outdir, args.reuse_calibration)
    direct_filename = Path(args.direct_file).name
    direct_target = outdir / direct_filename
    restore_commands = []
    if args.reuse_calibration:
        try:
            restore_commands = load_calibration_restore_commands(outdir / "calibration_summary.csv")
        except (FileNotFoundError, ValueError) as exc:
            print(f"Cannot reuse calibration: {exc}", file=sys.stderr)
            return 2

    last_local_timestamp, last_local_cycle, last_local_led = load_last_tracking_position(outdir / "tracking.csv")
    if args.cycle_start is not None:
        local_cycle = args.cycle_start
        last_local_timestamp = None
        last_local_led = None
    elif last_local_cycle is None:
        local_cycle = 0
    else:
        local_cycle = last_local_cycle

    print(f"Listening on {args.port} at {args.baud} baud")
    print(f"Log base directory: {base_outdir}")
    print(f"Writing CSV files into {outdir} ({outdir_reason})")
    if args.accept_direct_sweep:
        print(f"Legacy plain STM32 sweep rows will be appended to {direct_target}")
    else:
        print("Legacy plain STM32 sweep rows will be ignored")
    print("Appending CSV rows. Existing files will not be overwritten.")
    command = startup_command(args)
    if command is None:
        print("Board startup command: disabled")
    else:
        print(f"Board startup command: {command}")
    if restore_commands:
        print(f"Restoring calibration from {outdir / 'calibration_summary.csv'}")

    if args.cycle_start is not None or last_local_led is not None:
        if last_local_led is None:
            print(f"First tagged tracking row will be logged as local cycle {local_cycle}.")
        elif last_local_led >= LAST_LED_INDEX:
            print(f"Next tagged led_index 0 row will be logged as local cycle {local_cycle + 1}.")
        else:
            print(
                f"Continuing tagged tracking after local cycle {local_cycle}, "
                f"led_index {last_local_led}; cycle advances when led_index wraps."
            )

    handles = {}
    warned_direct_sweep = False
    cycle_state = {
        "cycle": local_cycle,
        "last_timestamp": last_local_timestamp,
        "last_led": last_local_led,
    }

    try:
        with serial.Serial(args.port, args.baud, timeout=1) as ser:
            command_confirmed = command is None
            last_command_sent_at = None
            if command is not None:
                time.sleep(args.command_delay)
                for restore_command in restore_commands:
                    send_board_command(ser, restore_command, "restore calibration from CSV")
                    time.sleep(0.01)
                send_board_command(ser, command, "initial")
                last_command_sent_at = time.monotonic()

            while True:
                raw = ser.readline()
                if not raw:
                    if (
                        command is not None
                        and not command_confirmed
                        and last_command_sent_at is not None
                        and time.monotonic() - last_command_sent_at >= args.command_retry_interval
                    ):
                        send_board_command(ser, command, "retry waiting for acknowledgement")
                        last_command_sent_at = time.monotonic()
                    continue

                line = raw.decode("utf-8", errors="replace").strip()
                if not line:
                    continue

                if command is not None and not command_confirmed:
                    if line_confirms_command(line):
                        command_confirmed = True
                    elif line_requests_command(line):
                        print(f"[board] {line}")
                        send_board_command(ser, command, "board reported ready")
                        last_command_sent_at = time.monotonic()
                        continue
                    elif (
                        last_command_sent_at is not None
                        and time.monotonic() - last_command_sent_at >= args.command_retry_interval
                    ):
                        send_board_command(ser, command, "retry waiting for acknowledgement")
                        last_command_sent_at = time.monotonic()

                if is_stm32_sweep_header(line):
                    if not args.accept_direct_sweep:
                        if not warned_direct_sweep:
                            print(
                                "Received legacy plain sweep output after sending the board command. "
                                "The board is probably still running the old sweep firmware; flash "
                                "build/stm32_g474re_tlc59711.bin and try again.",
                                file=sys.stderr,
                            )
                            warned_direct_sweep = True
                        continue

                    target_has_content = direct_target.exists() and direct_target.stat().st_size > 0
                    if target_has_content:
                        continue

                    handle = handles.get(direct_target)
                    if handle is None:
                        handle = direct_target.open("a", encoding="utf-8", buffering=1)
                        handles[direct_target] = handle
                        print(f"Appending to {direct_target}")

                    handle.write(STM32_SWEEP_HEADER + "\n")
                    handle.flush()
                    continue

                if is_stm32_sweep_row(line):
                    if not args.accept_direct_sweep:
                        if not warned_direct_sweep:
                            print(
                                "Received legacy plain sweep output after sending the board command. "
                                "The board is probably still running the old sweep firmware; flash "
                                "build/stm32_g474re_tlc59711.bin and try again.",
                                file=sys.stderr,
                            )
                            warned_direct_sweep = True
                        continue

                    target_has_content = direct_target.exists() and direct_target.stat().st_size > 0
                    handle = handles.get(direct_target)
                    if handle is None:
                        handle = direct_target.open("a", encoding="utf-8", buffering=1)
                        handles[direct_target] = handle
                        print(f"Appending to {direct_target}")

                    if not target_has_content:
                        handle.write(STM32_SWEEP_HEADER + "\n")

                    handle.write(line + "\n")
                    handle.flush()
                    continue

                if not line.startswith("CSV,"):
                    print(f"[board] {line}")
                    continue

                parts = line.split(",", 2)
                if len(parts) != 3:
                    print(f"Malformed CSV frame: {line}", file=sys.stderr)
                    continue

                _, filename, payload = parts
                header_row = is_header_row(filename, payload)
                expected_header = EXPECTED_HEADERS.get(filename)
                if expected_header is None:
                    print(f"Unexpected CSV target {filename}: {payload}", file=sys.stderr)
                    continue

                target = outdir / filename
                target_has_content = target.exists() and target.stat().st_size > 0

                if header_row and target_has_content:
                    continue

                if filename in TRACKING_FILES and not header_row:
                    local_cycle_for_row = map_cycle_from_led_order(payload, cycle_state)
                    if local_cycle_for_row is None:
                        print(f"Malformed led_index in {filename}: {payload}", file=sys.stderr)
                        continue

                    payload = replace_cycle(payload, local_cycle_for_row)

                handle = handles.get(target)
                if handle is None:
                    handle = target.open("a", encoding="utf-8", buffering=1)
                    handles[target] = handle
                    print(f"Appending to {target}")

                if not header_row and not target_has_content:
                    handle.write(expected_header + "\n")

                handle.write(payload + "\n")
                handle.flush()
    except KeyboardInterrupt:
        print("\nStopping logger")
    finally:
        close_handles(handles)


if __name__ == "__main__":
    main()
