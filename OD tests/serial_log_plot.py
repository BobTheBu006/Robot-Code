#!/usr/bin/env python3
"""Interactive plots for the newest serial_logs tracking repeat data."""

from __future__ import annotations

import argparse
import csv
from collections import defaultdict
from pathlib import Path

import matplotlib.pyplot as plt
from matplotlib.widgets import Button, CheckButtons


SERIAL_LOGS_DIR = Path("/home/robot/Downloads/serial_logs")

CHANNEL_GROUPS = [
    ("bacteria col 1", [0, 1, 2, 3]),
    ("bacteria col 2", [4, 5, 6, 7]),
    ("bacteria col 3", [8, 9, 10, 11]),
    ("beads + medium", [12, 13, 14]),
    ("beads", [15, 18, 19]),
    ("empty", [16, 17, 22, 23]),
]

CHANNELS = list(range(24))


def latest_log_dir(base_dir: Path = SERIAL_LOGS_DIR) -> Path:
    dirs = [p for p in base_dir.iterdir() if p.is_dir()]
    if not dirs:
        raise FileNotFoundError(f"No log folders found in {base_dir}")
    return max(dirs, key=lambda p: p.name)


def read_csv(path: Path) -> list[dict[str, float | int | str]]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        return [{key: parse_value(value) for key, value in row.items()} for row in reader]


def parse_value(value: str) -> float | int | str:
    if value == "":
        return value
    try:
        number = float(value)
    except ValueError:
        return value
    if number.is_integer():
        return int(number)
    return number


def channel_column(rows: list[dict[str, object]], channel: int) -> str:
    prefix = f"ch{channel}_"
    for key in rows[0]:
        if key.startswith(prefix):
            return key
    raise KeyError(f"Could not find column for channel {channel}")


def channel_columns(rows: list[dict[str, object]]) -> dict[int, str]:
    return {channel: channel_column(rows, channel) for channel in CHANNELS}


def rows_by_led_and_repeat(
    repeat_rows: list[dict[str, float | int | str]]
) -> dict[int, dict[int, list[dict[str, float | int | str]]]]:
    grouped: dict[int, dict[int, list[dict[str, float | int | str]]]] = defaultdict(lambda: defaultdict(list))
    for row in repeat_rows:
        grouped[int(row["led_index"])][int(row["repeat"])].append(row)

    for repeats in grouped.values():
        for rows in repeats.values():
            rows.sort(key=lambda row: int(row["cycle"]))

    return grouped


def attach_checkboxes(
    fig,
    toggle_artists: dict[str, list[object]],
    *,
    rect: list[float],
    font_size: int,
    title: str = "Show / hide",
    all_button_rect: list[float] | None = None,
) -> None:
    check_ax = fig.add_axes(rect)
    labels = list(toggle_artists)
    checks = CheckButtons(check_ax, labels, [True] * len(labels))
    check_ax.set_title(title)
    for text in checks.labels:
        text.set_fontsize(font_size)

    def on_toggle(label: str) -> None:
        for artist in toggle_artists[label]:
            artist.set_visible(not artist.get_visible())
        fig.canvas.draw_idle()

    checks.on_clicked(on_toggle)
    fig._check_buttons = checks

    if all_button_rect is not None:
        button_ax = fig.add_axes(all_button_rect)
        button = Button(button_ax, "All on/off")

        def on_all_toggle(event) -> None:
            all_artists = [
                artist
                for artists in toggle_artists.values()
                for artist in artists
            ]
            if not all_artists:
                return
            show = not any(artist.get_visible() for artist in all_artists)
            for artist in all_artists:
                artist.set_visible(show)
            fig.canvas.draw_idle()

        button.on_clicked(on_all_toggle)
        fig._all_toggle_button = button


def row_points(
    rows: list[dict[str, float | int | str]],
    col: str,
    *,
    derivative: bool,
) -> list[tuple[int, float]]:
    points = [(int(row["cycle"]), float(row[col])) for row in rows]
    if not derivative:
        return points

    return [
        (points[index][0], points[index + 1][1] - points[index][1])
        for index in range(len(points) - 1)
    ]


