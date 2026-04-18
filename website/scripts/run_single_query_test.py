#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List


def normalize_metric(app: str, metric: str) -> str:
    app_norm = str(app).strip().lower()
    metric_norm = str(metric).strip().upper()
    if app_norm == "nginx":
        if metric_norm != "REQ":
            raise ValueError("nginx metric must be REQ")
        return "REQ"
    if app_norm == "redis":
        if metric_norm not in {"GET", "SET"}:
            raise ValueError("redis metric must be GET or SET")
        return metric_norm
    raise ValueError(f"unsupported app: {app}")


def parse_metric_values(csv_path: Path, taskid: str, metric: str) -> List[float]:
    if not csv_path.is_file():
        return []
    values: List[float] = []
    with csv_path.open("r", encoding="utf-8", errors="ignore") as f:
        for idx, line in enumerate(f):
            if idx == 0:
                continue
            row = [x.strip().strip('"') for x in next(csv.reader([line]))]
            if len(row) < 5:
                continue
            rid, _chunk, _iter, method, value = row[:5]
            if rid != taskid:
                continue
            if method.strip().upper() != metric:
                continue
            try:
                values.append(float(value))
            except Exception:
                continue
    return values


def main() -> int:
    parser = argparse.ArgumentParser(description="Run single-query benchmark for one task and output one metric result")
    parser.add_argument("--task-dir", required=True)
    parser.add_argument("--app", required=True)
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--test-iterations", default="3")
    parser.add_argument("--use-sudo", default="0")
    args = parser.parse_args()

    task_dir = Path(args.task_dir).resolve()
    exp_dir = Path(args.experiment_dir).resolve()
    output_csv = Path(args.output_csv).resolve()
    result_json = Path(args.result_json).resolve()

    if not task_dir.is_dir():
        raise SystemExit(f"task dir not found: {task_dir}")
    if not exp_dir.is_dir():
        raise SystemExit(f"experiment dir not found: {exp_dir}")

    app = str(args.app).strip().lower()
    metric = normalize_metric(app, args.metric)
    taskid = task_dir.name

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        output_csv.unlink()

    sudo_prefix = ["sudo", "-n", "-E"] if str(args.use_sudo).lower() in {"1", "true", "yes"} else []

    with tempfile.TemporaryDirectory(prefix=f"single-task-{taskid[:8]}-") as tmp:
        tmp_root = Path(tmp)
        link_path = tmp_root / taskid
        try:
            link_path.symlink_to(task_dir, target_is_directory=True)
        except Exception:
            shutil.copytree(task_dir, link_path)

        cmd = sudo_prefix + [
            "env",
            f"ITERATIONS={args.test_iterations}",
            "DURATION=3s",
            "BOOT_WARMUP_SLEEP=5",
            f"RESULTS={output_csv}",
            f"UNIKERNEL_INITRD={exp_dir / 'apps' / app / f'{app}.cpio'}",
            f"./apps/{app}/test.sh",
            str(tmp_root),
        ]

        print(f"[single-test] task={taskid} app={app} metric={metric}")
        print("$ " + " ".join(cmd))
        proc = subprocess.Popen(cmd, cwd=str(exp_dir), text=True)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"single query test failed ({rc}) for task={taskid}")

    values = parse_metric_values(output_csv, taskid, metric)
    mean_metric = sum(values) / len(values) if values else 0.0
    payload: Dict[str, object] = {
        "taskid": taskid,
        "app": app,
        "metric_name": metric,
        "metric_values": values,
        "metric": mean_metric,
        "output_csv": str(output_csv),
    }
    result_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"[single-test] done task={taskid} metric={mean_metric:.6f} samples={len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
