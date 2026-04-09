#!/usr/bin/env python3

from __future__ import annotations

import argparse
import csv
import re
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np


@dataclass
class DiffStats:
    files_changed: int
    added: int
    removed: int

    @property
    def changed_lines(self) -> int:
        return self.added + self.removed


GATE_R_RE = re.compile(
    r"flexos_gate_r\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*[^,]+\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
)
GATE_RE = re.compile(
    r"flexos_gate\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
)


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


def run_diff(lhs: Path, rhs: Path) -> DiffStats:
    cmd = [
        "diff",
        "-ruN",
        "--exclude=cscope.out",
        "--exclude=cscope.files",
        str(lhs),
        str(rhs),
    ]
    ret = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if ret.returncode not in {0, 1}:
        raise RuntimeError(f"diff failed for {lhs} vs {rhs}: {ret.stderr.strip()}")

    files_changed = 0
    added = 0
    removed = 0
    for line in ret.stdout.splitlines():
        if line.startswith("diff -ruN"):
            files_changed += 1
            continue
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            removed += 1
    return DiffStats(files_changed=files_changed, added=added, removed=removed)


def list_changed_files(lhs: Path, rhs: Path) -> list[Path]:
    cmd = [
        "diff",
        "-qrN",
        "--exclude=cscope.out",
        "--exclude=cscope.files",
        str(lhs),
        str(rhs),
    ]
    ret = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="ignore")
    if ret.returncode not in {0, 1}:
        raise RuntimeError(f"diff -qrN failed for {lhs} vs {rhs}: {ret.stderr.strip()}")

    out: list[Path] = []
    for line in ret.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("Files ") and " differ" in line:
            left_path = line[len("Files ") : line.find(" and ")].strip()
            p = Path(left_path)
            if p.suffix.lower() in {".c", ".h"}:
                out.append(p)
    return out