def plot_grouped_by_led(
    log_dir: Path,
    repeat_rows: list[dict[str, float | int | str]],
    *,
    derivative: bool = False,
) -> None:
    columns = channel_columns(repeat_rows)
    rows_by_led = rows_by_led_and_repeat(repeat_rows)
    led_pages = [CHANNELS[index:index + 6] for index in range(0, len(CHANNELS), 6)]
    value_label = "ADC derivative" if derivative else "ADC"
    title_prefix = "Channel reading derivatives grouped by LED" if derivative else "All channel readings grouped by LED"

    for page_number, led_indices in enumerate(led_pages, start=1):
        fig, axes = plt.subplots(3, 2, figsize=(16, 10), sharex=True)
        title = (
            f"{title_prefix} "
            f"({page_number}/{len(led_pages)}): {log_dir.name}"
        )
        fig.canvas.manager.set_window_title(title)
        fig.suptitle(title)
        fig.subplots_adjust(left=0.06, right=0.73, top=0.92, bottom=0.08, hspace=0.35, wspace=0.25)

        toggle_artists: dict[str, list[object]] = {
            f"ch{channel} repeats": [] for channel in CHANNELS
        }
        toggle_artists.update({f"ch{channel} mean": [] for channel in CHANNELS})

        for led_index, ax in zip(led_indices, axes.flat):
            ax.set_title(f"LED {led_index}")
            ax.set_xlabel("Cycle")
            ax.set_ylabel(value_label)
            ax.grid(True, alpha=0.25)

            for channel, col in columns.items():
                color = f"C{channel % 10}"
                values_by_cycle = defaultdict(list)
                for repeat_index, rows in sorted(rows_by_led.get(led_index, {}).items()):
                    points = row_points(rows, col, derivative=derivative)
                    (line,) = ax.plot(
                        [point[0] for point in points],
                        [point[1] for point in points],
                        linewidth=0.55,
                        alpha=0.16,
                        color=color,
                        label="_nolegend_",
                    )
                    toggle_artists[f"ch{channel} repeats"].append(line)

                    for cycle, value in points:
                        values_by_cycle[cycle].append(value)

                mean_points = sorted(
                    (cycle, sum(values) / len(values))
                    for cycle, values in values_by_cycle.items()
                )
                if mean_points:
                    (mean_line,) = ax.plot(
                        [point[0] for point in mean_points],
                        [point[1] for point in mean_points],
                        linewidth=1.5,
                        alpha=0.9,
                        color=color,
                        label="_nolegend_",
                    )
                    toggle_artists[f"ch{channel} mean"].append(mean_line)

        attach_checkboxes(
            fig,
            toggle_artists,
            rect=[0.76, 0.08, 0.22, 0.82],
            font_size=7,
            title="Channels",
            all_button_rect=[0.76, 0.925, 0.22, 0.035],
        )


def plot_grouped_by_channel(
    log_dir: Path,
    repeat_rows: list[dict[str, float | int | str]],
    *,
    derivative: bool = False,
) -> None:
    columns = channel_columns(repeat_rows)
    rows_by_led = rows_by_led_and_repeat(repeat_rows)
    channel_pages = [CHANNELS[index:index + 6] for index in range(0, len(CHANNELS), 6)]
    value_label = "ADC derivative" if derivative else "ADC"
    title_prefix = "LED reading derivatives grouped by channel" if derivative else "All LED readings grouped by channel"

    for page_number, channels in enumerate(channel_pages, start=1):
        fig, axes = plt.subplots(3, 2, figsize=(16, 10), sharex=True)
        title = (
            f"{title_prefix} "
            f"({page_number}/{len(channel_pages)}): {log_dir.name}"
        )
        fig.canvas.manager.set_window_title(title)
        fig.suptitle(title)
        fig.subplots_adjust(left=0.06, right=0.73, top=0.92, bottom=0.08, hspace=0.35, wspace=0.25)

        toggle_artists: dict[str, list[object]] = {
            f"LED {led_index} repeats": [] for led_index in CHANNELS
        }
        toggle_artists.update({f"LED {led_index} mean": [] for led_index in CHANNELS})

        for channel, ax in zip(channels, axes.flat):
            col = columns[channel]
            ax.set_title(f"ch{channel} ({col})")
            ax.set_xlabel("Cycle")
            ax.set_ylabel(value_label)
            ax.grid(True, alpha=0.25)

            for led_index in CHANNELS:
                color = f"C{led_index % 10}"
                values_by_cycle = defaultdict(list)
                for repeat_index, rows in sorted(rows_by_led.get(led_index, {}).items()):
                    points = row_points(rows, col, derivative=derivative)
                    (line,) = ax.plot(
                        [point[0] for point in points],
                        [point[1] for point in points],
                        linewidth=0.55,
                        alpha=0.16,
                        color=color,
                        label="_nolegend_",
                    )
                    toggle_artists[f"LED {led_index} repeats"].append(line)

                    for cycle, value in points:
                        values_by_cycle[cycle].append(value)

                mean_points = sorted(
                    (cycle, sum(values) / len(values))
                    for cycle, values in values_by_cycle.items()
                )
                if mean_points:
                    (mean_line,) = ax.plot(
                        [point[0] for point in mean_points],
                        [point[1] for point in mean_points],
                        linewidth=1.5,
                        alpha=0.9,
                        color=color,
                        label="_nolegend_",
                    )
                    toggle_artists[f"LED {led_index} mean"].append(mean_line)

        attach_checkboxes(
            fig,
            toggle_artists,
            rect=[0.76, 0.08, 0.22, 0.82],
            font_size=7,
            title="LEDs",
            all_button_rect=[0.76, 0.925, 0.22, 0.035],
        )


