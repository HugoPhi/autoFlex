#!/usr/bin/env python3
"""Batch evaluation for Python FlexOS porthelper rewrite.

Evaluation method:
- Use manual dataset files as oracle (expected gated calls).
- Run auto migration on copied raw files.
- Compare expected gated call tuples (lib, function) vs produced ones.
- Report unresolved expected gates as auto-migration misses.
"""

from __future__ import annotations

import argparse
import csv
import json
import re
import shutil
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, Iterable, List, Tuple

from flexos_porthelper_py import migrate_one

GATE_R_RE = re.compile(r"flexos_gate_r\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*[^,]+\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")
GATE_RE = re.compile(r"flexos_gate\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,")


@dataclass
class FileEval:
    app: str
    rel_path: str
    expected_calls: int
    produced_calls: int
    matched_calls: int
    unresolved_calls: int
    migration_changed: bool
    generated_rules: int
    instrumentation_applied: bool
    runtime_gate_check_status: str


def parse_gate_pairs(text: str) -> List[Tuple[str, str]]:
    out: List[Tuple[str, str]] = []
    out.extend(GATE_R_RE.findall(text))
    out.extend(GATE_RE.findall(text))
    return out


def count_pairs(pairs: Iterable[Tuple[str, str]]) -> Counter[Tuple[str, str]]:
    c: Counter[Tuple[str, str]] = Counter()
    for p in pairs:
        c[p] += 1
    return c


def find_target_files(dataset_root: Path, apps: List[str]) -> Dict[str, List[Path]]:
    targets: Dict[str, List[Path]] = {}
    for app in apps:
        manual_root = dataset_root / app / "manual"
        raw_root = dataset_root / app / "raw"
        if not manual_root.exists() or not raw_root.exists():
            continue

        selected: List[Path] = []
        patterns = ["*.c"]
        if app == "lwip":
            patterns.append("*.h")
        for pat in patterns:
            for mp in manual_root.rglob(pat):
                rel = mp.relative_to(manual_root)
                rp = raw_root / rel
                if not rp.exists():
                    continue
                txt = mp.read_text(encoding="utf-8", errors="ignore")
                if "flexos_gate(" in txt or "flexos_gate_r(" in txt:
                    selected.append(rel)
        targets[app] = sorted(selected)
    return targets


def evaluate_one_app(
    dataset_root: Path,
    app: str,
    rel_files: List[Path],
    out_dir: Path,
    enable_instrumentation: bool,
) -> List[FileEval]:
    app_raw = dataset_root / app / "raw"
    app_manual = dataset_root / app / "manual"

    app_projects = out_dir / "projects" / app
    app_report = out_dir / "reports" / app
    app_projects.mkdir(parents=True, exist_ok=True)
    app_report.mkdir(parents=True, exist_ok=True)

    # Persist project layout for easy diffing: raw/manual/auto.
    app_raw_copy = app_projects / "raw"
    app_manual_copy = app_projects / "manual"
    app_auto_copy = app_projects / "auto"
    for p in (app_raw_copy, app_manual_copy, app_auto_copy):
        if p.exists():
            shutil.rmtree(p)

    shutil.copytree(app_raw, app_raw_copy)
    shutil.copytree(app_manual, app_manual_copy)
    shutil.copytree(app_raw, app_auto_copy)

    results: List[FileEval] = []

    # Build cscope once for this app raw tree via first file, then reuse.
    rebuild = True
    for rel in rel_files:
        raw_file = app_auto_copy / rel
        manual_file = app_manual / rel

        expected_pairs = count_pairs(parse_gate_pairs(manual_file.read_text(encoding="utf-8", errors="ignore")))

        migration_out = app_report / rel.parent
        migration_out.mkdir(parents=True, exist_ok=True)
        mig = migrate_one(
            source_root=app_auto_copy,
            target_file=raw_file,
            out_dir=migration_out,
            rebuild_cscope=rebuild,
            enable_instrumentation=enable_instrumentation,
        )
        rebuild = False

        produced_pairs = count_pairs(parse_gate_pairs(raw_file.read_text(encoding="utf-8", errors="ignore")))
        matched = sum(min(expected_pairs[k], produced_pairs[k]) for k in expected_pairs)
        expected_total = sum(expected_pairs.values())
        produced_total = sum(produced_pairs.values())

        results.append(
            FileEval(
                app=app,
                rel_path=str(rel),
                expected_calls=expected_total,
                produced_calls=produced_total,
                matched_calls=matched,
                unresolved_calls=max(0, expected_total - matched),
                migration_changed=mig.changed,
                generated_rules=mig.generated_rules,
                instrumentation_applied=mig.instrumentation_applied,
                runtime_gate_check_status=mig.runtime_gate_check_status,
            )
        )

    return results


