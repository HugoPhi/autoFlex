#!/usr/bin/env python3
from __future__ import annotations

import argparse
import difflib
import json
import shutil
import sys
import zipfile
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List


def project_root_from_script() -> Path:
    return Path(__file__).resolve().parents[2]


def write_json(path: Path, obj: Dict[str, Any]) -> None:
    path.write_text(json.dumps(obj, indent=2, ensure_ascii=True), encoding="utf-8")


def collect_c_files(root: Path) -> List[Path]:
    return sorted(p for p in root.rglob("*.c") if p.is_file())


def make_suggestions(unresolved_counter: Counter[str], total_files: int, changed_files: int) -> List[str]:
    tips: List[str] = []
    if total_files == 0:
        tips.append("No C files detected in uploaded source. Please verify zip structure.")
        return tips

    if changed_files == 0:
        tips.append("No automatic gate rewrite was applied. Check whether code paths match supported rewrite patterns.")

    top_unresolved = unresolved_counter.most_common(10)
    if top_unresolved:
        tips.append("Review unresolved external call candidates and add explicit mapping rules for hot symbols.")
        tips.extend([f"Unresolved symbol: {name} (count={cnt})" for name, cnt in top_unresolved[:5]])
    else:
        tips.append("No unresolved candidates were detected by lexical/heuristic pass. Still recommend manual review on macro-heavy paths.")

    tips.append("Validate gate semantics for if/return/cast wrapped calls in critical request paths.")
    tips.append("Run compile + smoke test on migrated tree before configuration search.")
    return tips


