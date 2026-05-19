"""
sensitivity_plot.py
-------------------
Generates the 'knee' graph for the linger-window sensitivity sweep.

Reads `sensitivity.csv` (columns: linger_window, completed_journeys) from the
same directory and writes `sensitivity_graph.png` at 300 DPI.
"""

from pathlib import Path

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
HERE = Path(__file__).resolve().parent
CSV_PATH = HERE / "sensitivity.csv"
OUTPUT_PATH = HERE / "sensitivity_graph.png"
OPTIMAL_X = 300  # seconds — the "knee" of the curve


# ---------------------------------------------------------------------------
# Academic / minimalist style
# ---------------------------------------------------------------------------
plt.rcParams.update({
    "font.family":      "serif",
    "font.serif":       ["DejaVu Serif", "Times New Roman", "Times"],
    "font.size":        11,
    "axes.titlesize":   14,
    "axes.titleweight": "bold",
    "axes.labelsize":   12,
    "axes.labelweight": "regular",
    "axes.spines.top":   False,
    "axes.spines.right": False,
    "axes.edgecolor":    "#333333",
    "axes.linewidth":    1.0,
    "xtick.direction":   "out",
    "ytick.direction":   "out",
    "xtick.color":       "#333333",
    "ytick.color":       "#333333",
    "grid.color":        "#cccccc",
    "grid.linestyle":    "--",
    "grid.linewidth":    0.6,
    "legend.frameon":    False,
})


# ---------------------------------------------------------------------------
# Load and sort data
# ---------------------------------------------------------------------------
df = (
    pd.read_csv(CSV_PATH)
      .sort_values("linger_window")
      .reset_index(drop=True)
)

required = {"linger_window", "completed_journeys"}
missing = required - set(df.columns)
if missing:
    raise ValueError(f"sensitivity.csv is missing required columns: {missing}")


# ---------------------------------------------------------------------------
# Figure
# ---------------------------------------------------------------------------
fig, ax = plt.subplots(figsize=(9, 5.5))

ax.plot(
    df["linger_window"],
    df["completed_journeys"],
    color="#1f4e79",
    linewidth=1.8,
    marker="o",
    markersize=6,
    markerfacecolor="#ffffff",
    markeredgecolor="#1f4e79",
    markeredgewidth=1.4,
    label="Completed Journeys",
    zorder=3,
)


# ---------------------------------------------------------------------------
# Annotate the optimal threshold
# ---------------------------------------------------------------------------
# Use the exact y if x = 300 exists in the data; otherwise interpolate.
if OPTIMAL_X in df["linger_window"].values:
    optimal_y = float(
        df.loc[df["linger_window"] == OPTIMAL_X, "completed_journeys"].iloc[0]
    )
else:
    optimal_y = float(
        np.interp(OPTIMAL_X, df["linger_window"], df["completed_journeys"])
    )

# Vertical reference line
ax.axvline(
    x=OPTIMAL_X,
    color="#c0392b",
    linestyle="--",
    linewidth=1.2,
    alpha=0.7,
    zorder=2,
)

# Highlight circle around the optimal point
ax.scatter(
    [OPTIMAL_X], [optimal_y],
    s=200,
    facecolors="none",
    edgecolors="#c0392b",
    linewidths=2.0,
    zorder=4,
)

# Annotation arrow + label
y_range = df["completed_journeys"].max() - df["completed_journeys"].min()
ax.annotate(
    "Optimal Threshold (300s)",
    xy=(OPTIMAL_X, optimal_y),
    xytext=(OPTIMAL_X + 80, optimal_y - 0.18 * y_range),
    fontsize=11,
    fontweight="bold",
    color="#c0392b",
    arrowprops=dict(
        arrowstyle="->",
        color="#c0392b",
        linewidth=1.4,
        connectionstyle="arc3,rad=0.18",
    ),
)


# ---------------------------------------------------------------------------
# Labels, title, grid
# ---------------------------------------------------------------------------
ax.set_title(
    "Sensitivity Sweep: Linger Window vs. Completed Journeys",
    pad=14,
)
ax.set_xlabel("Linger Window (seconds)")
ax.set_ylabel("Completed Journeys")
ax.grid(True, axis="both", zorder=1)
ax.set_axisbelow(True)
ax.legend(loc="lower right")

fig.tight_layout()


# ---------------------------------------------------------------------------
# Save
# ---------------------------------------------------------------------------
fig.savefig(OUTPUT_PATH, dpi=300, bbox_inches="tight")
print(f"Saved figure to: {OUTPUT_PATH}")