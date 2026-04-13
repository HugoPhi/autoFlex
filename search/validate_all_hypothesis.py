#!/usr/bin/env python3

import argparse
import csv
import os
from dataclasses import dataclass
from statistics import mean
from typing import Dict, List, Sequence, Tuple

import hypothesis
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.patches import Rectangle
from matplotlib.ticker import FuncFormatter

plt.rcParams["font.family"] = "Times New Roman"

Edge = Tuple[str, str]


@dataclass
class ConfigRow:
    config_id: str
    comp: Dict[str, int]
    sfi: Dict[str, int]
    metrics: Dict[str, float]


def parse_compartment_layout(text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for chunk in text.split("|"):
        chunk = chunk.strip()
        if not chunk or ":C" not in chunk:
            continue
        lib, raw = chunk.split(":C", 1)
        out[lib.strip()] = int(raw.strip())
    return out


def parse_sfi_layout(text: str) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for token in text.split():
        if ":" not in token:
            continue
        lib, yn = token.split(":", 1)
        out[lib.strip()] = 1 if yn.strip().upper() == "Y" else 0
    return out


def load_config_rows(path: str, methods: Sequence[str]) -> List[ConfigRow]:
    rows: List[ConfigRow] = []
    with open(path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            metrics: Dict[str, float] = {}
            for m in methods:
                key = f"{m}_mean"
                if key not in row:
                    raise ValueError(f"Missing column '{key}' in {path}")
                metrics[m] = float(row[key])

            rows.append(
                ConfigRow(
                    config_id=row["ConfigID"].strip(),
                    comp=parse_compartment_layout(row["CompartmentLayout"]),
                    sfi=parse_sfi_layout(row["SFI"]),
                    metrics=metrics,
                )
            )
    return rows


def leq(a: ConfigRow, b: ConfigRow, libs: Sequence[str]) -> bool:
    for lib in libs:
        if a.comp[lib] > b.comp[lib]:
            return False
        if a.sfi[lib] > b.sfi[lib]:
            return False
    return True


def strict_less(a: ConfigRow, b: ConfigRow, libs: Sequence[str]) -> bool:
    if not leq(a, b, libs):
        return False
    for lib in libs:
        if a.comp[lib] < b.comp[lib] or a.sfi[lib] < b.sfi[lib]:
            return True
    return False


def build_cover_edges(configs: List[ConfigRow]) -> List[Edge]:
    libs = sorted(configs[0].comp.keys())
    candidates: List[Tuple[int, int]] = []
    for i, a in enumerate(configs):
        for j, b in enumerate(configs):
            if i == j:
                continue
            if strict_less(a, b, libs):
                candidates.append((i, j))

    cover: List[Edge] = []
    for i, j in candidates:
        is_cover = True
        for k, c in enumerate(configs):
            if k == i or k == j:
                continue
            if strict_less(configs[i], c, libs) and strict_less(c, configs[j], libs):
                is_cover = False
                break
        if is_cover:
            cover.append((configs[i].config_id, configs[j].config_id))

    return sorted(set(cover), key=lambda x: (x[0], x[1]))


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def write_csv(path: str, header: Sequence[str], rows: Sequence[Sequence[object]]) -> None:
    ensure_parent(path)
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.writer(f)
        w.writerow(list(header))
        for row in rows:
            w.writerow(list(row))


def evaluate_series(app: str, method: str, edges: List[Edge], perf: Dict[str, float], epsilon: float, epsilon_mode: str) -> dict:
    violations, missing = hypothesis.check_edge_hypothesis(
        edges=edges,
        performance=perf,
        epsilon=epsilon,
        epsilon_mode=epsilon_mode,
    )
    violations = sorted(violations, key=lambda x: x["gap"], reverse=True)
    gaps = [v["gap"] for v in violations]
    return {
        "app": app,
        "method": method,
        "total_edges": len(edges),
        "performance_entries": len(perf),
        "epsilon": epsilon,
        "epsilon_mode": epsilon_mode,
        "violation_count": len(violations),
        "missing_count": len(missing),
        "max_gap": max(gaps) if gaps else 0.0,
        "mean_gap": mean(gaps) if gaps else 0.0,
        "violations": violations,
        "missing": [{"src": s, "dst": d} for s, d in missing],
    }


def build_edge_points(edges: List[Edge], perf: Dict[str, float]) -> List[dict]:
    points: List[dict] = []
    for src, dst in edges:
        if src not in perf or dst not in perf:
            continue
        a_perf = float(perf[src])
        b_perf = float(perf[dst])
        points.append(
            {
                "src": src,
                "dst": dst,
                "a_perf": a_perf,
                "b_perf": b_perf,
                "delta": b_perf - a_perf,
                "on_or_below": b_perf <= a_perf,
            }
        )
    return points


def _fmt_k(v: float) -> str:
    return f"{v / 1000.0:.1f}k"


def _draw_scatter_panel(
    lines: List[str],
    *,
    points: List[dict],
    x0: float,
    y0: float,
    w: float,
    h: float,
) -> None:
    pad_l = 52.0
    pad_r = 14.0
    pad_t = 26.0
    pad_b = 34.0
    px0 = x0 + pad_l
    py0 = y0 + pad_t
    pw = w - pad_l - pad_r
    ph = h - pad_t - pad_b

    if points:
        vals = [p["a_perf"] for p in points] + [p["b_perf"] for p in points]
        vmin = min(vals)
        vmax = max(vals)
    else:
        vmin, vmax = 0.0, 1.0

    span = max(vmax - vmin, 1.0)
    lo = max(0.0, vmin - span * 0.08)
    hi = vmax + span * 0.08
    if hi <= lo:
        hi = lo + 1.0

    def mx(v: float) -> float:
        return px0 + (v - lo) / (hi - lo) * pw

    def my(v: float) -> float:
        return py0 + ph - (v - lo) / (hi - lo) * ph

    lines.append(f'<rect x="{x0:.1f}" y="{y0:.1f}" width="{w:.1f}" height="{h:.1f}" fill="white" stroke="#111" stroke-width="1.4"/>')

    # Axes
    lines.append(f'<line x1="{px0:.1f}" y1="{py0 + ph:.1f}" x2="{px0 + pw:.1f}" y2="{py0 + ph:.1f}" stroke="#111" stroke-width="1.2"/>')
    lines.append(f'<line x1="{px0:.1f}" y1="{py0:.1f}" x2="{px0:.1f}" y2="{py0 + ph:.1f}" stroke="#111" stroke-width="1.2"/>')

    # y=x dashed line
    line_x0 = mx(lo)
    line_y0 = my(lo)
    line_x1 = mx(hi)
    line_y1 = my(hi)
    lines.append(
        f'<line x1="{line_x0:.1f}" y1="{line_y0:.1f}" x2="{line_x1:.1f}" y2="{line_y1:.1f}" stroke="#555" stroke-width="1.3" stroke-dasharray="6,4"/>'
    )

    # Ticks
    tick_n = 5
    for i in range(tick_n + 1):
        v = lo + (hi - lo) * i / tick_n
        tx = mx(v)
        ty = my(v)
        lines.append(f'<line x1="{tx:.1f}" y1="{py0 + ph:.1f}" x2="{tx:.1f}" y2="{py0 + ph + 3:.1f}" stroke="#222" stroke-width="1"/>')
        lines.append(f'<text x="{tx:.1f}" y="{py0 + ph + 18:.1f}" text-anchor="middle" font-size="10" font-family="Times New Roman, serif">{_fmt_k(v)}</text>')
        lines.append(f'<line x1="{px0 - 3:.1f}" y1="{ty:.1f}" x2="{px0:.1f}" y2="{ty:.1f}" stroke="#222" stroke-width="1"/>')
        lines.append(f'<text x="{px0 - 8:.1f}" y="{ty + 3:.1f}" text-anchor="end" font-size="10" font-family="Times New Roman, serif">{_fmt_k(v)}</text>')

    lines.append(f'<text x="{x0 + w / 2:.1f}" y="{y0 + h - 6:.1f}" text-anchor="middle" font-size="12" font-family="Times New Roman, serif">Parent node A performance</text>')
    lines.append(
        f'<text x="{x0 + 14:.1f}" y="{y0 + h / 2:.1f}" text-anchor="middle" font-size="12" font-family="Times New Roman, serif" transform="rotate(-90 {x0 + 14:.1f} {y0 + h / 2:.1f})">Child node B performance</text>'
    )

    # Points
    below = 0
    above = 0
    for p in points:
        cx = mx(p["a_perf"])
        cy = my(p["b_perf"])
        if p["on_or_below"]:
            fill = "#1f9d8a"
            stroke = "#146a5c"
            below += 1
        else:
            fill = "#e67e22"
            stroke = "#9a5216"
            above += 1
        lines.append(f'<circle cx="{cx:.1f}" cy="{cy:.1f}" r="2.6" fill="{fill}" stroke="{stroke}" stroke-width="1.1"/>')

    lines.append(f'<rect x="{x0 + w - 232:.1f}" y="{y0 + 8:.1f}" width="224" height="48" fill="white" stroke="#222" stroke-width="1.1"/>')
    lines.append(f'<circle cx="{x0 + w - 218:.1f}" cy="{y0 + 24:.1f}" r="3" fill="#1f9d8a" stroke="#146a5c" stroke-width="1.0"/>')
    lines.append(f'<text x="{x0 + w - 206:.1f}" y="{y0 + 28:.1f}" font-size="11" font-family="Times New Roman, serif">On/Below y=x: {below}</text>')
    lines.append(f'<circle cx="{x0 + w - 218:.1f}" cy="{y0 + 42:.1f}" r="3" fill="#e67e22" stroke="#9a5216" stroke-width="1.0"/>')
    lines.append(f'<text x="{x0 + w - 206:.1f}" y="{y0 + 46:.1f}" font-size="11" font-family="Times New Roman, serif">Above y=x: {above}</text>')


def render_a2b_scatter_svg(path: str, *, app: str, method: str, points: List[dict]) -> None:
    width = 760
    height = 350
    panel_w = 700
    panel_h = 255

    lines: List[str] = []
    lines.append(f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}">')
    lines.append('<rect x="0" y="0" width="100%" height="100%" fill="white"/>')
    _draw_scatter_panel(lines, points=points, x0=30.0, y0=58.0, w=float(panel_w), h=float(panel_h))

    lines.append("</svg>")
    ensure_parent(path)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def render_a2b_scatter_png(path: str, *, app: str, method: str, points: List[dict], dpi: int = 220) -> None:
    """Generate A2B scatter plot as PNG using matplotlib."""
    fig, ax = plt.subplots(figsize=(10, 4.5), dpi=dpi)
    
    # Compute value range
    if points:
        vals = [p["a_perf"] for p in points] + [p["b_perf"] for p in points]
        vmin = min(vals)
        vmax = max(vals)
    else:
        vmin, vmax = 0.0, 1.0
    
    span = max(vmax - vmin, 1.0)
    lo = max(0.0, vmin - span * 0.08)
    hi = vmax + span * 0.08
    if hi <= lo:
        hi = lo + 1.0
    
    # Plot points
    below_x, below_y = [], []
    above_x, above_y = [], []
    for p in points:
        if p["on_or_below"]:
            below_x.append(p["a_perf"])
            below_y.append(p["b_perf"])
        else:
            above_x.append(p["a_perf"])
            above_y.append(p["b_perf"])
    
    ax.scatter(below_x, below_y, c='#1f9d8a', edgecolors='#146a5c', s=50, label='On/Below y=x', zorder=3)
    ax.scatter(above_x, above_y, c='#e67e22', edgecolors='#9a5216', s=50, label='Above y=x', zorder=3)
    
    # Plot y=x diagonal line
    ax.plot([lo, hi], [lo, hi], '--', linewidth=1.2, color='#555555', alpha=0.7, zorder=2)
    
    # Set axis limits and labels
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_xlabel('Parent node A performance', fontsize=12, family='serif')
    ax.set_ylabel('Child node B performance', fontsize=12, family='serif')
    
    # Grid
    ax.grid(True, alpha=0.3, zorder=1)
    ax.legend(loc='upper left', fontsize=10)
    
    # Save figure
    ensure_parent(path)
    fig.tight_layout()
    fig.savefig(path, dpi=dpi, bbox_inches='tight')
    plt.close(fig)


def _series_label(app: str, method: str) -> str:
    return f"{app}:{method}"


def _draw_scatter_ax(ax, *, points: List[dict], title: str) -> None:
    if points:
        vals = [p["a_perf"] for p in points] + [p["b_perf"] for p in points]
        vmin = min(vals)
        vmax = max(vals)
    else:
        vmin, vmax = 0.0, 1.0

    span = max(vmax - vmin, 1.0)
    lo = max(0.0, vmin - span * 0.08)
    hi = vmax + span * 0.08
    if hi <= lo:
        hi = lo + 1.0

    below_x, below_y = [], []
    above_x, above_y = [], []
    for p in points:
        if p["on_or_below"]:
            below_x.append(p["a_perf"])
            below_y.append(p["b_perf"])
        else:
            above_x.append(p["a_perf"])
            above_y.append(p["b_perf"])

    ax.scatter(below_x, below_y, c="#1f9d8a", edgecolors="#146a5c", s=24, label="On/Below y=x", zorder=3)
    ax.scatter(above_x, above_y, c="#e67e22", edgecolors="#9a5216", s=24, label="Above y=x", zorder=3)
    ax.plot([lo, hi], [lo, hi], "--", linewidth=1.0, color="#555555", alpha=0.75, zorder=2)

    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_title(title, fontsize=11, family="Times New Roman")
    ax.grid(True, alpha=0.28, zorder=1)
    ax.xaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt_k(v)))
    ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: _fmt_k(v)))
    ax.tick_params(axis="both", labelsize=9)
    ax.legend(loc="upper left", fontsize=8.5, frameon=True, prop={"family": "Times New Roman"})