def write_reports(out_dir: Path, rows: List[FileEval]) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)

    csv_path = out_dir / "evaluation.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow([
            "app",
            "rel_path",
            "expected_calls",
            "produced_calls",
            "matched_calls",
            "unresolved_calls",
            "migration_changed",
            "generated_rules",
            "instrumentation_applied",
            "runtime_gate_check_status",
        ])
        for r in rows:
            w.writerow([
                r.app,
                r.rel_path,
                r.expected_calls,
                r.produced_calls,
                r.matched_calls,
                r.unresolved_calls,
                int(r.migration_changed),
                r.generated_rules,
                int(r.instrumentation_applied),
                r.runtime_gate_check_status,
            ])

    by_app: Dict[str, Dict[str, int]] = defaultdict(lambda: defaultdict(int))
    for r in rows:
        d = by_app[r.app]
        d["files"] += 1
        d["files_changed"] += int(r.migration_changed)
        d["expected_calls"] += r.expected_calls
        d["matched_calls"] += r.matched_calls
        d["unresolved_calls"] += r.unresolved_calls
        d["instrumentation_applied_files"] += int(r.instrumentation_applied)

    summary = {
        "total_files": len(rows),
        "files_changed": sum(int(r.migration_changed) for r in rows),
        "expected_calls": sum(r.expected_calls for r in rows),
        "matched_calls": sum(r.matched_calls for r in rows),
        "unresolved_calls": sum(r.unresolved_calls for r in rows),
        "instrumentation_applied_files": sum(int(r.instrumentation_applied) for r in rows),
        "runtime_gate_check_status_counts": dict(Counter(r.runtime_gate_check_status for r in rows)),
        "by_app": by_app,
    }

    json_path = out_dir / "summary.json"
    json_path.write_text(json.dumps(summary, indent=2, ensure_ascii=True), encoding="utf-8")

    md_path = out_dir / "summary.md"
    lines = []
    lines.append("# FlexOS Auto-Migration Evaluation")
    lines.append("")
    lines.append(f"- Total files evaluated: {summary['total_files']}")
    lines.append(f"- Files changed by automation: {summary['files_changed']}")
    lines.append(f"- Expected gated calls (manual oracle): {summary['expected_calls']}")
    lines.append(f"- Automatically matched gated calls: {summary['matched_calls']}")
    lines.append(f"- Unresolved expected calls (cannot auto-complete): {summary['unresolved_calls']}")
    lines.append(f"- Files with instrumentation applied: {summary['instrumentation_applied_files']}")
    lines.append(f"- Runtime gate check status counts: {summary['runtime_gate_check_status_counts']}")
    lines.append("")
    lines.append("## Per App")
    lines.append("")
    lines.append("| app | files | changed | expected | matched | unresolved | instrumentation_applied_files |")
    lines.append("|---|---:|---:|---:|---:|---:|---:|")
    for app, d in sorted(by_app.items()):
        lines.append(
            f"| {app} | {d['files']} | {d['files_changed']} | {d['expected_calls']} | "
            f"{d['matched_calls']} | {d['unresolved_calls']} | {d['instrumentation_applied_files']} |"
        )

    md_path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate python flexos porthelper on dataset")
    parser.add_argument("--dataset-root", default="autoGen/dataset")
    parser.add_argument("--apps", nargs="*", default=["nginx", "redis", "lwip", "newlib", "iperf"])
    parser.add_argument("--out-dir", default="autoGen/eval_results/flexos_py")
    parser.add_argument("--enable-instrumentation", action="store_true")
    args = parser.parse_args()

    dataset_root = Path(args.dataset_root).resolve()
    out_dir = Path(args.out_dir).resolve()

    targets = find_target_files(dataset_root, args.apps)
    all_rows: List[FileEval] = []
    for app in args.apps:
        rel_files = targets.get(app, [])
        if not rel_files:
            continue
        all_rows.extend(evaluate_one_app(dataset_root, app, rel_files, out_dir, args.enable_instrumentation))

    write_reports(out_dir, all_rows)
    print(f"evaluation_done files={len(all_rows)} out_dir={out_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
