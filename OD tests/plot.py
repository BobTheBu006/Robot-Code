from math import ceil
from pathlib import Path
import re

import matplotlib.pyplot as plt
import pandas as pd


BASE_DIR = Path(__file__).resolve().parent
LOG_BASE_DIR = BASE_DIR / "serial_logs"
PLOTS_PER_PAGE = 12


def latest_log_file(filename):
    candidates = []
    if LOG_BASE_DIR.exists():
        candidates.extend(path / filename for path in LOG_BASE_DIR.iterdir() if path.is_dir())
    candidates.append(LOG_BASE_DIR / filename)
    candidates.append(BASE_DIR / "sweep.csv")

    existing = [path for path in candidates if path.exists()]
    if not existing:
        return BASE_DIR / "sweep.csv"

    return max(existing, key=lambda path: (path.stat().st_mtime, path.parent.name))


file_path = latest_log_file("calibration_sweep.csv")


def channel_number(column_name):
    match = re.match(r"ch(\d+)(?:_|$)", column_name)
    if not match:
        return None
    return int(match.group(1))


def subplot_grid(count):
    cols = min(4, max(1, count))
    rows = ceil(count / cols)
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(4.8 * cols, 3.6 * rows),
        sharex=True,
        sharey=True,
    )
    if count == 1:
        axes = [axes]
    else:
        axes = list(axes.flat)
    return fig, axes


def chunks(values, size):
    for start in range(0, len(values), size):
        yield values[start:start + size], (start // size) + 1, ceil(len(values) / size)


df = pd.read_csv(file_path)
df.columns = [col.strip() for col in df.columns]

if "led_index" not in df.columns and "active_led" in df.columns:
    df = df.rename(columns={"active_led": "led_index"})

required_columns = {"led_index", "duty"}
missing_columns = required_columns - set(df.columns)
if missing_columns:
    raise ValueError(f"{file_path} is missing required columns: {sorted(missing_columns)}")

channel_columns = sorted(
    [col for col in df.columns if channel_number(col) is not None],
    key=channel_number,
)
if not channel_columns:
    raise ValueError(f"{file_path} has no channel columns named like ch0 or ch0_pa0")

numeric_columns = ["led_index", "duty", *channel_columns]
if "repeat" in df.columns:
    numeric_columns.append("repeat")
if "main_adc" in df.columns:
    numeric_columns.append("main_adc")

for col in numeric_columns:
    df[col] = pd.to_numeric(df[col], errors="coerce")

df = df.dropna(subset=["led_index", "duty", *channel_columns])
if df.empty:
    raise ValueError(f"{file_path} has no valid numeric sweep rows to plot")

id_vars = ["led_index", "duty"]
if "repeat" in df.columns:
    id_vars.append("repeat")
if "main_adc" in df.columns:
    id_vars.append("main_adc")

long_df = df.melt(
    id_vars=id_vars,
    value_vars=channel_columns,
    var_name="measured_channel",
    value_name="adc",
)
long_df["measured_channel"] = long_df["measured_channel"].map(channel_number)

mean_df = long_df.groupby(
    ["led_index", "measured_channel", "duty"], as_index=False
)["adc"].mean()
if mean_df.empty:
    raise ValueError(f"{file_path} has no channel data to plot")

print(
    f"Loaded {len(df)} sweep rows from {file_path}; "
    f"LEDs: {', '.join(str(int(led)) for led in sorted(df['led_index'].unique()))}; "
    f"channels: {len(channel_columns)}"
)

channels = sorted(mean_df["measured_channel"].unique())
for channel_page, page_number, page_count in chunks(channels, PLOTS_PER_PAGE):
    fig, axes = subplot_grid(len(channel_page))

    for ax, ch in zip(axes, channel_page):
        sub_mean = mean_df[mean_df["measured_channel"] == ch]

        for led in sorted(sub_mean["led_index"].unique()):
            led_data = sub_mean[sub_mean["led_index"] == led].sort_values("duty")

            label = f"LED {int(led)}"
            if int(led) == int(ch):
                label += " (main)"

            ax.plot(
                led_data["duty"],
                led_data["adc"],
                linewidth=1.8,
                marker="o",
                markersize=2.5,
                label=label,
            )

        ax.set_title(f"Channel {int(ch)}")
        ax.set_xlabel("PWM duty")
        ax.set_ylabel("ADC")
        ax.legend(fontsize="small")
        ax.grid(True)

    for ax in axes[len(channel_page):]:
        ax.set_visible(False)

    fig.suptitle(f"PWM vs ADC by measured channel ({page_number}/{page_count})")
    fig.tight_layout()

leds = sorted(mean_df["led_index"].unique())
for led_page, page_number, page_count in chunks(leds, PLOTS_PER_PAGE):
    fig_led, axes_led = subplot_grid(len(led_page))

    for ax, led in zip(axes_led, led_page):
        sub_mean = mean_df[mean_df["led_index"] == led]

        for ch in sorted(sub_mean["measured_channel"].unique()):
            ch_data = sub_mean[sub_mean["measured_channel"] == ch].sort_values("duty")

            label = f"Channel {int(ch)}"
            if int(ch) == int(led):
                label += " (main)"

            ax.plot(
                ch_data["duty"],
                ch_data["adc"],
                linewidth=1.8,
                marker="o",
                markersize=2.5,
                label=label,
            )

        ax.set_title(f"LED {int(led)}")
        ax.set_xlabel("PWM duty")
        ax.set_ylabel("ADC")
        ax.legend(fontsize="small")
        ax.grid(True)

    for ax in axes_led[len(led_page):]:
        ax.set_visible(False)

    fig_led.suptitle(f"PWM vs ADC by active LED ({page_number}/{page_count})")
    fig_led.tight_layout()

if "main_adc" in df.columns:
    fig_main, ax_main = plt.subplots(figsize=(9, 5))
    for led in sorted(df["led_index"].unique()):
        led_data = df[df["led_index"] == led].sort_values("duty")
        ax_main.plot(
            led_data["duty"],
            led_data["main_adc"],
            linewidth=2,
            marker="o",
            markersize=3,
            label=f"LED {int(led)} main ADC",
        )

    ax_main.set_title("Calibration sweep main ADC")
    ax_main.set_xlabel("PWM duty")
    ax_main.set_ylabel("Main ADC")
    ax_main.legend(frameon=False)
    ax_main.grid(True)
    fig_main.tight_layout()

plt.show()
