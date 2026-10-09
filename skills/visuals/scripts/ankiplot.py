"""House style for card images.

import sys; sys.path.insert(0, "<plugin>/skills/visuals/scripts")
import ankiplot
fig, ax = ankiplot.figure()
ax.plot(...)
ankiplot.save(fig, "name.png")  # prints the absolute path for stage_image
"""

from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PALETTE = [
    "#0072B2",
    "#D55E00",
    "#009E73",
    "#CC79A7",
    "#E69F00",
    "#56B4E9",
]  # Okabe-Ito

plt.rcParams.update(
    {
        "figure.facecolor": "white",
        "axes.facecolor": "white",
        "axes.prop_cycle": plt.cycler(color=PALETTE),
        "axes.spines.top": False,
        "axes.spines.right": False,
        "axes.grid": True,
        "grid.alpha": 0.3,
        "font.size": 15,
        "axes.titlesize": 16,
        "lines.linewidth": 2.4,
        "savefig.dpi": 200,
    }
)


def figure(width: float = 6.0, height: float = 4.0):
    return plt.subplots(figsize=(width, height))


def save(fig, name: str, folder: str = ".") -> Path:
    path = Path(folder).expanduser() / name
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, bbox_inches="tight", facecolor="white")
    plt.close(fig)
    print(path.resolve())
    return path
