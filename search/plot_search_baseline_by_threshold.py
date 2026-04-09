#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def threshold_key(text: str) -> float:
    return float(text)


def render(detail_csv: Path, metric: str, out_file: Path) -> None:
    rows = load_rows(detail_csv)
    datasets = ["nginx:REQ", "redis:GET", "redis:SET"]
    methods = ["exhaustive", "random", "balanced"]

    field_map = {
        "query_ratio": (
            "query_ratio",
            "Mean Query Ratio (over seeds)",
            "Query Ratio by Threshold (mean over seeds)",
            (0.0, 1.25),
        ),
        "first_result_query": (
            "first_result_query",
            "Mean First-Result Query (over seeds)",
            "First-Result Query by Threshold (mean over seeds)",
            None,
        ),
    }
    if metric not in field_map:
        raise ValueError(f"Unsupported metric: {metric}")

    value_field, ylabel, title, ylim = field_map[metric]

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

    style = {
        "exhaustive": {"facecolor": "#f0f0f0", "edgecolor": "#262626", "hatch": "////", "linewidth": 0.9, "label": "Exhaustive"},
        "random": {"facecolor": "#f9e3d2", "edgecolor": "#dd8452", "hatch": "++", "linewidth": 0.9, "label": "Random-candidate"},
        "balanced": {"facecolor": "#d6f0d1", "edgecolor": "#2e8b57", "hatch": "....", "linewidth": 1.1, "label": "Balanced (Ours)"},
    }

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 3.6), facecolor="white", sharey=False)

    global_max = 0.0
    for d in datasets:
        for r in rows:
            if r.get("dataset") == d and r.get("search_method") in methods:
                global_max = max(global_max, float(r[value_field]))

    for ax, dataset in zip(axes, datasets):
        drows = [r for r in rows if r.get("dataset") == dataset and r.get("search_method") in methods]
        if not drows:
            raise ValueError(f"No rows for dataset: {dataset}")

        thresholds = sorted({r["threshold"] for r in drows}, key=threshold_key)
        rotate_labels = len(thresholds) >= 5
        x = np.arange(len(thresholds))
        width = 0.18

        for idx, method in enumerate(methods):
            vals = []
            for th in thresholds:
                bucket = [float(r[value_field]) for r in drows if r["threshold"] == th and r["search_method"] == method]
                if not bucket:
                    raise ValueError(f"Missing values for dataset={dataset}, threshold={th}, method={method}")
                vals.append(sum(bucket) / len(bucket))

            xpos = x + (idx - 1.5) * width
            bars = ax.bar(
                xpos,
                vals,
                width=width,
                zorder=3,
                label=style[method]["label"],
                facecolor=style[method]["facecolor"],
                edgecolor=style[method]["edgecolor"],
                hatch=style[method]["hatch"],
                linewidth=style[method]["linewidth"],
            )

            top = max(vals) if vals else 1.0
            # Stagger labels by method index to avoid overlaps when bar heights are very close.
            base = 0.012 if metric == "query_ratio" else max(top * 0.012, 0.25)
            stagger = idx * (0.010 if metric == "query_ratio" else max(top * 0.010, 0.15))
            offset = base + stagger
            for b, v in zip(bars, vals):
                ax.text(
                    b.get_x() + b.get_width() / 2,
                    v + offset,
                    f"{v:.2f}",
                    ha="center",
                    va="bottom",
                    rotation=90 if rotate_labels else 0,
                    fontsize=6.5,
                )

        ax.set_xticks(x)
        ax.set_xticklabels([f"{int(float(t))/1000:.0f}k" for t in thresholds], fontsize=9)
        ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8, zorder=0)
        ax.set_xlabel("Threshold", fontsize=10)

        if ylim is not None:
            ax.set_ylim(*ylim)
        else:
            ax.set_ylim(0, max(1.2, global_max * 1.22))

    axes[0].set_ylabel(ylabel, fontsize=11)

    handles, labels = axes[0].get_legend_handles_labels()
    leg = fig.legend(
        handles,
        labels,
        loc="upper center",
        bbox_to_anchor=(0.5, 0.055),
        ncol=3,
        frameon=True,
        edgecolor="#262626",
        framealpha=1.0,
        fancybox=False,
        fontsize=9,
    )
    leg.get_frame().set_linewidth(1.0)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.14, 1, 0.93])
    fig.savefig(out_file, bbox_inches="tight", pad_inches=0.08)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description="Plot baseline comparison by threshold with per-threshold seed means")
    p.add_argument("--detail-csv", required=True)
    p.add_argument("--metric", choices=["query_ratio", "first_result_query"], required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()

    render(Path(args.detail_csv).resolve(), args.metric, Path(args.output).resolve())
    print(f"Generated threshold panel plot: {Path(args.output).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