def render_a2b_scatter_panel(svg_path: str, png_path: str, *, series_points: List[dict], dpi: int = 220) -> None:
    n = len(series_points)
    if n == 0:
        return

    # Keep a tighter canvas so text remains legible when included at \linewidth in LaTeX.
    fig, axes = plt.subplots(1, n, figsize=(3.7 * n, 3.4), dpi=dpi, facecolor="white")
    if n == 1:
        axes = [axes]
    else:
        axes = list(axes)

    for i, s in enumerate(series_points):
        ax = axes[i]
        _draw_scatter_ax(
            ax,
            points=s["points"],
            title=_series_label(s["app"], s["method"]),
        )
        if i == 0:
            ax.set_ylabel("Child node B performance", fontsize=10, family="Times New Roman")
        else:
            ax.set_ylabel("")
        ax.set_xlabel("Parent node A performance", fontsize=10, family="Times New Roman")

    fig.tight_layout()

    ensure_parent(svg_path)
    fig.savefig(svg_path, format="svg", bbox_inches="tight")
    ensure_parent(png_path)
    fig.savefig(png_path, dpi=dpi, bbox_inches="tight")
    plt.close(fig)


def build_violation_rows(series_reports: List[dict]) -> List[List[object]]:
    rows: List[List[object]] = []
    for rep in series_reports:
        for v in rep["violations"]:
            rows.append(
                [
                    rep["app"],
                    rep["method"],
                    v["src"],
                    v["dst"],
                    f"{v['src_perf']:.6f}",
                    f"{v['dst_perf']:.6f}",
                    f"{v['gap']:.6f}",
                    f"{v['required_epsilon_absolute']:.6f}",
                    f"{v['required_epsilon_relative']:.6f}",
                ]
            )
    rows.sort(key=lambda r: float(r[6]), reverse=True)
    return rows


