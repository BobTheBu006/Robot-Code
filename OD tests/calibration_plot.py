import matplotlib.pyplot as plt
import pandas as pd
import math


SUMMARY_PATH = "serial_logs/calibration_summary.csv"
SWEEP_PATH = "serial_logs/calibration_sweep.csv"


def make_axes(count, figsize_per_col=4.2, figsize_per_row=3.2):
    cols = min(4, max(1, count))
    rows = max(1, math.ceil(count / cols))
    fig, axes = plt.subplots(
        rows,
        cols,
        figsize=(figsize_per_col * cols, figsize_per_row * rows),
        sharex=True,
        sharey=True,
    )
    if hasattr(axes, "flat"):
        axes = list(axes.flat)
    else:
        axes = [axes]
    return fig, axes


summary_df = pd.read_csv(SUMMARY_PATH)
sweep_df = pd.read_csv(SWEEP_PATH)

leds = sorted(summary_df["led_index"].unique())
fig, axes = make_axes(len(leds))

for ax, led in zip(axes, leds):
    fit_row = summary_df[summary_df["led_index"] == led].iloc[0]
    led_data = sweep_df[sweep_df["led_index"] == led].sort_values("duty")

    slope = fit_row["fit_slope"]
    intercept = fit_row["fit_intercept"]
    fit_start = fit_row["linear_start_duty"]
    fit_end = fit_row["linear_end_duty"]
    r_squared = fit_row["fit_r_squared"]

    fit_x = pd.Series([led_data["duty"].min(), led_data["duty"].max()])
    fit_y = slope * fit_x + intercept

    ax.plot(
        led_data["duty"],
        led_data["main_adc"],
        marker="o",
        markersize=3,
        linewidth=1.5,
        label="Measured main ADC",
    )
    ax.plot(
        fit_x,
        fit_y,
        linestyle="--",
        linewidth=2,
        label=f"Fit: y={slope:.3f}x + {intercept:.1f}",
    )
    ax.axvspan(fit_start, fit_end, color="tab:gray", alpha=0.12, label="Fit range")

    ax.set_title(f"LED {int(led)}")
    ax.set_xlabel("PWM duty")
    ax.set_ylabel("ADC")
    ax.grid(True)
    ax.legend(title=f"R^2={r_squared:.4f}")

for ax in axes[len(leds):]:
    ax.set_visible(False)

fig.suptitle("Calibration Fit vs Measured Data by LED")
fig.tight_layout()
plt.show()
