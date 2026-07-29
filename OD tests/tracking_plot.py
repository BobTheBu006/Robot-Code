from math import ceil
from pathlib import Path
import re

import matplotlib.pyplot as plt
from matplotlib.widgets import CheckButtons
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
LOG_BASE_DIR = BASE_DIR / "serial_logs"
DATA_POINT_STEP = 1
CYCLE_MIN = 0
MAX_RAW_ADC_DELTA = 25
GRID_COLUMNS = 4
CHANNEL_GROUPS = [
    ("bacteria col 1", [0, 1, 2, 3]),
    ("bacteria col 2", [4, 5, 6, 7]),
    ("bacteria col 3", [8, 9, 10, 11]),
    ("beads + medium", [12, 13, 14]),
    ("beads", [15, 18, 19]),
    ("empty", [16, 17, 22, 23]),
]


def latest_log_file(filename):
    candidates = []
    if LOG_BASE_DIR.exists():
        candidates.extend(path / filename for path in LOG_BASE_DIR.iterdir() if path.is_dir())
    candidates.append(LOG_BASE_DIR / filename)

    existing = [path for path in candidates if path.exists()]
    if not existing:
        return LOG_BASE_DIR / filename

    return max(existing, key=lambda path: (path.stat().st_mtime, path.parent.name))


TRACKING_PATH = latest_log_file("tracking.csv")
TRACKING_REPEATS_PATH = latest_log_file("tracking_repeats.csv")


def channel_number(column):
    match = re.match(r"ch(\d+)(?:_|$)", str(column))
    if not match:
        return None
    return int(match.group(1))


def find_channel_columns(df):
    return sorted(
        [column for column in df.columns if channel_number(column) is not None],
        key=channel_number,
    )


def make_axes(count, figsize_per_col=4.2, figsize_per_row=3.2):
    cols = min(4, max(1, count))
    rows = max(1, ceil(count / cols))
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(figsize_per_col * cols, figsize_per_row * rows),
        sharex=True,
        sharey=True,
    )
    if count == 1:
        return fig, [axes]
    return fig, list(axes.flat)


def chunks(values, size):
    for start in range(0, len(values), size):
        yield values[start:start + size], (start // size) + 1, ceil(len(values) / size)


def adjacent_channels(channel, max_channel):
    channel = int(channel)
    column = channel % GRID_COLUMNS
    channels = []

    if column > 0:
        channels.append(channel - 1)
    channels.append(channel)
    if column < GRID_COLUMNS - 1 and channel + 1 <= max_channel:
        channels.append(channel + 1)
    if channel - GRID_COLUMNS >= 0:
        channels.append(channel - GRID_COLUMNS)
    if channel + GRID_COLUMNS <= max_channel:
        channels.append(channel + GRID_COLUMNS)

    return channels


def padded_limits(series, padding_fraction=0.05):
    minimum = series.min()
    maximum = series.max()
    span = maximum - minimum
    if pd.isna(span):
        return None
    if span == 0:
        padding = abs(maximum) * padding_fraction or 1.0
    else:
        padding = span * padding_fraction
    return minimum - padding, maximum + padding


def grouped_tracking_data(df):
    group_frames = []
    for group_name, group_channels in CHANNEL_GROUPS:
        group_df = df[df["measured_channel"].isin(group_channels)].copy()
        if group_df.empty:
            continue

        group_df["channel_group"] = group_name
        group_frames.append(group_df)

    if not group_frames:
        return pd.DataFrame()

    return pd.concat(group_frames, ignore_index=True)


def normalize_trace(series):
    valid = series.dropna()
    if valid.empty:
        return series

    mean = valid.mean()
    variance = valid.var()
    centered = series - mean
    if pd.isna(variance) or variance == 0:
        return centered

    return centered / variance


def add_visibility_checkboxes(fig, line_groups, title):
    if not line_groups:
        return

    fig.subplots_adjust(right=0.86)
    checkbox_ax = fig.add_axes([0.875, 0.16, 0.115, 0.68])
    labels = list(line_groups)
    checkboxes = CheckButtons(checkbox_ax, labels, [True] * len(labels))
    checkbox_ax.set_title(title, fontsize=9)

    def toggle(label):
        visible = not line_groups[label][0].get_visible()
        for line in line_groups[label]:
            line.set_visible(visible)
        fig.canvas.draw_idle()

    checkboxes.on_clicked(toggle)
    fig._trace_visibility_checkboxes = checkboxes


def read_tracking_csv(path):
    df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
    df.columns = [column.strip() for column in df.columns]

    required_columns = [
        "timestamp_ms",
        "cycle",
        "led_index",
        "duty",
        "reference_adc",
        "main_adc",
        "normalized",
        "delta_od",
    ]
    channel_columns = find_channel_columns(df)
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {missing_columns}")
    if not channel_columns:
        raise ValueError(f"{path} has no channel columns named like ch0 or ch0_pa0")

    environment_columns = [
        column for column in ["temperature_c", "humidity_percent"] if column in df.columns
    ]
    numeric_columns = required_columns + environment_columns + channel_columns
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["timestamp_ms", "cycle", "led_index", "duty", *channel_columns])
    df = df.sort_index().copy()

    reset_rows = (df["cycle"].diff() < 0) | (df["timestamp_ms"].diff() < 0)
    df["session"] = reset_rows.fillna(False).cumsum().astype(int)
    return df, channel_columns


