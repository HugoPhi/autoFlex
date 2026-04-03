#!/usr/bin/env python3

import argparse
from typing import List, Tuple

import matplotlib.pyplot as plt
import numpy as np
from pathlib import Path


def load_iperf_blocks(data_file: Path) -> List[Tuple[np.ndarray, np.ndarray]]:
    blocks: List[Tuple[np.ndarray, np.ndarray]] = []
    cur_x: list[float] = []
    cur_y: list[float] = []
    with data_file.open("r", encoding="utf-8") as f:
        for line in f:
            s = line.strip()
            if not s:
                if cur_x:
                    blocks.append((np.array(cur_x, dtype=float), np.array(cur_y, dtype=float)))
                    cur_x, cur_y = [], []
                continue
            if s.startswith("#"):
                continue
            parts = s.split()
            if len(parts) >= 2:
                cur_x.append(float(parts[0]))
                cur_y.append(float(parts[1]))
    if cur_x:
        blocks.append((np.array(cur_x, dtype=float), np.array(cur_y, dtype=float)))
    return blocks


def render_grouped_bar(data_file: Path, out_file: Path) -> None:
    blocks = load_iperf_blocks(data_file)
    if len(blocks) < 5:
        raise RuntimeError(f"Expected 5 data blocks in {data_file}, got {len(blocks)}")

    # Keep the original ordering used by the previous line plot.
    order = [0, 1, 3, 2, 4]
    labels = ["Unikraft", "FlexOS NONE", "FlexOS MPK2-light", "FlexOS MPK2-dss", "FlexOS EPT2"]
    colors = ["#4c78a8", "#1f9d8a", "#72b7b2", "#e67e22", "#d95f02"]
    hatches = ["//////", "\\\\\\", "xxxx", "++++", "...."]

    x_sizes = blocks[0][0].astype(int)
    series = [blocks[i][1] for i in order]
    n_groups = len(x_sizes)
    n_series = len(series)

    bar_w = 0.14
    gap = 0.18
    group_w = n_series * bar_w + gap
    base = np.arange(n_groups) * group_w

    plt.rcParams.update(
        {
            "font.family": "Times New Roman",
            "mathtext.fontset": "custom",
            "mathtext.rm": "Times New Roman",
            "mathtext.it": "Times New Roman:italic",
            "mathtext.bf": "Times New Roman:bold",
            "axes.edgecolor": "#262626",
            "axes.linewidth": 1.1,
            "xtick.color": "#262626",
            "ytick.color": "#262626",
            "text.color": "#262626",
            "svg.fonttype": "none",
        }
    )

    fig, ax = plt.subplots(figsize=(10.6, 3.3), facecolor="white")
    for i, y in enumerate(series):
        ax.bar(
            base + i * bar_w,
            y,
            width=bar_w,
            facecolor="white",
            edgecolor=colors[i],
            linewidth=0.9,
            hatch=hatches[i],
            label=labels[i],
            zorder=3,
        )

    centers = base + (n_series - 1) * bar_w / 2
    exponents = [int(np.log2(v)) for v in x_sizes]
    ax.set_xticks(centers)
    ax.set_xticklabels([f"$2^{{{e}}}$" for e in exponents], rotation=0, fontsize=10)
    ax.set_ylabel("iPerf throughput (Gb/s)", fontsize=11)
    ax.set_xlabel("Receive Buffer Size", fontsize=11)
    ax.set_ylim(0, 6)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8, zorder=0)
    ax.tick_params(axis="both", width=1.1)
    for spine in ax.spines.values():
        spine.set_linewidth(1.1)
        spine.set_color("#262626")

    leg = ax.legend(
        loc="upper right",
        ncol=1,
        frameon=True,
        facecolor="white",
        edgecolor="#111111",
        framealpha=1.0,
        fancybox=False,
    )
    leg.get_frame().set_linewidth(1.0)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(out_file)
    plt.close(fig)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate fig09 iPerf grouped bar plot")
    parser.add_argument("--gnuplot", default="gnuplot", help="gnuplot executable")
    parser.add_argument("--output-root", required=True, help="Output root directory")
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["svg", "png"],
        help="Output formats to generate (default: svg png)",
    )
    args = parser.parse_args()
    out_root = Path(args.output_root).resolve()

    root = Path(__file__).resolve().parent
    data_file = root / "results/iperf.dat"

    for fmt in args.formats:
        fmt = fmt.lower().strip(".")
        if fmt not in {"svg", "png"}:
            raise ValueError(f"Unsupported format: {fmt}")

        out_file = out_root / "fig-09_iperf-throughput" / f"fig-09_iperf-throughput.{fmt}"
        render_grouped_bar(data_file, out_file)

    print("Done generating fig09 plot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
