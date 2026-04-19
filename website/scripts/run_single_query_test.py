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


def resolve_task_dir_via_build(
    app: str,
    experiment_dir: Path,
    taskid: str,
    task_config_json: Path,
    build_script: Path,
    build_work_root: Path,
    use_sudo: bool,
) -> Path:
    if not build_script.is_file():
        raise SystemExit(f"build script not found: {build_script}")
    build_work_root.mkdir(parents=True, exist_ok=True)

    cmd = [
        "bash",
        str(build_script),
        "--job-id",
        f"single-query-{taskid[:12]}",
        "--experiment-dir",
        str(experiment_dir),
        "--app",
        app,
        "--work-root",
        str(build_work_root),
        "--task-id",
        taskid,
        "--task-config-json",
        str(task_config_json),
        "--use-sudo",
        "1" if use_sudo else "0",
    ]

    print(f"[single-test] build task={taskid}")
    print("$ " + " ".join(cmd))
    proc = subprocess.Popen(cmd, text=True)
    rc = proc.wait()
    if rc != 0:
        raise RuntimeError(f"single config build failed ({rc}) for task={taskid}")

    task_dir = build_work_root / "query-builds" / taskid / "results" / taskid
    if not task_dir.is_dir():
        raise RuntimeError(f"built task dir not found: {task_dir}")
    return task_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="Run single-query benchmark for one task and output one metric result")
    parser.add_argument("--task-dir", default="")
    parser.add_argument("--task-id", default="")
    parser.add_argument("--task-config-json", default="")
    parser.add_argument("--build-script", default="website/scripts/run_wayfinder_build_from_zip.sh")
    parser.add_argument("--build-work-root", default="")
    parser.add_argument("--app", required=True)
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument("--output-csv", required=True)
    parser.add_argument("--result-json", required=True)
    parser.add_argument("--metric", required=True)
    parser.add_argument("--test-iterations", default="3")
    parser.add_argument("--use-sudo", default="0")
    args = parser.parse_args()

    exp_dir = Path(args.experiment_dir).resolve()
    output_csv = Path(args.output_csv).resolve()
    result_json = Path(args.result_json).resolve()

    if not exp_dir.is_dir():
        raise SystemExit(f"experiment dir not found: {exp_dir}")

    app = str(args.app).strip().lower()
    metric = normalize_metric(app, args.metric)
    use_sudo = str(args.use_sudo).lower() in {"1", "true", "yes"}

    task_dir_arg = str(args.task_dir).strip()
    if task_dir_arg:
        task_dir = Path(task_dir_arg).resolve()
        if not task_dir.is_dir():
            raise SystemExit(f"task dir not found: {task_dir}")
        taskid = str(args.task_id).strip() or task_dir.name
    else:
        taskid = str(args.task_id).strip()
        if not taskid:
            raise SystemExit("missing --task-id when --task-dir is not provided")
        task_cfg = Path(str(args.task_config_json).strip()).resolve()
        if not task_cfg.is_file():
            raise SystemExit(f"task config json not found: {task_cfg}")

        build_script = Path(str(args.build_script).strip())
        if not build_script.is_absolute():
            build_script = (Path.cwd() / build_script).resolve()

        if str(args.build_work_root).strip():
            build_work_root = Path(str(args.build_work_root).strip()).resolve()
        else:
            build_work_root = (result_json.parent / "build_workspace").resolve()

        task_dir = resolve_task_dir_via_build(
            app=app,
            experiment_dir=exp_dir,
            taskid=taskid,
            task_config_json=task_cfg,
            build_script=build_script,
            build_work_root=build_work_root,
            use_sudo=use_sudo,
        )

    output_csv.parent.mkdir(parents=True, exist_ok=True)
    result_json.parent.mkdir(parents=True, exist_ok=True)
    if output_csv.exists():
        output_csv.unlink()

    sudo_prefix = ["sudo", "-n", "-E"] if use_sudo else []

    metric_values: List[float] | None = None

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
            # nginx test.sh may return non-zero due cleanup pkill commands even
            # when benchmark rows were already written successfully.
            metric_values = parse_metric_values(output_csv, taskid, metric)
            if not metric_values:
                raise RuntimeError(f"single query test failed ({rc}) for task={taskid}")
            print(
                f"[single-test] warning: non-zero test exit rc={rc}, "
                f"but collected {len(metric_values)} metric samples; continue"
            )

    values = metric_values if metric_values is not None else parse_metric_values(output_csv, taskid, metric)
    mean_metric = sum(values) / len(values) if values else 0.0
    payload: Dict[str, object] = {
        "taskid": taskid,
        "app": app,
        "metric_name": metric,
        "metric_values": values,
        "metric": mean_metric,
        "task_dir": str(task_dir),
        "output_csv": str(output_csv),
    }
    result_json.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
    print(f"[single-test] done task={taskid} metric={mean_metric:.6f} samples={len(values)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
