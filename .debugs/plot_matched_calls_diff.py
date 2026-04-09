#!/usr/bin/env python3
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import matplotlib.pyplot as plt

ROOT = Path(__file__).resolve().parents[1]
EVAL_ROOT = ROOT / "autoGen" / "eval_results"
OUT_DIR = ROOT / ".debugs"

PLUS_RE = re.compile(r"^flexos_py_plus_v(\d+)$")


def load_rows() -> list[dict[str, float | int | str]]:
    rows: list[dict[str, float | int | str]] = []

    baseline = EVAL_ROOT / "flexos_py_plus_baseline" / "summary.json"
    if baseline.exists():
        data = json.loads(baseline.read_text(encoding="utf-8"))
        rows.append(
            {
                "version": "baseline",
                "matched_calls": int(data.get("matched_calls", 0)),
                "expected_calls": int(data.get("expected_calls", 0)),
                "unresolved_calls": int(data.get("unresolved_calls", 0)),
            }
        )

    ver_rows: list[tuple[int, dict[str, float | int | str]]] = []
    for summary in sorted(EVAL_ROOT.glob("flexos_py_plus_v*/summary.json")):
        name = summary.parent.name
        m = PLUS_RE.match(name)
        if not m:
            continue
        v = int(m.group(1))
        data = json.loads(summary.read_text(encoding="utf-8"))
        ver_rows.append(
            (
                v,
                {
                    "version": f"v{v}",
                    "matched_calls": int(data.get("matched_calls", 0)),
                    "expected_calls": int(data.get("expected_calls", 0)),
                    "unresolved_calls": int(data.get("unresolved_calls", 0)),
                },
            )
        )

    for _, item in sorted(ver_rows, key=lambda x: x[0]):
        rows.append(item)

    prev = None
    for r in rows:
        matched = int(r["matched_calls"])
        expected = int(r["expected_calls"])
        r["match_rate"] = (matched / expected * 100.0) if expected else 0.0
        r["delta_vs_prev"] = 0 if prev is None else matched - prev
        prev = matched

    return rows


def write_csv(rows: list[dict[str, float | int | str]], out_csv: Path) -> None:
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "version",
                "matched_calls",
                "expected_calls",
                "unresolved_calls",
                "match_rate",
                "delta_vs_prev",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["version"],
                    r["matched_calls"],
                    r["expected_calls"],
                    r["unresolved_calls"],
                    f"{float(r['match_rate']):.2f}",
                    r["delta_vs_prev"],
                ]
            )


def plot(rows: list[dict[str, float | int | str]], out_png: Path, out_svg: Path) -> None:
    labels = [str(r["version"]) for r in rows]
    matched = [int(r["matched_calls"]) for r in rows]
    expected = [int(r["expected_calls"]) for r in rows]
    delta = [int(r["delta_vs_prev"]) for r in rows]

    x = list(range(len(rows)))

    plt.rcParams.update({"font.family": "DejaVu Sans", "svg.fonttype": "none"})
    fig, (ax1, ax2) = plt.subplots(2, 1, figsize=(11, 7), sharex=True, gridspec_kw={"height_ratios": [3, 2]})

    ax1.bar(x, matched, color="#4e79a7", label="matched_calls")
    ax1.plot(x, expected, color="#f28e2b", marker="o", linewidth=1.8, label="expected_calls")
    ax1.set_ylabel("Calls")
    ax1.grid(axis="y", linestyle="--", alpha=0.3)
    ax1.legend(loc="upper left")

    for xi, yi in zip(x, matched):
        ax1.text(xi, yi + 1, str(yi), ha="center", va="bottom", fontsize=8)

    colors = ["#59a14f" if d >= 0 else "#e15759" for d in delta]
    ax2.bar(x, delta, color=colors)
    ax2.axhline(0, color="#333333", linewidth=1)
    ax2.set_ylabel("Delta vs prev")
    ax2.set_xlabel("Rule version")
    ax2.grid(axis="y", linestyle="--", alpha=0.3)

    for xi, di in zip(x, delta):
        y = di + (0.8 if di >= 0 else -0.8)
        va = "bottom" if di >= 0 else "top"
        sign = "+" if di > 0 else ""
        ax2.text(xi, y, f"{sign}{di}", ha="center", va=va, fontsize=8)

    ax2.set_xticks(x)
    ax2.set_xticklabels(labels)

    fig.tight_layout()
    fig.savefig(out_png, dpi=220)
    fig.savefig(out_svg)
    plt.close(fig)


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    rows = load_rows()
    if not rows:
        raise SystemExit("No flexos_py_plus summary files found.")

    csv_path = OUT_DIR / "matched_calls_diff_by_rule_version.csv"
    png_path = OUT_DIR / "matched_calls_diff_by_rule_version.png"
    svg_path = OUT_DIR / "matched_calls_diff_by_rule_version.svg"

    write_csv(rows, csv_path)
    plot(rows, png_path, svg_path)

    print(f"wrote: {csv_path}")
    print(f"wrote: {png_path}")
    print(f"wrote: {svg_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
