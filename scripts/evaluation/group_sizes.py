"""Group size distribution of the hit processor (thesis Results, entity extraction).

Reads the "Group Size Distribution" block of the extract log of a run and plots the
number of groups per group size (candidate hits sharing one span) on log-log axes.
"""
import argparse
import re
from pathlib import Path

import matplotlib.pyplot as plt

FIGURE = Path("/mnt/raidbio2/extstud/studtemp/mitsopoulos/bachelor-thesis/figures/group_sizes")


def read_group_sizes(log_path: Path) -> dict[int, int]:
    sizes, inside = {}, False
    for line in log_path.read_text().splitlines():
        if "Group Size Distribution:" in line:
            inside = True
        elif inside:
            m = re.search(r"size=(\d+)\s*:\s*(\d+)", line)
            if not m:
                break
            sizes[int(m.group(1))] = int(m.group(2))
    return sizes


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("log", type=Path, help="extract log of the run")
    args = parser.parse_args()

    sizes = read_group_sizes(args.log)
    x, y = zip(*sorted(sizes.items()))
    print(f"{sum(y):,} groups, {len(x)} distinct sizes, single-candidate share {sizes[1] / sum(y):.1%}")

    plt.rcParams.update({"font.size": 9, "pdf.fonttype": 42, "axes.spines.top": False, "axes.spines.right": False})
    fig, ax = plt.subplots(figsize=(4.8, 3.0), layout="constrained")
    ax.plot(x, y, "o", ms=3.5, color="#0072B2")
    ax.set_xscale("log")
    ax.set_yscale("log")
    ax.set_ylim(0.8, max(y) * 3)
    ax.set_xlabel("Group size (candidate hits per span)")
    ax.set_ylabel("Number of groups")
    ax.grid(axis="y", color="0.9", lw=0.6)
    ax.set_axisbelow(True)
    for size, text, ha in ((65, "C. elegans\n(65 taxa)", "center"), (6105, "uncharacterized\nprotein (gene)", "center"),
                           (12210, "same, every hit\nreported twice", "right")):
        if size in sizes:
            ax.annotate(text, (size, sizes[size]), xytext=(4 if ha == "right" else 0, 12), textcoords="offset points",
                        ha=ha, va="bottom", fontsize=7, color="0.3",
                        arrowprops=dict(arrowstyle="-", color="0.5", lw=0.6))
    fig.savefig(f"{FIGURE}.pdf")
    fig.savefig(f"{FIGURE}.png", dpi=200)