def read_tracking_repeats_csv(path, channel_columns):
    df = pd.read_csv(path, on_bad_lines="warn", low_memory=False)
    df.columns = [column.strip() for column in df.columns]

    required_columns = ["timestamp_ms", "cycle", "led_index", "duty", "repeat"]
    missing_columns = [column for column in required_columns if column not in df.columns]
    if missing_columns:
        raise ValueError(f"{path} is missing required columns: {missing_columns}")

    numeric_columns = required_columns + channel_columns
    for column in numeric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    df = df.dropna(subset=["timestamp_ms", "cycle", "led_index", "repeat", *channel_columns])
    df = df.sort_index().copy()

    reset_rows = (df["cycle"].diff() < 0) | (df["timestamp_ms"].diff() < 0)
    df["session"] = reset_rows.fillna(False).cumsum().astype(int)
    return df


def remove_large_raw_adc_jumps(group):
    group = group.sort_values("plot_cycle")
    corrected = []
    cumulative_delta = 0.0
    previous_corrected_adc = None

    for row in group.itertuples():
        corrected_adc = row.adc - cumulative_delta

        if previous_corrected_adc is not None:
            adc_delta = corrected_adc - previous_corrected_adc
            if abs(adc_delta) > MAX_RAW_ADC_DELTA:
                cumulative_delta += adc_delta
                corrected_adc -= adc_delta

        corrected.append((row.Index, corrected_adc))
        previous_corrected_adc = corrected_adc

    return pd.Series(
        [value for _, value in corrected],
        index=[index for index, _ in corrected],
    )


tracking_full_df, CHANNEL_COLUMNS = read_tracking_csv(TRACKING_PATH)
tracking_full_df = tracking_full_df[tracking_full_df["cycle"] >= CYCLE_MIN].copy()

if tracking_full_df.empty:
    raise ValueError(f"No tracking rows found at or after cycle {CYCLE_MIN}.")

cycle_led_counts = tracking_full_df.groupby(["session", "cycle"])["led_index"].nunique()
complete_cycle_index = cycle_led_counts[cycle_led_counts == len(CHANNEL_COLUMNS)].index
complete_cycles = pd.DataFrame(
    list(complete_cycle_index),
    columns=["session", "cycle"],
)

tracking_df = tracking_full_df.merge(complete_cycles, on=["session", "cycle"], how="inner")

if tracking_df.empty:
    raise ValueError(
        f"No complete tracking cycles found in {TRACKING_PATH}. "
        f"Expected every complete cycle to contain all {len(CHANNEL_COLUMNS)} LED indices."
    )

