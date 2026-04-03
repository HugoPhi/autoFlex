#!/usr/bin/env python3
"""Compute per-rule match stats from evaluation output.

A "rule" is represented as a (lib, function) gate pair.
Stats are computed by comparing manual oracle vs auto migrated outputs.
"""

from __future__ import annotations

import argparse
import csv
import re
from collections import Counter, defaultdict
from pathlib import Path

GATE_R_RE = re.compile(
    r"flexos_gate_r\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*[^,]+\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
)
GATE_RE = re.compile(
    r"flexos_gate\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*,\s*([A-Za-z_][A-Za-z0-9_]*)\s*,"
)


def parse_pairs(text: str) -> list[tuple[str, str]]:
    out: list[tuple[str, str]] = []
    out.extend(GATE_R_RE.findall(text))
    out.extend(GATE_RE.findall(text))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description="Compute per-rule match statistics")
    ap.add_argument("--eval-dir", required=True, help="Evaluation directory containing projects/<app>/manual and auto")
    ap.add_argument("--out-csv", default="", help="Output CSV path")
    args = ap.parse_args()

    eval_dir = Path(args.eval_dir).resolve()
    projects_dir = eval_dir / "projects"
    if not projects_dir.exists():
        raise SystemExit(f"projects dir not found: {projects_dir}")

    agg: dict[tuple[str, str], list[int]] = defaultdict(lambda: [0, 0, 0, 0])
    # [expected, produced, matched, unresolved]

    for app_dir in sorted(projects_dir.iterdir()):
        manual_root = app_dir / "manual"
        auto_root = app_dir / "auto"
        if not manual_root.exists() or not auto_root.exists():
            continue

        for manual_file in sorted(manual_root.rglob("*.c")):
            rel = manual_file.relative_to(manual_root)
            auto_file = auto_root / rel
            if not auto_file.exists():
                continue

            expected = Counter(parse_pairs(manual_file.read_text(encoding="utf-8", errors="ignore")))
            produced = Counter(parse_pairs(auto_file.read_text(encoding="utf-8", errors="ignore")))
            for key in sorted(set(expected) | set(produced)):
                e = expected.get(key, 0)
                p = produced.get(key, 0)
                m = min(e, p)
                u = max(0, e - m)
                row = agg[key]
                row[0] += e
                row[1] += p
                row[2] += m
                row[3] += u

    rows = sorted(agg.items(), key=lambda kv: (-kv[1][2], kv[0][0], kv[0][1]))

    out_csv = Path(args.out_csv).resolve() if args.out_csv else eval_dir / "rule_match_stats.csv"
    out_csv.parent.mkdir(parents=True, exist_ok=True)
    with out_csv.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["lib", "function", "expected", "produced", "matched", "unresolved"])
        for (lib, fn), vals in rows:
            w.writerow([lib, fn, vals[0], vals[1], vals[2], vals[3]])

    print(f"wrote {out_csv}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