def build_markdown_report(path: str, summary: dict, series_reports: List[dict], top_n: int) -> None:
    ensure_parent(path)
    lines: List[str] = []
    lines.append("# Hypothesis Violation Report (Nginx + Redis)")
    lines.append("")
    lines.append(f"- epsilon_mode: {summary['epsilon_mode']}")
    lines.append(f"- epsilon: {summary['epsilon']}")
    lines.append(f"- total_series: {len(series_reports)}")
    lines.append("")
    lines.append("## Per-Series Summary")
    lines.append("")
    lines.append("| App | Method | Edges | Violations | Missing | Max Gap | Mean Gap |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for r in series_reports:
        lines.append(
            f"| {r['app']} | {r['method']} | {r['total_edges']} | {r['violation_count']} | {r['missing_count']} | {r['max_gap']:.3f} | {r['mean_gap']:.3f} |"
        )

    lines.append("")
    lines.append("## Top Violations Across All Series")
    lines.append("")
    all_v: List[Tuple[float, str]] = []
    for r in series_reports:
        for v in r["violations"]:
            all_v.append(
                (
                    v["gap"],
                    f"- [{r['app']}/{r['method']}] {v['src']} -> {v['dst']}: gap={v['gap']:.3f}, need_abs_eps={v['required_epsilon_absolute']:.3f}, need_rel_eps={v['required_epsilon_relative']:.6f}",
                )
            )
    all_v.sort(key=lambda x: x[0], reverse=True)
    if all_v:
        for _, line in all_v[:top_n]:
            lines.append(line)
    else:
        lines.append("- No violations.")

    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Validate hypothesis for nginx+redis and generate aggregate reports")
    p.add_argument("--nginx-config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--redis-config-map", default="./data/redis_config_map.csv")
    p.add_argument("--epsilon", type=float, default=0.0)
    p.add_argument("--epsilon-mode", choices=("absolute", "relative"), default="absolute")
    p.add_argument("--top-n", type=int, default=20)
    p.add_argument("--out-dir", default="./result")
    p.add_argument("--png-dpi", type=int, default=220, help="DPI for PNG output")
    p.add_argument(
        "--a2b-only",
        action="store_true",
        help="Generate only per-series A2B scatter SVGs",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()
    if args.epsilon < 0:
        raise SystemExit("--epsilon must be non-negative")
    if args.top_n <= 0:
        raise SystemExit("--top-n must be positive")

    apps = [
        ("nginx", args.nginx_config_map, ["REQ"]),
        ("redis", args.redis_config_map, ["GET", "SET"]),
    ]

    series_reports: List[dict] = []
    aggregate_index: List[dict] = []
    series_points: List[dict] = []

    for app, path, methods in apps:
        rows = load_config_rows(path, methods)
        if not rows:
            raise SystemExit(f"No rows found for app={app} in {path}")

        edges = build_cover_edges(rows)
        data_dir = os.path.dirname(os.path.abspath(path))
        if not args.a2b_only:
            write_csv(
                os.path.join(data_dir, f"{app}_poset_edges.csv"),
                ["src", "dst"],
                edges,
            )

        for method in methods:
            perf = {r.config_id: r.metrics[method] for r in rows}
            if not args.a2b_only:
                write_csv(
                    os.path.join(data_dir, f"{app}_perf_{method.lower()}.csv"),
                    ["node", "perf"],
                    [(k, f"{v:.6f}") for k, v in sorted(perf.items())],
                )
            rep = evaluate_series(app, method, edges, perf, args.epsilon, args.epsilon_mode)
            series_reports.append(rep)
            series_points.append(
                {
                    "app": app,
                    "method": method,
                    "points": build_edge_points(edges, perf),
                }
            )
            aggregate_index.append(
                {
                    "app": app,
                    "method": method,
                    "edges": len(edges),
                    "configs": len(rows),
                    "violation_count": rep["violation_count"],
                    "missing_count": rep["missing_count"],
                    "max_gap": rep["max_gap"],
                    "mean_gap": rep["mean_gap"],
                }
            )

    out_dir = os.path.abspath(args.out_dir)
    os.makedirs(out_dir, exist_ok=True)
    
    # Create subdirectories for SVG and PNG
    svg_dir = os.path.join(out_dir, "svg")
    png_dir = os.path.join(out_dir, "png")
    os.makedirs(svg_dir, exist_ok=True)
    os.makedirs(png_dir, exist_ok=True)

    violation_rows: List[List[object]] = []
    summary = {
        "epsilon": args.epsilon,
        "epsilon_mode": args.epsilon_mode,
        "series_count": len(series_reports),
        "total_violations": sum(r["violation_count"] for r in series_reports),
        "total_missing": sum(r["missing_count"] for r in series_reports),
        "series": aggregate_index,
    }
    if not args.a2b_only:
        violation_rows = build_violation_rows(series_reports)
        write_csv(
            os.path.join(out_dir, "hypothesis_all_violations.csv"),
            [
                "app",
                "method",
                "src",
                "dst",
                "src_perf",
                "dst_perf",
                "gap",
                "required_epsilon_absolute",
                "required_epsilon_relative",
            ],
            violation_rows,
        )

        build_markdown_report(
            os.path.join(out_dir, "hypothesis_violate_report.md"),
            summary,
            series_reports,
            top_n=args.top_n,
        )
    scatter_paths: List[str] = []
    for s in series_points:
        scatter_base_name = f"hypothesis_a2b_scatter_{s['app']}_{s['method'].lower()}"
        
        # Generate SVG
        svg_path = os.path.join(svg_dir, f"{scatter_base_name}.svg")
        render_a2b_scatter_svg(
            svg_path,
            app=s["app"],
            method=s["method"],
            points=s["points"],
        )
        
        # Generate PNG
        png_path = os.path.join(png_dir, f"{scatter_base_name}.png")
        render_a2b_scatter_png(
            png_path,
            app=s["app"],
            method=s["method"],
            points=s["points"],
            dpi=args.png_dpi,
        )
        
        scatter_paths.append(svg_path)

    panel_base_name = "hypothesis_a2b_scatter_panel"
    panel_svg_path = os.path.join(svg_dir, f"{panel_base_name}.svg")
    panel_png_path = os.path.join(png_dir, f"{panel_base_name}.png")
    render_a2b_scatter_panel(
        panel_svg_path,
        panel_png_path,
        series_points=series_points,
        dpi=args.png_dpi,
    )
    scatter_paths.append(panel_svg_path)

    print("Series summary:")
    for row in aggregate_index:
        print(
            f"  {row['app']}/{row['method']}: edges={row['edges']} violations={row['violation_count']} "
            f"missing={row['missing_count']} max_gap={row['max_gap']:.3f}"
        )
    print(f"Total violations: {summary['total_violations']}")
    if not args.a2b_only:
        print(f"Violations CSV: {os.path.join(out_dir, 'hypothesis_all_violations.csv')}")
        print(f"Violate report: {os.path.join(out_dir, 'hypothesis_violate_report.md')}")
    print("A2B scatter plots:")
    for p in scatter_paths:
        print(f"  {p}")


if __name__ == "__main__":
    main()