def parse_gate_pairs(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    out.extend(GATE_R_RE.findall(text))
    out.extend(GATE_RE.findall(text))
    return out


def is_semantically_equivalent_for_migration(manual_file: Path, auto_file: Path) -> bool:
    manual_text = manual_file.read_text(encoding="utf-8", errors="ignore")
    auto_text = auto_file.read_text(encoding="utf-8", errors="ignore")

    expected = Counter(parse_gate_pairs(manual_text))
    produced = Counter(parse_gate_pairs(auto_text))

    # No migration gate in manual: keep conservative behavior.
    if not expected:
        return False

    unresolved = 0
    for key, exp_count in expected.items():
        unresolved += max(0, exp_count - min(exp_count, produced.get(key, 0)))
    return unresolved == 0


def semantic_remaining_changed_lines(auto_dir: Path, manual_dir: Path) -> tuple[int, int, int]:
    changed_auto_files = list_changed_files(auto_dir, manual_dir)
    sem_equiv_files = 0
    sem_non_equiv_files = 0
    remaining = 0

    for left_auto_file in changed_auto_files:
        rel = left_auto_file.relative_to(auto_dir)
        manual_file = manual_dir / rel
        auto_file = auto_dir / rel
        if not manual_file.exists() or not auto_file.exists():
            sem_non_equiv_files += 1
            continue

        if is_semantically_equivalent_for_migration(manual_file, auto_file):
            sem_equiv_files += 1
            continue

        sem_non_equiv_files += 1
        d = run_diff(auto_file, manual_file)
        remaining += d.changed_lines

    return remaining, sem_equiv_files, sem_non_equiv_files


def collect_app_stats(projects_dir: Path) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    for app_dir in sorted(projects_dir.iterdir()):
        if not app_dir.is_dir():
            continue
        raw_dir = app_dir / "raw"
        manual_dir = app_dir / "manual"
        auto_dir = app_dir / "auto"
        if not (raw_dir.exists() and manual_dir.exists() and auto_dir.exists()):
            continue

        total = run_diff(raw_dir, manual_dir)
        remaining_text = run_diff(auto_dir, manual_dir)
        remaining_semantic, sem_equiv_files, sem_non_equiv_files = semantic_remaining_changed_lines(auto_dir, manual_dir)

        total_lines = total.changed_lines
        remaining_lines = remaining_semantic
        reduced_lines = max(0, total_lines - remaining_lines)
        reduction_pct = (reduced_lines / total_lines * 100.0) if total_lines > 0 else 0.0

        rows.append(
            {
                "app": app_dir.name,
                "total_manual_changed_lines": total_lines,
                "remaining_changed_lines": remaining_lines,
                "remaining_text_changed_lines": remaining_text.changed_lines,
                "reduced_changed_lines": reduced_lines,
                "reduction_pct": reduction_pct,
                "total_files_changed": total.files_changed,
                "remaining_files_changed": remaining_text.files_changed,
                "semantically_equivalent_changed_files": sem_equiv_files,
                "semantically_non_equivalent_changed_files": sem_non_equiv_files,
            }
        )
    return rows


def write_csv(rows: list[dict[str, object]], out_csv: Path) -> None:
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(
            [
                "app",
                "total_manual_changed_lines",
                "remaining_changed_lines",
                "remaining_text_changed_lines",
                "reduced_changed_lines",
                "reduction_pct",
                "total_files_changed",
                "remaining_files_changed",
                "semantically_equivalent_changed_files",
                "semantically_non_equivalent_changed_files",
            ]
        )
        for r in rows:
            w.writerow(
                [
                    r["app"],
                    r["total_manual_changed_lines"],
                    r["remaining_changed_lines"],
                    r["remaining_text_changed_lines"],
                    r["reduced_changed_lines"],
                    f"{float(r['reduction_pct']):.2f}",
                    r["total_files_changed"],
                    r["remaining_files_changed"],
                    r["semantically_equivalent_changed_files"],
                    r["semantically_non_equivalent_changed_files"],
                ]
            )


def plot_rows(rows: list[dict[str, object]], out_file: Path) -> None:
    if not rows:
        raise ValueError("No app stats found under projects directory")

    apps = [str(r["app"]) for r in rows]
    total = np.array([int(r["total_manual_changed_lines"]) for r in rows], dtype=float)
    remain = np.array([int(r["remaining_changed_lines"]) for r in rows], dtype=float)
    pct = np.array([float(r["reduction_pct"]) for r in rows], dtype=float)

    x = np.arange(len(apps))
    width = 0.34

    fig, ax = plt.subplots(figsize=(10.2, 3.9), facecolor="white")
    bars_total = ax.bar(
        x - width / 2,
        total,
        width,
        label="Manual workload (raw->manual)",
        facecolor="#dbe9f6",
        edgecolor="#4c78a8",
        linewidth=1.0,
        hatch="xx",
        zorder=3,
    )
    bars_remain = ax.bar(
        x + width / 2,
        remain,
        width,
        label="Remaining after auto (semantic-aware)",
        facecolor="#f9e3d2",
        edgecolor="#dd8452",
        linewidth=1.0,
        hatch="++",
        zorder=3,
    )

    ymax = max(float(np.max(total)), float(np.max(remain))) if len(rows) else 1.0
    ax.set_ylim(0, max(10.0, ymax * 1.28))

    for b, v in zip(bars_total, total):
        ax.text(b.get_x() + b.get_width() / 2, v + ymax * 0.015, f"{int(v)}", ha="center", va="bottom", fontsize=8)
    for b, v in zip(bars_remain, remain):
        ax.text(b.get_x() + b.get_width() / 2, v + ymax * 0.015, f"{int(v)}", ha="center", va="bottom", fontsize=8)

    for xi, t, p in zip(x, total, pct):
        ax.text(
            xi,
            t + ymax * 0.11,
            f"-{p:.1f}%",
            ha="center",
            va="bottom",
            fontsize=9,
            fontweight="semibold",
            color="#2e8b57",
        )

    ax.set_xticks(x)
    ax.set_xticklabels([a.upper() for a in apps], fontsize=10)
    ax.set_ylabel("Changed lines (diff-based effort)", fontsize=11)
    ax.grid(axis="y", color="#d9d9d9", linewidth=0.6, alpha=0.8, zorder=0)

    leg = ax.legend(
        loc="upper center",
        bbox_to_anchor=(0.5, -0.18),
        ncol=2,
        frameon=True,
        edgecolor="#262626",
        framealpha=1.0,
        fancybox=False,
        fontsize=9,
    )
    leg.get_frame().set_linewidth(1.0)

    out_file.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout(rect=[0, 0.06, 1, 1])
    fig.savefig(out_file)
    plt.close(fig)


def main() -> int:
    p = argparse.ArgumentParser(description="Plot app-level manual workload reduction from project diffs")
    p.add_argument("--eval-dir", required=True, help="Evaluation dir that contains projects/<app>/{raw,manual,auto}")
    p.add_argument("--output-root", required=True, help="Output root for figure files")
    p.add_argument("--formats", nargs="+", default=["svg", "png"], help="Output formats")
    args = p.parse_args()

    eval_dir = Path(args.eval_dir).resolve()
    projects_dir = eval_dir / "projects"
    if not projects_dir.exists():
        raise SystemExit(f"projects dir not found: {projects_dir}")

    setup_style()
    rows = collect_app_stats(projects_dir)

    stats_csv = eval_dir / "manual_effort_diff_stats.csv"
    write_csv(rows, stats_csv)

    out_root = Path(args.output_root).resolve()
    stem = "fig-auto-manual-effort-reduction"
    for fmt in args.formats:
        fmt = fmt.lower().strip(".")
        if fmt not in {"svg", "png"}:
            raise SystemExit(f"unsupported format: {fmt}")
        plot_rows(rows, out_root / stem / f"{stem}.{fmt}")

    print(f"wrote stats: {stats_csv}")
    print("done")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
