#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_rows(summary_csv: Path) -> list[dict[str, str]]:
    with summary_csv.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def render(summary_csv: Path, out_file: Path) -> None:
    rows = load_rows(summary_csv)
    if not rows:
        raise ValueError(f"Empty summary CSV: {summary_csv}")

    datasets = ["nginx:REQ", "redis:GET", "redis:SET"]
    methods = ["exhaustive", "worst", "random", "balanced"]
    labels = {
        "exhaustive": "Exhaustive",
        "worst": "Worst-split",
        "random": "Random-candidate",
        "balanced": "Balanced (Ours)",
    }

    table: dict[tuple[str, str], float] = {}
    for r in rows:
        dataset = r.get("dataset", "")
        method = r.get("search_method", "")
        if dataset in datasets and method in methods:
            table[(dataset, method)] = float(r["query_ratio"])

    for d in datasets:
        for m in methods:
            if (d, m) not in table:
                raise ValueError(f"Missing row for dataset={d}, method={m}")

    plt.rcParams.update(
        {
            "font.family": "Times New Roman",
            "axes.edgecolor": "#262626",
            "axes.linewidth": 1.1,
            "xtick.color": "#262626",
            "ytick.color": "#262626",
            "text.color": "#262626",
            "svg.fonttype": "none",
        }
    )

    x = np.arange(len(datasets))
    width = 0.18

    fig, ax = plt.subplots(figsize=(9.2, 3.6), facecolor="white")

    style = {
        "exhaustive": {"facecolor": "#f0f0f0", "edgecolor": "#262626", "hatch": "////", "linewidth": 0.9},
        "worst": {"facecolor": "#dbe9f6", "edgecolor": "#4c78a8", "hatch": "xx", "linewidth": 0.9},
        "random": {"facecolor": "#f9e3d2", "edgecolor": "#dd8452", "hatch": "++", "linewidth": 0.9},
        "balanced": {"facecolor": "#d6f0d1", "edgecolor": "#2e8b57", "hatch": "....", "linewidth": 1.1},
    }

    for idx, m in enumerate(methods):
        vals = [table[(d, m)] for d in datasets]
        xpos = x + (idx - 1.5) * width
        bars = ax.bar(
            xpos,
            vals,
            width=width,
            label=labels[m],
            zorder=3,
            **style[m],
        )
        for b, v in zip(bars, vals):
            ax.text(
                b.get_x() + b.get_width() / 2,
                min(v + 0.02, 1.05),
                f"{v:.2f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(["Nginx-REQ", "Redis-GET", "Redis-SET"], fontsize=10)
    ax.set_ylim(0, 1.08)
    ax.set_ylabel("Query Ratio (queried / exhaustive)", fontsize=11)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8, zorder=0)

    leg = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.16),
        ncol=4,
        frameon=True,
        edgecolor="#262626",
        framealpha=1.0,
        fancybox=False,
        fontsize=9,
    )
    leg.get_frame().set_linewidth(1.0)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.07, 1, 1])
    fig.savefig(out_file)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description="Plot search baseline comparison from dag_search_summary.csv")
    p.add_argument("--summary-csv", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    render(Path(args.summary_csv).resolve(), Path(args.output).resolve())
    print(f"Generated comparison plot: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