def plot_channels(
    log_dir: Path,
    repeat_rows: list[dict[str, float | int | str]],
) -> None:
    fig, axes = plt.subplots(3, 2, figsize=(16, 10), sharex=False)
    fig.canvas.manager.set_window_title(f"Main LED-channel pairs: {log_dir.name}")
    fig.suptitle(f"Main LED-channel pairs ADC by cycle: {log_dir.name}")
    fig.subplots_adjust(left=0.06, right=0.72, top=0.92, bottom=0.08, hspace=0.34, wspace=0.22)

    toggle_artists: dict[str, list[object]] = {}

    for ax, (group_name, channels) in zip(axes.flat, CHANNEL_GROUPS):
        ax.set_title(group_name)
        ax.set_xlabel("Cycle")
        ax.set_ylabel("ADC")
        ax.grid(True, alpha=0.25)

        for channel in channels:
            col = channel_column(repeat_rows, channel)
            color = f"C{channel % 10}"
            pair_label = f"LED {channel} - {col}"

            repeats = [row for row in repeat_rows if row["led_index"] == channel]
            repeat_artists = []
            repeat_by_index = defaultdict(list)
            for row in repeats:
                repeat_by_index[row["repeat"]].append(row)

            for repeat_index, rows in sorted(repeat_by_index.items()):
                rows = sorted(rows, key=lambda row: row["cycle"])
                (line,) = ax.plot(
                    [row["cycle"] for row in rows],
                    [row[col] for row in rows],
                    linewidth=0.8,
                    alpha=0.28,
                    color=color,
                    label="_nolegend_",
                )
                repeat_artists.append(line)

            means_by_cycle = defaultdict(list)
            for row in repeats:
                means_by_cycle[row["cycle"]].append(float(row[col]))

            mean_points = sorted(
                (cycle, sum(values) / len(values))
                for cycle, values in means_by_cycle.items()
            )
            mean_artists = []
            if mean_points:
                (mean_line,) = ax.plot(
                    [point[0] for point in mean_points],
                    [point[1] for point in mean_points],
                    linewidth=2.0,
                    color=color,
                    label=f"{pair_label} mean",
                )
                mean_artists.append(mean_line)

            toggle_artists[f"LED {channel} - ch{channel} repeats"] = repeat_artists
            toggle_artists[f"LED {channel} - ch{channel} mean"] = mean_artists

        ax.legend(loc="best", fontsize=7, ncols=2)

    attach_checkboxes(
        fig,
        toggle_artists,
        rect=[0.75, 0.08, 0.22, 0.82],
        font_size=8,
    )


def plot_environment(log_dir: Path, tracking_rows: list[dict[str, float | int | str]]) -> None:
    if not tracking_rows:
        return

    required = {"temperature_c", "humidity_percent", "cycle"}
    missing = required.difference(tracking_rows[0])
    if missing:
        print(f"Skipping environment plot; missing columns: {', '.join(sorted(missing))}")
        return

    cycles = [row["cycle"] for row in tracking_rows]
    temps = [row["temperature_c"] for row in tracking_rows]
    humidity = [row["humidity_percent"] for row in tracking_rows]

    fig, ax_temp = plt.subplots(figsize=(12, 6))
    fig.canvas.manager.set_window_title(f"Temperature and humidity: {log_dir.name}")
    fig.suptitle(f"Temperature and humidity: {log_dir.name}")

    (temp_line,) = ax_temp.plot(cycles, temps, color="tab:red", label="temperature C")
    ax_temp.set_xlabel("Cycle")
    ax_temp.set_ylabel("Temperature (C)", color="tab:red")
    ax_temp.tick_params(axis="y", labelcolor="tab:red")
    ax_temp.grid(True, alpha=0.25)

    ax_hum = ax_temp.twinx()
    (hum_line,) = ax_hum.plot(cycles, humidity, color="tab:blue", label="humidity %")
    ax_hum.set_ylabel("Humidity (%)", color="tab:blue")
    ax_hum.tick_params(axis="y", labelcolor="tab:blue")

    check_ax = fig.add_axes([0.78, 0.72, 0.16, 0.13])
    checks = CheckButtons(check_ax, ["temperature", "humidity"], [True, True])

    def on_toggle(label: str) -> None:
        if label == "temperature":
            temp_line.set_visible(not temp_line.get_visible())
        else:
            hum_line.set_visible(not hum_line.get_visible())
        fig.canvas.draw_idle()

    checks.on_clicked(on_toggle)
    fig._environment_check_buttons = checks


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "log_dir",
        nargs="?",
        type=Path,
        default=None,
        help="Log folder to plot. Defaults to the newest folder under /home/robot/Downloads/serial_logs.",
    )
    args = parser.parse_args()

    log_dir = args.log_dir or latest_log_dir()
    repeats_path = log_dir / "tracking_repeats.csv"
    tracking_path = log_dir / "tracking.csv"

    if not repeats_path.exists():
        raise FileNotFoundError(repeats_path)

    repeat_rows = read_csv(repeats_path)

    plot_channels(log_dir, repeat_rows)
    plot_grouped_by_led(log_dir, repeat_rows)
    plot_grouped_by_channel(log_dir, repeat_rows)
    plot_grouped_by_led(log_dir, repeat_rows, derivative=True)
    plot_grouped_by_channel(log_dir, repeat_rows, derivative=True)
    if tracking_path.exists():
        plot_environment(log_dir, read_csv(tracking_path))
    else:
        print(f"Skipping temperature/humidity plot; {tracking_path} was not found")
    plt.show()


if __name__ == "__main__":
    main()