tracking_df["plot_cycle"] = tracking_df.groupby(["session", "cycle"], sort=False).ngroup()
if DATA_POINT_STEP > 1:
    tracking_df = tracking_df[tracking_df["plot_cycle"] % DATA_POINT_STEP == 0].copy()

if tracking_df.empty:
    raise ValueError(
        "No tracking rows remain after downsampling. Set DATA_POINT_STEP to a smaller value."
    )

tracking_long = tracking_df.melt(
    id_vars=[
        "timestamp_ms",
        "session",
        "cycle",
        "plot_cycle",
        "led_index",
        "duty",
        "reference_adc",
        "main_adc",
        "normalized",
        "delta_od",
        *[column for column in ["temperature_c", "humidity_percent"] if column in tracking_df.columns],
    ],
    value_vars=CHANNEL_COLUMNS,
    var_name="measured_channel",
    value_name="adc",
)
tracking_long["measured_channel"] = tracking_long["measured_channel"].map(channel_number)

cycle_plot_index = tracking_df[
    ["session", "cycle", "plot_cycle"]
].drop_duplicates()
tracking_repeats_df = read_tracking_repeats_csv(TRACKING_REPEATS_PATH, CHANNEL_COLUMNS)
tracking_repeats_df = tracking_repeats_df[
    tracking_repeats_df["cycle"] >= CYCLE_MIN
].copy()
tracking_repeats_df = tracking_repeats_df.merge(
    cycle_plot_index,
    on=["session", "cycle"],
    how="inner",
)
if DATA_POINT_STEP > 1:
    tracking_repeats_df = tracking_repeats_df[
        tracking_repeats_df["plot_cycle"] % DATA_POINT_STEP == 0
    ].copy()

if tracking_repeats_df.empty:
    raise ValueError(f"No repeat tracking rows found in {TRACKING_REPEATS_PATH}.")

repeat_count = int(tracking_repeats_df["repeat"].max()) + 1
tracking_repeats_df["repeat_plot_cycle"] = (
    tracking_repeats_df["plot_cycle"]
    + tracking_repeats_df["repeat"] / max(1, repeat_count)
)
tracking_repeats_long = tracking_repeats_df.melt(
    id_vars=[
        "timestamp_ms",
        "session",
        "cycle",
        "plot_cycle",
        "repeat_plot_cycle",
        "led_index",
        "duty",
        "repeat",
    ],
    value_vars=CHANNEL_COLUMNS,
    var_name="measured_channel",
    value_name="adc",
)
tracking_repeats_long["measured_channel"] = tracking_repeats_long[
    "measured_channel"
].map(channel_number)

main_tracking = tracking_long[
    tracking_long["led_index"] == tracking_long["measured_channel"]
].copy()
main_tracking = main_tracking.sort_values(["measured_channel", "plot_cycle"])
main_tracking["adc_raw_delta_corrected"] = (
    main_tracking.groupby("measured_channel", group_keys=False)
    .apply(remove_large_raw_adc_jumps)
    .sort_index()
)

channels = sorted(main_tracking["measured_channel"].unique())
adc_y_limits = padded_limits(
    main_tracking[["adc", "adc_raw_delta_corrected"]].stack()
)

fig_comparison, axes_comparison = make_axes(len(channels))

for ax, ch in zip(axes_comparison, channels):
    tracking_ch = main_tracking[main_tracking["measured_channel"] == ch].sort_values(
        "plot_cycle"
    )

    ax.plot(
        tracking_ch["plot_cycle"],
        tracking_ch["adc"],
        linewidth=1.5,
        marker="o",
        markersize=3,
        alpha=0.65,
        label="Raw",
    )
    ax.plot(
        tracking_ch["plot_cycle"],
        tracking_ch["adc_raw_delta_corrected"],
        linewidth=2,
        marker="o",
        markersize=3,
        label="Processed",
    )

    ax.set_title(f"Channel {int(ch)}")
    ax.set_xlabel("Complete cycle")
    ax.set_ylabel("ADC")
    if adc_y_limits:
        ax.set_ylim(*adc_y_limits)
    ax.legend(frameon=False, fontsize=8)
    ax.grid(True)

