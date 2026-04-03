#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
from matplotlib.colors import ListedColormap
from matplotlib.patches import Patch
from matplotlib.lines import Line2D


def parse_compartment_layout(layout: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for token in layout.split("|"):
        k, v = token.strip().split(":")
        out[k.strip().lower()] = int(v.strip().replace("C", ""))
    return out


def parse_sfi_map(sfi_text: str) -> dict[str, int]:
    out: dict[str, int] = {}
    for token in sfi_text.split():
        k, v = token.split(":")
        out[k.strip().lower()] = 1 if v.strip().upper() == "Y" else 0
    return out


def load_config_map(path: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with path.open("r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            rows.append(
                {
                    "id": row["ConfigID"],
                    "layout": parse_compartment_layout(row["CompartmentLayout"]),
                    "sfi": parse_sfi_map(row["SFI"]),
                    "REQ_mean": float(row.get("REQ_mean", 0.0)),
                    "REQ_std": float(row.get("REQ_std", 0.0)),
                    "GET_mean": float(row.get("GET_mean", 0.0)),
                    "GET_std": float(row.get("GET_std", 0.0)),
                    "SET_mean": float(row.get("SET_mean", 0.0)),
                    "SET_std": float(row.get("SET_std", 0.0)),
                }
            )
    rows.sort(key=lambda r: int(str(r["id"])[1:]))
    return rows


def setup_style() -> None:
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


def save_fig(fig: plt.Figure, out_file: Path, rect: list[float] | None = None) -> None:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    if rect is None:
        fig.tight_layout()
    else:
        fig.tight_layout(rect=rect)
    fig.savefig(out_file)
    plt.close(fig)


def plot_config(rows: list[dict[str, object]], libs: list[str], title: str, out_file: Path) -> None:
    n = len(rows)
    comp = np.zeros((len(libs), n), dtype=float)
    sfi = np.zeros((len(libs), n), dtype=float)
    for j, row in enumerate(rows):
        layout = row["layout"]
        sfi_map = row["sfi"]
        for i, lib in enumerate(libs):
            comp[i, j] = int(layout[lib.lower()])
            sfi[i, j] = float(sfi_map.get(lib.lower(), 0))

    fig, ax = plt.subplots(figsize=(16.0, 3.2), facecolor="white")
    cmap = ListedColormap(["#ffffff", "#bcd7f5", "#f4b6b6"])
    ax.imshow(comp, aspect="auto", cmap=cmap, vmin=1, vmax=3, interpolation="nearest")

    # Overlay solid triangle on cells where SFI is enabled.
    for i in range(len(libs)):
        for j in range(n):
            if sfi[i, j] > 0:
                ax.scatter(j, i, s=18, marker="^", c="#111111", edgecolors="#111111", linewidths=0.2, zorder=3)

    ax.set_title(title, fontsize=12, color="#262626", pad=6)
    ax.set_yticks(np.arange(len(libs)))
    ax.set_yticklabels([x.capitalize() for x in libs], fontsize=9, color="#262626")
    ax.set_xlabel("Config index (1..96)", fontsize=11, color="#262626")
    ax.set_xlim(-0.5, n - 0.5)
    ax.set_xticks(np.arange(n))
    ax.set_xticklabels([str(i) for i in range(1, n + 1)], rotation=90, fontsize=7, color="#262626")
    for spine in ax.spines.values():
        spine.set_linewidth(1.25)
        spine.set_color("#262626")
    ax.tick_params(axis="both", width=1.1, colors="#262626")
    legend_handles = [
        Patch(facecolor="#ffffff", edgecolor="#2f2f2f", label="Compartment 1"),
        Patch(facecolor="#bcd7f5", edgecolor="#2f2f2f", label="Compartment 2"),
        Patch(facecolor="#f4b6b6", edgecolor="#2f2f2f", label="Compartment 3"),
        Line2D([0], [0], marker="^", color="none", markerfacecolor="#111111", markeredgecolor="#111111", markersize=6, label="SFI enabled"),
    ]
    leg = ax.legend(
        handles=legend_handles,
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=4,
        frameon=True,
        edgecolor="#262626",
        framealpha=1.0,
        fancybox=False,
        fontsize=8,
    )
    leg.get_frame().set_linewidth(1.0)
    save_fig(fig, out_file, rect=[0, 0.04, 1, 1])


def plot_data(vals: list[float], errs: list[float], title: str, ylabel: str, out_file: Path) -> None:
    n = len(vals)
    x = np.arange(1, n + 1)
    fig, ax = plt.subplots(figsize=(16.0, 3.3), facecolor="white")
    ax.bar(
        x,
        vals,
        color="#4c78a8",
        alpha=0.95,
        edgecolor="#2f2f2f",
        linewidth=0.28,
    )
    ax.set_title(title, fontsize=12, color="#262626", pad=6)
    ax.set_ylabel(ylabel, fontsize=11, color="#262626")
    ax.set_xlabel("Config index (1..96)", fontsize=11, color="#262626")
    ax.set_xticks(x)
    ax.set_xticklabels([str(i) for i in x], rotation=90, fontsize=7, color="#262626")
    ax.set_xlim(0.5, n + 0.5)
    ax.margins(x=0.0)
    y_max = max(vals) * 1.14
    ax.set_ylim(0, y_max)
    for xi, yi in zip(x, vals):
        y_text = yi + 0.01 * y_max
        va = "bottom"
        if y_text > 0.98 * y_max:
            y_text = 0.98 * y_max
            va = "top"
        ax.text(
            xi,
            y_text,
            f"{yi/1000:.1f}k",
            rotation=90,
            ha="center",
            va=va,
            fontsize=8,
            fontweight="semibold",
            color="#262626",
        )
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.75, zorder=0)
    for spine in ax.spines.values():
        spine.set_linewidth(1.25)
        spine.set_color("#262626")
    ax.tick_params(axis="both", width=1.1, colors="#262626")
    save_fig(fig, out_file)


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate split fig06 plots (2 config + 3 data)")
    parser.add_argument("--output-root", required=True, help="Absolute or relative output root directory")
    parser.add_argument("--formats", nargs="+", default=["svg", "png"], help="Output formats")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent
    out_root = Path(args.output_root).resolve()
    setup_style()

    project_root = root.parents[2]
    nginx_rows = load_config_map(project_root / "search/data/nginx_config_map.csv")
    redis_rows = load_config_map(project_root / "search/data/redis_config_map.csv")

    if len(nginx_rows) != 96 or len(redis_rows) != 96:
        print(f"[warn] expected 96 configs, found nginx={len(nginx_rows)} redis={len(redis_rows)}")

    nginx_req_mean = [float(r["REQ_mean"]) for r in nginx_rows]
    nginx_req_std = [float(r["REQ_std"]) for r in nginx_rows]
    redis_get_mean = [float(r["GET_mean"]) for r in redis_rows]
    redis_get_std = [float(r["GET_std"]) for r in redis_rows]
    redis_set_mean = [float(r["SET_mean"]) for r in redis_rows]
    redis_set_std = [float(r["SET_std"]) for r in redis_rows]

    for fmt in args.formats:
        fmt = fmt.lower().strip(".")
        if fmt not in {"svg", "png"}:
            raise ValueError(f"Unsupported format: {fmt}")

        plot_config(
            nginx_rows,
            ["nginx", "newlib", "uksched", "lwip"],
            "Nginx configuration map",
            out_root / "fig-06_nginx-config" / f"fig-06_nginx-config.{fmt}",
        )
        plot_config(
            redis_rows,
            ["redis", "newlib", "uksched", "lwip"],
            "Redis configuration map",
            out_root / "fig-06_redis-config" / f"fig-06_redis-config.{fmt}",
        )
        plot_data(
            nginx_req_mean,
            nginx_req_std,
            "Nginx REQ throughput across configurations",
            "REQ / s",
            out_root / "fig-06_nginx-req" / f"fig-06_nginx-req.{fmt}",
        )
        plot_data(
            redis_get_mean,
            redis_get_std,
            "Redis GET throughput across configurations",
            "GET / s",
            out_root / "fig-06_redis-get" / f"fig-06_redis-get.{fmt}",
        )
        plot_data(
            redis_set_mean,
            redis_set_std,
            "Redis SET throughput across configurations",
            "SET / s",
            out_root / "fig-06_redis-set" / f"fig-06_redis-set.{fmt}",
        )

    print("Done generating fig06 split plots")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