def zip_dir(source_dir: Path, out_zip: Path) -> None:
    with zipfile.ZipFile(out_zip, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        for p in sorted(source_dir.rglob("*")):
            if p.is_file():
                zf.write(p, p.relative_to(source_dir).as_posix())


def unified_diff_lines(old: str, new: str, rel: str) -> List[str]:
    return list(
        difflib.unified_diff(
            old.splitlines(),
            new.splitlines(),
            fromfile=f"a/{rel}",
            tofile=f"b/{rel}",
            lineterm="",
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Run AutoFlex code porting on uploaded source zip")
    parser.add_argument("--source-zip", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--job-id", required=True)
    args = parser.parse_args()

    source_zip = Path(args.source_zip).resolve()
    work_root = Path(args.work_root).resolve()
    job_id = args.job_id

    if not source_zip.is_file():
        raise SystemExit(f"source zip not found: {source_zip}")

    project_root = project_root_from_script()
    sys.path.insert(0, str(project_root))

    try:
        from autoGen.flexos_porthelper_py import migrate_one  # type: ignore
    except Exception as exc:  # noqa: BLE001
        raise SystemExit(f"failed to import migrate_one: {exc}")

    raw_dir = work_root / "source_raw"
    migrated_dir = work_root / "source_migrated"
    report_dir = work_root / "report"
    run_dir = work_root / "run"
    artifacts_dir = work_root / "artifacts"

    for d in (raw_dir, migrated_dir, report_dir, run_dir, artifacts_dir):
        d.mkdir(parents=True, exist_ok=True)

    with zipfile.ZipFile(source_zip, "r") as zf:
        zf.extractall(raw_dir)

    # Handle common single-top-folder zip layout.
    top_entries = [p for p in raw_dir.iterdir() if p.name != "__MACOSX"]
    if len(top_entries) == 1 and top_entries[0].is_dir():
        source_root = top_entries[0]
    else:
        source_root = raw_dir

    shutil.copytree(source_root, migrated_dir, dirs_exist_ok=True)

    c_files = collect_c_files(migrated_dir)

    report_rows: List[Dict[str, Any]] = []
    unresolved_counter: Counter[str] = Counter()
    changed_files = 0
    rebuild = True

    cscope_or_spatch_missing = False
    for cmd in ("cscope", "spatch"):
        if shutil.which(cmd) is None:
            cscope_or_spatch_missing = True

    if cscope_or_spatch_missing:
        report = {
            "job_id": job_id,
            "status": "bypass-only",
            "reason": "missing required tools cscope/spatch",
            "source_zip": str(source_zip),
            "total_c_files": len(c_files),
            "changed_files": 0,
            "suggestions": [
                "Install cscope and spatch on host to enable automatic migration.",
                "Current output zip is pass-through copy of input source.",
            ],
        }
        write_json(report_dir / "migration_report.json", report)
        (report_dir / "migration_report.md").write_text(
            "# Migration Report\n\n"
            "Status: bypass-only\n\n"
            "Reason: missing required tools (`cscope`/`spatch`).\n",
            encoding="utf-8",
        )

        out_zip = artifacts_dir / "migrated_source.zip"
        zip_dir(migrated_dir, out_zip)
        shutil.copy2(report_dir / "migration_report.json", artifacts_dir / "migration_report.json")
        shutil.copy2(report_dir / "migration_report.md", artifacts_dir / "migration_report.md")
        print(f"job_id={job_id}")
        print(f"artifact_dir={artifacts_dir}")
        return 0

    for idx, file_path in enumerate(c_files, start=1):
        rel = file_path.relative_to(migrated_dir)
        raw_file = source_root / rel

        before = file_path.read_text(encoding="utf-8", errors="ignore")
        run_out = run_dir / rel.parent
        run_out.mkdir(parents=True, exist_ok=True)

        res = migrate_one(
            source_root=migrated_dir,
            target_file=file_path,
            out_dir=run_out,
            rebuild_cscope=rebuild,
            enable_instrumentation=False,
        )
        rebuild = False

        after = file_path.read_text(encoding="utf-8", errors="ignore")
        changed = before != after
        if changed:
            changed_files += 1

        unresolved_names = [x[1] for x in res.unresolved_calls]
        unresolved_counter.update(unresolved_names)

        diff_sample = unified_diff_lines(before, after, rel.as_posix())[:120]

        report_rows.append(
            {
                "file": rel.as_posix(),
                "changed": changed,
                "generated_rules": res.generated_rules,
                "unresolved_calls": len(res.unresolved_calls),
                "unresolved_symbols": unresolved_names[:20],
                "diff_sample": diff_sample,
            }
        )

        # keep progress visible in job logs
        print(f"[{idx}/{len(c_files)}] migrated: {rel} changed={int(changed)} unresolved={len(res.unresolved_calls)}")

    suggestions = make_suggestions(unresolved_counter, len(c_files), changed_files)

    report = {
        "job_id": job_id,
        "status": "ok",
        "source_zip": str(source_zip),
        "total_c_files": len(c_files),
        "changed_files": changed_files,
        "unresolved_total": sum(unresolved_counter.values()),
        "unresolved_top": unresolved_counter.most_common(30),
        "suggestions": suggestions,
        "files": report_rows,
    }
    write_json(report_dir / "migration_report.json", report)

    md_lines = [
        "# Migration Report",
        "",
        f"- job_id: {job_id}",
        f"- total_c_files: {len(c_files)}",
        f"- changed_files: {changed_files}",
        f"- unresolved_total: {sum(unresolved_counter.values())}",
        "",
        "## Suggestions",
    ]
    for s in suggestions:
        md_lines.append(f"- {s}")
    md_lines.append("")
    md_lines.append("## Top Unresolved Symbols")
    for name, cnt in unresolved_counter.most_common(20):
        md_lines.append(f"- {name}: {cnt}")
    (report_dir / "migration_report.md").write_text("\n".join(md_lines) + "\n", encoding="utf-8")

    out_zip = artifacts_dir / "migrated_source.zip"
    zip_dir(migrated_dir, out_zip)
    shutil.copy2(report_dir / "migration_report.json", artifacts_dir / "migration_report.json")
    shutil.copy2(report_dir / "migration_report.md", artifacts_dir / "migration_report.md")

    print(f"job_id={job_id}")
    print(f"artifact_dir={artifacts_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