for ax in axes_comparison[len(channels):]:
    ax.set_visible(False)

fig_comparison.suptitle("Raw and processed tracking ADC")
fig_comparison.tight_layout()

group_tracking = grouped_tracking_data(main_tracking)
if not group_tracking.empty:
    group_names = [
        group_name
        for group_name, _ in CHANNEL_GROUPS
        if group_name in set(group_tracking["channel_group"])
    ]
    grouped_y_limits = padded_limits(group_tracking["adc_raw_delta_corrected"])

    fig_groups, axes_groups = make_axes(len(group_names), figsize_per_col=4.8)
    for ax, group_name in zip(axes_groups, group_names):
        tracking_group = group_tracking[group_tracking["channel_group"] == group_name]

        for ch in sorted(tracking_group["measured_channel"].unique()):
            tracking_ch = tracking_group[
                tracking_group["measured_channel"] == ch
            ].sort_values("plot_cycle")
            ax.plot(
                tracking_ch["plot_cycle"],
                tracking_ch["adc_raw_delta_corrected"],
                linewidth=1.8,
                marker="o",
                markersize=2.5,
                label=f"Channel {int(ch)}",
            )

        ax.set_title(group_name)
        ax.set_xlabel("Complete cycle")
        ax.set_ylabel("Raw-delta-corrected ADC")
        if grouped_y_limits:
            ax.set_ylim(*grouped_y_limits)
        ax.legend(frameon=False, fontsize=8)
        ax.grid(True)

    for ax in axes_groups[len(group_names):]:
        ax.set_visible(False)

    fig_groups.suptitle("Tracking ADC by channel group")
    fig_groups.tight_layout()

    raw_grouped_y_limits = padded_limits(group_tracking["adc"])

    fig_raw_groups, axes_raw_groups = make_axes(len(group_names), figsize_per_col=4.8)
    for ax, group_name in zip(axes_raw_groups, group_names):
        tracking_group = group_tracking[group_tracking["channel_group"] == group_name]

        for ch in sorted(tracking_group["measured_channel"].unique()):
            tracking_ch = tracking_group[
                tracking_group["measured_channel"] == ch
            ].sort_values("plot_cycle")
            ax.plot(
                tracking_ch["plot_cycle"],
                tracking_ch["adc"],
                linewidth=1.8,
                marker="o",
                markersize=2.5,
                label=f"Channel {int(ch)}",
            )

        ax.set_title(group_name)
        ax.set_xlabel("Complete cycle")
        ax.set_ylabel("Raw ADC")
        if raw_grouped_y_limits:
            ax.set_ylim(*raw_grouped_y_limits)
        ax.legend(frameon=False, fontsize=8)
        ax.grid(True)

    for ax in axes_raw_groups[len(group_names):]:
        ax.set_visible(False)

    fig_raw_groups.suptitle("Raw tracking ADC by channel group")
    fig_raw_groups.tight_layout()

leds = sorted(tracking_repeats_long["led_index"].dropna().unique())
max_measured_channel = int(tracking_repeats_long["measured_channel"].max())
for led_page, page_number, page_count in chunks(leds, 8):
    fig_led_channels, axes_led_channels = make_axes(
        len(led_page),
        figsize_per_col=4.8,
        figsize_per_row=3.5,
    )
    channel_line_groups = {}

    for ax, led in zip(axes_led_channels, led_page):
        tracking_led = tracking_repeats_long[tracking_repeats_long["led_index"] == led]
        adjacent_measured_channels = adjacent_channels(led, max_measured_channel)

        for ch in adjacent_measured_channels:
            tracking_ch = tracking_led[
                tracking_led["measured_channel"] == ch
            ].sort_values(["plot_cycle", "repeat"])
            if tracking_ch.empty:
                continue

            line, = ax.plot(
                tracking_ch["repeat_plot_cycle"],
                normalize_trace(tracking_ch["adc"]),
                linewidth=1.0,
                marker="o",
                markersize=1.8,
                alpha=0.75,
            )
            channel_line_groups.setdefault(f"Ch {int(ch)}", []).append(line)

        ax.set_title(f"LED {int(led)}")
        ax.set_xlabel("Complete cycle")
        ax.set_ylabel("Mean-centered ADC / variance")
        ax.grid(True)

    for ax in axes_led_channels[len(led_page):]:
        ax.set_visible(False)

    fig_led_channels.suptitle(
        f"Adjacent channel variance-normalized repeat readings by active LED ({page_number}/{page_count})"
    )
    fig_led_channels.tight_layout()
    add_visibility_checkboxes(fig_led_channels, channel_line_groups, "Channels")

