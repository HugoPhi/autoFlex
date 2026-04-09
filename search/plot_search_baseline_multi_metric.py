#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def render(agg_csv: Path, out_file: Path, metric: str) -> None:
    rows = load_rows(agg_csv)
    datasets = ["nginx:REQ", "redis:GET", "redis:SET"]
    methods = ["exhaustive", "random", "balanced"]

    field_map = {
        "query_ratio": ("mean_query_ratio", "Mean Query Ratio (queried / exhaustive)", "Average Query Ratio Across Thresholds & Seeds", (0.0, 1.08)),
        "first_result_query": (
            "mean_first_result_query",
            "Mean First-Result Query Count",
            "Average First-Result Query Count Across Thresholds & Seeds",
            None,
        ),
    }
    if metric not in field_map:
        raise ValueError(f"Unsupported metric: {metric}")

    value_field, ylabel, title, ylim = field_map[metric]
    std_field = "std_query_ratio" if metric == "query_ratio" else "std_first_result_query"

    table: dict[tuple[str, str], float] = {}
    err_table: dict[tuple[str, str], float] = {}
    for r in rows:
        d = r.get("dataset", "")
        m = r.get("search_method", "")
        if d in datasets and m in methods:
            table[(d, m)] = float(r[value_field])
            err_table[(d, m)] = float(r.get(std_field, "0") or 0.0)

    for d in datasets:
        for m in methods:
            if (d, m) not in table:
                raise ValueError(f"Missing aggregated row for dataset={d}, method={m}")

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

    style = {
        "exhaustive": {"facecolor": "#f0f0f0", "edgecolor": "#262626", "hatch": "////", "linewidth": 0.9, "label": "Exhaustive"},
        "random": {"facecolor": "#f9e3d2", "edgecolor": "#dd8452", "hatch": "++", "linewidth": 0.9, "label": "Random-candidate"},
        "balanced": {"facecolor": "#d6f0d1", "edgecolor": "#2e8b57", "hatch": "....", "linewidth": 1.1, "label": "Balanced (Ours)"},
    }

    fig, ax = plt.subplots(figsize=(9.4, 3.8), facecolor="white")

    for idx, m in enumerate(methods):
        vals = [table[(d, m)] for d in datasets]
        errs = [err_table[(d, m)] for d in datasets]
        xpos = x + (idx - 1.5) * width
        bars = ax.bar(xpos, vals, width=width, zorder=3, label=style[m]["label"],
                      facecolor=style[m]["facecolor"], edgecolor=style[m]["edgecolor"], hatch=style[m]["hatch"], linewidth=style[m]["linewidth"])
        ax.errorbar(xpos, vals, yerr=errs, fmt="none", ecolor="#262626", elinewidth=0.8, capsize=2, capthick=0.8, zorder=4)
        top = max(vals) if vals else 1.0
        for b, v in zip(bars, vals):
            offset = 0.02 if metric == "query_ratio" else max(top * 0.02, 0.6)
            ax.text(
                b.get_x() + b.get_width() / 2,
                v + offset,
                f"{v:.2f}",
                ha="center",
                va="bottom",
                fontsize=8,
            )

    ax.set_xticks(x)
    ax.set_xticklabels(["Nginx-REQ", "Redis-GET", "Redis-SET"], fontsize=10)
    ax.set_ylabel(ylabel, fontsize=11)
    if ylim is not None:
        ax.set_ylim(*ylim)
    else:
        max_v = max(table.values())
        ax.set_ylim(0, max_v * 1.22)

    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8, zorder=0)

    leg = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.26),
        ncol=3,
        frameon=True,
        edgecolor="#262626",
        framealpha=1.0,
        fancybox=False,
        fontsize=9,
    )
    leg.get_frame().set_linewidth(1.0)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.18, 1, 1])
    fig.savefig(out_file, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description="Plot aggregated baseline comparison metrics")
    p.add_argument("--agg-csv", required=True)
    p.add_argument("--metric", choices=["query_ratio", "first_result_query"], required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    render(Path(args.agg_csv).resolve(), Path(args.output).resolve(), args.metric)
    print(f"Generated metric plot: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