measured_channels = sorted(tracking_repeats_long["measured_channel"].dropna().unique())
max_led = int(tracking_repeats_long["led_index"].max())
for channel_page, page_number, page_count in chunks(measured_channels, 8):
    fig_channel_leds, axes_channel_leds = make_axes(
        len(channel_page),
        figsize_per_col=4.8,
        figsize_per_row=3.5,
    )
    led_line_groups = {}

    for ax, ch in zip(axes_channel_leds, channel_page):
        tracking_channel = tracking_repeats_long[
            tracking_repeats_long["measured_channel"] == ch
        ]
        adjacent_leds = adjacent_channels(ch, max_led)

        for led in adjacent_leds:
            tracking_led = tracking_channel[
                tracking_channel["led_index"] == led
            ].sort_values(["plot_cycle", "repeat"])
            if tracking_led.empty:
                continue

            line, = ax.plot(
                tracking_led["repeat_plot_cycle"],
                normalize_trace(tracking_led["adc"]),
                linewidth=1.0,
                marker="o",
                markersize=1.8,
                alpha=0.75,
            )
            led_line_groups.setdefault(f"LED {int(led)}", []).append(line)

        ax.set_title(f"Channel {int(ch)}")
        ax.set_xlabel("Complete cycle")
        ax.set_ylabel("Mean-centered ADC / variance")
        ax.grid(True)

    for ax in axes_channel_leds[len(channel_page):]:
        ax.set_visible(False)

    fig_channel_leds.suptitle(
        f"Adjacent LED variance-normalized repeat readings by measured channel ({page_number}/{page_count})"
    )
    fig_channel_leds.tight_layout()
    add_visibility_checkboxes(fig_channel_leds, led_line_groups, "LEDs")

if "temperature_c" in tracking_df.columns:
    environment_df = (
        tracking_df.groupby("plot_cycle", as_index=False)
        .agg(
            temperature_c=("temperature_c", "mean"),
            **(
                {"humidity_percent": ("humidity_percent", "mean")}
                if "humidity_percent" in tracking_df.columns
                else {}
            ),
        )
        .dropna(subset=["temperature_c"])
    )

    if not environment_df.empty:
        fig_temperature, ax_temperature = plt.subplots(figsize=(9, 4.8))
        ax_temperature.plot(
            environment_df["plot_cycle"],
            environment_df["temperature_c"],
            linewidth=2,
            marker="o",
            markersize=3,
            label="Temperature",
        )
        ax_temperature.set_title("AHT temperature during tracking")
        ax_temperature.set_xlabel("Complete cycle")
        ax_temperature.set_ylabel("Temperature (C)")
        ax_temperature.grid(True)

        if "humidity_percent" in environment_df.columns:
            environment_df = environment_df.sort_values("plot_cycle").copy()
            ax_humidity = ax_temperature.twinx()
            ax_humidity.plot(
                environment_df["plot_cycle"],
                environment_df["humidity_percent"],
                linewidth=1.5,
                marker="o",
                markersize=3,
                color="tab:green",
                label="Humidity",
            )
            ax_humidity.set_ylabel("Humidity (%)")

            lines, labels = ax_temperature.get_legend_handles_labels()
            humidity_lines, humidity_labels = ax_humidity.get_legend_handles_labels()
            ax_temperature.legend(
                lines + humidity_lines,
                labels + humidity_labels,
                frameon=False,
            )
        else:
            ax_temperature.legend(frameon=False)

        fig_temperature.tight_layout()
plt.show()
