#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import os
import signal
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Set, Tuple


@dataclass
class SearchResult:
    strategy: str
    threshold: float
    query_count: int
    first_hit_query: int
    feasible_count: int
    frontier: List[str]


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def format_duration(seconds: float) -> str:
    return f"{seconds:.2f}s"


def normalize_metric(app: str, metric: str) -> str:
    app_norm = str(app).strip().lower()
    metric_norm = str(metric).strip().upper()
    if app_norm == "nginx":
        if metric_norm != "REQ":
            raise ValueError("nginx baseline_metric must be REQ")
        return "REQ"
    if app_norm == "redis":
        if metric_norm not in {"GET", "SET"}:
            raise ValueError("redis baseline_metric must be GET or SET")
        return metric_norm
    raise ValueError(f"unsupported app: {app}")


def run_cmd(
    cmd: List[str],
    cwd: Path,
    log_path: Path,
    env: Dict[str, str] | None = None,
    label: str | None = None,
    timeout_sec: int | None = None,
) -> float:
    start_ts = datetime.now(timezone.utc)
    start_iso = start_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
    with log_path.open("a", encoding="utf-8") as logf:
        if label:
            logf.write(f"[{label}] start {start_iso}\n")
        logf.write("$ " + " ".join(cmd) + "\n")
        proc_env = dict(**subprocess.os.environ)
        if env:
            proc_env.update(env)
        # Start child in its own process group so timeout cleanup can terminate
        # nested subprocesses (e.g., sudo -> bash -> docker/test.sh).
        proc = subprocess.Popen(
            cmd,
            cwd=str(cwd),
            stdout=logf,
            stderr=subprocess.STDOUT,
            text=True,
            env=proc_env,
            start_new_session=True,
        )
        try:
            rc = proc.wait(timeout=timeout_sec)
        except subprocess.TimeoutExpired:
            try:
                os.killpg(proc.pid, signal.SIGTERM)
            except Exception:
                pass
            try:
                rc = proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(proc.pid, signal.SIGKILL)
                except Exception:
                    pass
                rc = proc.wait()
            raise RuntimeError(f"command timed out after {timeout_sec}s: {' '.join(cmd)}")
        end_ts = datetime.now(timezone.utc)
        duration = (end_ts - start_ts).total_seconds()
        end_iso = end_ts.strftime("%Y-%m-%dT%H:%M:%SZ")
        if label:
            logf.write(f"[{label}] end {end_iso} duration={duration:.2f}s rc={rc}\n")
        if rc != 0:
            raise RuntimeError(f"command failed ({rc}): {' '.join(cmd)}")
    return duration


def append_log_line(log_path: Path, line: str) -> None:
    with log_path.open("a", encoding="utf-8") as logf:
        logf.write(line + "\n")


def run_single_query_evaluator(
    query_index: int,
    taskid: str,
    task_config: Dict[str, Any],
    app: str,
    baseline_metric: str,
    test_iterations: str,
    use_sudo: bool,
    exp_copy: Path,
    report_dir: Path,
    log_path: Path,
    single_test_script: Path,
    single_test_args: List[str],
    task_timing_log: Path,
    per_query_timeout_sec: int,
) -> Dict[str, Any]:
    query_root = report_dir / "query_results"
    query_root.mkdir(parents=True, exist_ok=True)
    query_csv = query_root / f"query_{query_index:03d}_{taskid}.csv"
    query_json = query_root / f"query_{query_index:03d}_{taskid}.json"
    query_cfg = query_root / f"query_{query_index:03d}_{taskid}_config.json"
    if query_csv.exists():
        query_csv.unlink()
    if query_json.exists():
        query_json.unlink()
    query_cfg.write_text(json.dumps(task_config, ensure_ascii=True, indent=2), encoding="utf-8")

    build_workspace = report_dir / "query_build_workspace"
    build_script = (Path(__file__).resolve().parent / "run_wayfinder_build_from_zip.sh").resolve()

    cmd = [
        "python3",
        str(single_test_script),
        "--task-id",
        taskid,
        "--task-config-json",
        str(query_cfg),
        "--build-script",
        str(build_script),
        "--build-work-root",
        str(build_workspace),
        "--app",
        app,
        "--experiment-dir",
        str(exp_copy),
        "--output-csv",
        str(query_csv),
        "--result-json",
        str(query_json),
        "--metric",
        baseline_metric,
        "--test-iterations",
        str(test_iterations),
        "--use-sudo",
        "1" if use_sudo else "0",
    ]
    cmd.extend(single_test_args)

    started_at = utc_now_iso()
    duration = run_cmd(
        cmd,
        exp_copy,
        log_path,
        env={"FLEXOS_TASK_TIMING_LOG": str(task_timing_log)},
        label=f"query-{query_index:03d} task={taskid}",
        timeout_sec=per_query_timeout_sec,
    )
    ended_at = utc_now_iso()

    if not query_json.is_file():
        raise RuntimeError(f"single query result json missing: {query_json}")
    payload = json.loads(query_json.read_text(encoding="utf-8"))
    metric = float(payload.get("metric", 0.0) or 0.0)
    task_dir = str(payload.get("task_dir", "")).strip()

    return {
        "query": query_index,
        "taskid": taskid,
        "task_dir": task_dir,
        "metric": metric,
        "duration_sec": duration,
        "started_at": started_at,
        "ended_at": ended_at,
        "result_csv": str(query_csv),
        "result_json": str(query_json),
    }


def extract_zip(zip_path: Path, out_dir: Path) -> Path:
    with zipfile.ZipFile(zip_path, "r") as zf:
        zf.extractall(out_dir)
    top_entries = [p for p in out_dir.iterdir() if p.name != "__MACOSX"]
    if len(top_entries) == 1 and top_entries[0].is_dir():
        return top_entries[0]
    return out_dir


def patch_experiment_for_overlay(exp_copy: Path, overlay_src: Path, app: str) -> None:
    overlay_dst = exp_copy / "_overlay" / app
    overlay_dst.mkdir(parents=True, exist_ok=True)
    shutil.copytree(overlay_src, overlay_dst, dirs_exist_ok=True)

    app_dir = exp_copy / "apps" / app
    orig_build = app_dir / "build.sh"
    wrap_build = app_dir / "build_wrapper.sh"
    wrap_build.write_text(make_build_wrapper_text(app, orig_build.read_text(encoding="utf-8")), encoding="utf-8")
    wrap_build.chmod(0o755)

    tpl = app_dir / "templates" / "wayfinder" / "template.yaml"
    text = tpl.read_text(encoding="utf-8")
    text = text.replace(f"./apps/{app}/build.sh", f"./apps/{app}/build_wrapper.sh")
    marker = f"  - source: ./apps/{app}/templates/kraft\n    destination: /kraft-yaml-template\n"
    insert = marker + f"  - source: ./_overlay/{app}\n    destination: /source-overlay\n"
    if "/source-overlay" not in text:
        text = text.replace(marker, insert)
    tpl.write_text(text, encoding="utf-8")


def parse_tasks(tasks_json: Path) -> Dict[str, Dict[str, Any]]:
    data = json.loads(tasks_json.read_text(encoding="utf-8"))
    return {str(taskid): payload for taskid, payload in data.items()}


def parse_benchmark_csv(csv_path: Path, app: str, baseline_metric: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    metric = normalize_metric(app, baseline_metric)
    lines = csv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for ln in lines[1:]:
        row = [x.strip().strip('"') for x in next(csv.reader([ln]))]
        if len(row) < 5:
            continue
        taskid, _chunk, _iter, method, value = row[:5]
        method_norm = method.strip().upper()
        if method_norm == "TIMEOUT":
            continue
        if method_norm != metric:
            continue
        try:
            v = float(value)
        except Exception:
            continue
        out.setdefault(taskid, []).append(v)
    return out


def parse_permutations_csv(path: Path) -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            taskid = str(row.get("TASKID", "")).strip().strip('"')
            if not taskid:
                continue
            out[taskid] = {k: str(v).strip().strip('"') for k, v in row.items() if k}
    return out


def make_build_wrapper_text(app: str, original_build_text: str) -> str:
    return (
        r'''#!/bin/bash
set -euo pipefail
export USE_UKSP=${USE_UKSP:-n}
if [[ -d /source-overlay ]]; then cp -a /source-overlay/. /usr/src/unikraft/apps/__APP__/; fi
TASKID=$(basename "$PWD")
BUILD_START_TS=$(date +%s)
BUILD_START_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)
echo "[task-build] task=${TASKID} phase=start at=${BUILD_START_ISO}"
trap 'BUILD_RC=$?; BUILD_END_TS=$(date +%s); BUILD_END_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ); BUILD_DURATION=$((BUILD_END_TS - BUILD_START_TS)); echo "[task-build] task=${TASKID} phase=end at=${BUILD_END_ISO} duration=${BUILD_DURATION}s rc=${BUILD_RC}"; if [[ -n "${FLEXOS_TASK_TIMING_LOG:-}" ]]; then mkdir -p "$(dirname "${FLEXOS_TASK_TIMING_LOG}")"; if [[ ! -f "${FLEXOS_TASK_TIMING_LOG}" ]]; then echo "phase,taskid,start_iso,end_iso,duration_sec,return_code" > "${FLEXOS_TASK_TIMING_LOG}"; fi; printf "%s,%s,%s,%s,%s,%s\n" "build" "${TASKID}" "${BUILD_START_ISO}" "${BUILD_END_ISO}" "${BUILD_DURATION}" "${BUILD_RC}" >> "${FLEXOS_TASK_TIMING_LOG}"; fi' EXIT

'''.replace("__APP__", app)
        + original_build_text
    )


def inject_task_timing_into_test_script(text: str, app: str) -> str:
    image_name = "nginx_kvm-x86_64" if app == "nginx" else "redis_kvm-x86_64"
    start_anchor = f"  TASKID=$(basename ${{D}})\n  UNIKERNEL_IMAGE=${{D}}/usr/src/unikraft/apps/{app}/build/{image_name}\n"
    start_insert = (
        f"  TASKID=$(basename ${{D}})\n"
        "  (\n"
        "    TASK_TEST_START_TS=$(date +%s)\n"
        "    TASK_TEST_START_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ)\n"
        "    echo \"[task-test] task=${TASKID} phase=start at=${TASK_TEST_START_ISO}\"\n"
        "    trap 'TASK_TEST_RC=$?; TASK_TEST_END_TS=$(date +%s); TASK_TEST_END_ISO=$(date -u +%Y-%m-%dT%H:%M:%SZ); TASK_TEST_DURATION=$((TASK_TEST_END_TS - TASK_TEST_START_TS)); echo \"[task-test] task=${TASKID} phase=end at=${TASK_TEST_END_ISO} duration=${TASK_TEST_DURATION}s rc=${TASK_TEST_RC}\"; if [[ -n \"${FLEXOS_TASK_TIMING_LOG:-}\" ]]; then mkdir -p \"$(dirname \"${FLEXOS_TASK_TIMING_LOG}\")\"; if [[ ! -f \"${FLEXOS_TASK_TIMING_LOG}\" ]]; then echo \"phase,taskid,start_iso,end_iso,duration_sec,return_code\" > \"${FLEXOS_TASK_TIMING_LOG}\"; fi; printf \"%s,%s,%s,%s,%s,%s\\n\" \"test\" \"${TASKID}\" \"${TASK_TEST_START_ISO}\" \"${TASK_TEST_END_ISO}\" \"${TASK_TEST_DURATION}\" \"${TASK_TEST_RC}\" >> \"${FLEXOS_TASK_TIMING_LOG}\"; fi' EXIT\n"
        f"  UNIKERNEL_IMAGE=${{D}}/usr/src/unikraft/apps/{app}/build/{image_name}\n"
    )
    if start_anchor not in text:
        return text
    patched = text.replace(start_anchor, start_insert, 1)
    if app == "nginx":
        end_anchor = "      pkill qemu-system-x86\n      pkill qemu\n      pkill qemu*\n    done\ndone\n"
        end_insert = "      pkill qemu-system-x86\n      pkill qemu\n      pkill qemu*\n    done\n  )\ndone\n"
    else:
        end_anchor = "      sleep 1 # 给系统一点喘息时间\n    done\n  done\ndone\n"
        end_insert = "      sleep 1 # 给系统一点喘息时间\n    done\n  )\n  done\ndone\n"
    if end_anchor in patched:
        patched = patched.replace(end_anchor, end_insert, 1)
    return patched


def read_timing_rows(path: Path) -> List[Dict[str, str]]:
    if not path.is_file():
        return []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        return [{k: str(v) for k, v in row.items()} for row in reader]


def summarize_task_timings(rows: List[Dict[str, str]]) -> List[Dict[str, Any]]:
    summary: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        taskid = row.get("taskid", "").strip()
        phase = row.get("phase", "").strip()
        if not taskid or phase not in {"build", "test"}:
            continue
        item = summary.setdefault(taskid, {"taskid": taskid, "build_sec": None, "build_runs": 0, "test_sec": 0.0, "test_runs": 0})
        try:
            duration = float(row.get("duration_sec", "0") or 0.0)
        except Exception:
            duration = 0.0
        if phase == "build":
            item["build_sec"] = duration
            item["build_runs"] += 1
        else:
            item["test_sec"] = float(item["test_sec"] or 0.0) + duration
            item["test_runs"] += 1
    return [summary[k] for k in sorted(summary.keys())]


def render_timing_report(report_dir: Path, phase_timings: List[Dict[str, Any]], task_timing_rows: List[Dict[str, str]]) -> None:
    task_summary = summarize_task_timings(task_timing_rows)
    lines: List[str] = ["# Timing Report", "", "## Command Timings"]
    if phase_timings:
        lines.extend(["| phase | duration | return_code |", "| --- | ---: | ---: |"])
        for item in phase_timings:
            lines.append(
                f"| {item.get('label', '-') } | {format_duration(float(item.get('duration_sec', 0.0)))} | {item.get('return_code', 0)} |"
            )
    else:
        lines.append("- no command timings recorded")

    lines.extend(["", "## Per-config Timings"])
    if task_summary:
        lines.extend(["| taskid | build_time | build_runs | test_time | test_runs |", "| --- | ---: | ---: | ---: | ---: |"])
        for item in task_summary:
            build_sec = item.get("build_sec")
            test_sec = item.get("test_sec")
            lines.append(
                f"| {item['taskid']} | {format_duration(float(build_sec)) if build_sec is not None else 'n/a'} | {item.get('build_runs', 0)} | {format_duration(float(test_sec)) if test_sec is not None else 'n/a'} | {item.get('test_runs', 0)} |"
            )
    else:
        lines.append("- no per-config timings recorded")

    (report_dir / "timing_report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    if task_timing_rows:
        with (report_dir / "task_timings.csv").open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=["phase", "taskid", "start_iso", "end_iso", "duration_sec", "return_code"])
            writer.writeheader()
            writer.writerows(task_timing_rows)


def run_dataset_search_fallback(
    exp_copy: Path,
    artifacts: Path,
    report_dir: Path,
    app: str,
    baseline_metric: str,
    threshold: float,
    top_k: int,
) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, Any]]:
    metric = normalize_metric(app, baseline_metric)
    permutations_csv = exp_copy / "apps" / app / "permutations-3.csv"
    results_csv = exp_copy / "paperresults" / f"{app}.csv"
    if not permutations_csv.is_file():
        raise RuntimeError(f"missing permutations csv: {permutations_csv}")
    if not results_csv.is_file():
        raise RuntimeError(f"missing paperresults csv: {results_csv}")

    tasks = parse_permutations_csv(permutations_csv)
    raw = parse_benchmark_csv(results_csv, app, metric)
    perf = {tid: mean(vals) for tid, vals in raw.items() if vals and tid in tasks}
    nodes = sorted(perf.keys())
    if not nodes:
        raise RuntimeError(f"no data parsed from {results_csv} for metric={metric}")

    vectors = build_vectors(tasks)
    all_keys = sorted({k for tid in nodes for k in vectors.get(tid, {}).keys()})
    anc, desc = closures(nodes, vectors, all_keys)

    progress_csv = report_dir / "search_progress.csv"
    sr = run_balanced(nodes, perf, threshold, anc, desc, progress_csv)

    feasible = {n for n in nodes if perf.get(n, 0.0) >= threshold}
    frontier = maximal(feasible, vectors, all_keys)

    selected = frontier[:top_k]
    if len(selected) < top_k:
        extras = [n for n in sorted(nodes, key=lambda x: perf.get(x, 0.0), reverse=True) if n not in selected]
        selected.extend(extras[: (top_k - len(selected))])

    img_out = artifacts / "top_images"
    img_out.mkdir(parents=True, exist_ok=True)

    selected_payload: List[Dict[str, Any]] = []
    for tid in selected:
        selected_payload.append(
            {
                "taskid": tid,
                "mean_metric": perf.get(tid, 0.0),
                "vector": vectors.get(tid, {}),
                "copied_files": [],
            }
        )

    shutil.copy2(results_csv, report_dir / f"benchmark_{app}.csv")

    meta = {
        "mode": "dataset-search-fallback",
        "query_count": sr.query_count,
        "first_hit_query": sr.first_hit_query,
        "frontier_taskids": frontier,
        "num_nodes_with_perf": len(nodes),
        "metric": metric,
    }
    return perf, selected_payload, meta


def mean(values: List[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def build_vectors(tasks: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, int]]:
    vectors: Dict[str, Dict[str, int]] = {}
    for tid, payload in tasks.items():
        vec: Dict[str, int] = {}
        for k, v in payload.items():
            if k.endswith("_COMPARTMENT"):
                vec[k] = int(v)
            elif k.endswith("_SFI"):
                vec[k] = 1 if str(v).lower() == "y" else 0
        vectors[tid] = vec
    return vectors


def validate_task_config(task: Dict[str, Any]) -> Tuple[bool, str]:
    try:
        num_comp = int(str(task.get("NUM_COMPARTMENTS", "3") or "3"))
    except Exception:
        return False, "invalid NUM_COMPARTMENTS"
    if num_comp <= 0:
        return False, "NUM_COMPARTMENTS must be positive"

    used: Set[int] = set()
    for k, v in task.items():
        if not k.endswith("_COMPARTMENT"):
            continue
        if k.startswith("COMPARTMENT"):
            continue
        try:
            c = int(str(v))
        except Exception:
            return False, f"invalid integer in {k}"
        if c < 1 or c > num_comp:
            return False, f"{k} out of range [1,{num_comp}]"
        used.add(c)

    if not used:
        return False, "no library compartments assigned"

    max_used = max(used)
    expected = set(range(1, max_used + 1))
    if used != expected:
        return False, f"non-contiguous compartments: used={sorted(used)}"

    return True, "ok"


def filter_safe_tasks(tasks: Dict[str, Dict[str, Any]]) -> Tuple[Dict[str, Dict[str, Any]], Dict[str, str]]:
    safe: Dict[str, Dict[str, Any]] = {}
    dropped: Dict[str, str] = {}
    for tid, payload in tasks.items():
        ok, reason = validate_task_config(payload)
        if ok:
            safe[tid] = payload
        else:
            dropped[tid] = reason
    return safe, dropped


def build_hasse_edges(nodes: List[str], vectors: Dict[str, Dict[str, int]], keys: List[str]) -> List[Tuple[str, str]]:
    edges: List[Tuple[str, str]] = []
    for a in nodes:
        for b in nodes:
            if a == b:
                continue
            if not leq(vectors[a], vectors[b], keys):
                continue
            if not any(vectors[a].get(k, 0) < vectors[b].get(k, 0) for k in keys):
                continue
            covered = False
            for c in nodes:
                if c in {a, b}:
                    continue
                if leq(vectors[a], vectors[c], keys) and leq(vectors[c], vectors[b], keys):
                    if any(vectors[a].get(k, 0) < vectors[c].get(k, 0) for k in keys) and any(
                        vectors[c].get(k, 0) < vectors[b].get(k, 0) for k in keys
                    ):
                        covered = True
                        break
            if not covered:
                edges.append((a, b))
    return sorted(set(edges))


def leq(a: Dict[str, int], b: Dict[str, int], keys: List[str]) -> bool:
    return all(a.get(k, 0) <= b.get(k, 0) for k in keys)


def maximal(feasible: Set[str], vectors: Dict[str, Dict[str, int]], keys: List[str]) -> List[str]:
    out: List[str] = []
    for x in feasible:
        dominated = False
        for y in feasible:
            if x == y:
                continue
            if leq(vectors[x], vectors[y], keys) and any(vectors[x].get(k, 0) < vectors[y].get(k, 0) for k in keys):
                dominated = True
                break
        if not dominated:
            out.append(x)
    return sorted(out)


def closures(nodes: List[str], vectors: Dict[str, Dict[str, int]], keys: List[str]) -> Tuple[Dict[str, Set[str]], Dict[str, Set[str]]]:
    anc: Dict[str, Set[str]] = {n: set() for n in nodes}
    desc: Dict[str, Set[str]] = {n: set() for n in nodes}
    for a in nodes:
        for b in nodes:
            if leq(vectors[a], vectors[b], keys):
                anc[b].add(a)
                desc[a].add(b)
    return anc, desc


def run_balanced(
    nodes: List[str],
    perf: Dict[str, float],
    threshold: float,
    anc: Dict[str, Set[str]],
    desc: Dict[str, Set[str]],
    progress_csv: Path,
) -> SearchResult:
    C: Set[str] = set(nodes)
    R: Set[str] = set()
    observed = 0
    feasible_obs = 0
    first_hit = 0

    with progress_csv.open("w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["query", "taskid", "metric", "threshold", "feasible", "remaining"])

        while C:
            p = (feasible_obs + 1) / (observed + 2)
            best = None
            best_score = -1.0
            for n in C:
                a = len(anc[n] & C)
                d = len(desc[n] & C)
                score = p * a + (1 - p) * d
                if score > best_score:
                    best_score = score
                    best = n
            if best is None:
                break

            observed += 1
            g = perf.get(best, 0.0)
            feasible = 1 if g >= threshold else 0
            print(
                f"[search-progress] query={observed} task={best} metric={g:.2f} "
                f"threshold={threshold:.2f} feasible={feasible}"
            )
            writer.writerow([observed, best, f"{g:.6f}", f"{threshold:.6f}", feasible, len(C)])
            f.flush()

            if feasible:
                if first_hit == 0:
                    first_hit = observed
                feasible_obs += 1
                R.add(best)
                C -= anc[best]
            else:
                C -= desc[best]

    return SearchResult(
        strategy="balanced",
        threshold=threshold,
        query_count=observed,
        first_hit_query=first_hit,
        feasible_count=len(R),
        frontier=sorted(R),
    )


def run_balanced_live(
    nodes: List[str],
    threshold: float,
    anc: Dict[str, Set[str]],
    desc: Dict[str, Set[str]],
    progress_csv: Path,
    query_detail_csv: Path,
    log_path: Path,
    evaluator: Callable[[int, str], Dict[str, Any]],
    max_queries: int = 0,
    feasible_target: int = 0,
) -> Tuple[SearchResult, Dict[str, float], List[Dict[str, Any]]]:
    C: Set[str] = set(nodes)
    R: Set[str] = set()
    perf: Dict[str, float] = {}
    query_details: List[Dict[str, Any]] = []
    observed = 0
    feasible_obs = 0
    first_hit = 0

    with progress_csv.open("w", encoding="utf-8", newline="") as pfile, query_detail_csv.open("w", encoding="utf-8", newline="") as qfile:
        progress_writer = csv.writer(pfile)
        progress_writer.writerow(["query", "taskid", "metric", "threshold", "feasible", "remaining"])

        detail_writer = csv.writer(qfile)
        detail_writer.writerow([
            "query",
            "taskid",
            "metric",
            "threshold",
            "feasible",
            "remaining",
            "test_duration_sec",
            "result_json",
            "result_csv",
            "started_at",
            "ended_at",
            "error",
        ])

        while C:
            if max_queries > 0 and observed >= max_queries:
                append_log_line(log_path, f"[search-limit] reached max_queries={max_queries}, stop early")
                break

            p = (feasible_obs + 1) / (observed + 2)
            best = None
            best_score = -1.0
            for n in C:
                a = len(anc[n] & C)
                d = len(desc[n] & C)
                score = p * a + (1 - p) * d
                if score > best_score:
                    best_score = score
                    best = n
            if best is None:
                break

            observed += 1
            start_line = (
                f"========== QUERY {observed:03d} START =========="
                f" task={best} threshold={threshold:.2f} remaining={len(C)}"
            )
            append_log_line(log_path, start_line)

            eval_error = ""
            try:
                detail = evaluator(observed, best)
            except Exception as exc:  # noqa: BLE001
                eval_error = str(exc)
                detail = {
                    "query": observed,
                    "taskid": best,
                    "metric": 0.0,
                    "duration_sec": 0.0,
                    "started_at": utc_now_iso(),
                    "ended_at": utc_now_iso(),
                    "result_json": "",
                    "result_csv": "",
                    "error": eval_error,
                }

            metric = float(detail.get("metric", 0.0) or 0.0)
            if not eval_error:
                perf[best] = metric
            duration = float(detail.get("duration_sec", 0.0) or 0.0)
            feasible = 1 if (not eval_error and metric >= threshold) else 0
            end_line = (
                f"========== QUERY {observed:03d} END =========="
                f" task={best} threshold={threshold:.2f} metric={metric:.2f}"
                f" feasible={feasible} duration={duration:.2f}s"
            )
            append_log_line(log_path, end_line)
            if eval_error:
                append_log_line(log_path, f"[query-error] query={observed} task={best} error={eval_error}")

            print(
                f"[search-progress] query={observed} task={best} metric={metric:.2f} "
                f"threshold={threshold:.2f} feasible={feasible}"
            )

            progress_writer.writerow([observed, best, f"{metric:.6f}", f"{threshold:.6f}", feasible, len(C)])
            pfile.flush()

            detail_writer.writerow([
                observed,
                best,
                f"{metric:.6f}",
                f"{threshold:.6f}",
                feasible,
                len(C),
                f"{duration:.6f}",
                str(detail.get("result_json", "")),
                str(detail.get("result_csv", "")),
                str(detail.get("started_at", "")),
                str(detail.get("ended_at", "")),
                str(eval_error or detail.get("error", "")),
            ])
            qfile.flush()

            query_details.append(detail)

            if feasible:
                if first_hit == 0:
                    first_hit = observed
                feasible_obs += 1
                R.add(best)
                C -= anc[best]
                if feasible_target > 0 and len(R) >= feasible_target:
                    append_log_line(log_path, f"[search-target] reached feasible_target={feasible_target}, stop early")
                    break
            else:
                C -= desc[best]

    return (
        SearchResult(
            strategy="balanced-live",
            threshold=threshold,
            query_count=observed,
            first_hit_query=first_hit,
            feasible_count=len(R),
            frontier=sorted(R),
        ),
        perf,
        query_details,
    )


def run_single_config_fallback(
    exp_copy: Path,
    artifacts: Path,
    report_dir: Path,
    log_path: Path,
    test_iterations: str,
    sudo_prefix: List[str],
    app: str,
    baseline_metric: str,
    threshold: float,
) -> Tuple[Dict[str, float], List[Dict[str, Any]], Dict[str, Any]]:
    image_name = "nginx_kvm-x86_64" if app == "nginx" else "redis_kvm-x86_64"
    app_image = "ghcr.io/project-flexos/nginx:latest" if app == "nginx" else "ghcr.io/project-flexos/redis:latest"

    single_root = report_dir / "single_config"
    single_build = single_root / "build"
    single_results = single_root / "results"
    single_task = single_results / "task-single" / "usr" / "src" / "unikraft" / "apps" / app / "build"
    single_build.mkdir(parents=True, exist_ok=True)
    single_task.mkdir(parents=True, exist_ok=True)

    docker_cmd = [
        "docker", "run", "--rm", "--entrypoint", "",
        "-e", "NUM_COMPARTMENTS=1",
        "-e", "LIBTLSF_COMPARTMENT=1", "-e", "LIBTLSF_SFI=n",
        "-e", "LIBLWIP_COMPARTMENT=1", "-e", "LIBLWIP_SFI=n",
        "-e", f"LIB{app.upper()}_COMPARTMENT=1", "-e", f"LIB{app.upper()}_SFI=n",
        "-e", "LIBNEWLIB_COMPARTMENT=1", "-e", "LIBNEWLIB_SFI=n",
        "-e", "LIBUKSCHED_COMPARTMENT=1", "-e", "LIBUKSCHED_SFI=n",
        "-e", "LIBPTHREAD_EMBEDDED_COMPARTMENT=1", "-e", "LIBPTHREAD_EMBEDDED_SFI=n",
        "-e", "COMPARTMENT1_DRIVER=intel-pku",
        "-e", "COMPARTMENT1_ISOLSTACK=false",
        "-e", "TEMPLDIR=/kraft-yaml-template",
        "-v", f"{exp_copy / 'apps' / app / 'build_wrapper.sh'}:/build.sh:ro",
        "-v", f"{exp_copy / 'apps' / app / 'templates' / 'kraft'}:/kraft-yaml-template:ro",
        "-v", f"{single_root / 'docker_out'}:/out",
        app_image,
        "bash", "-lc",
        "set -e; /build.sh; mkdir -p /out/build /out/src; "
        f"cp -av /usr/src/unikraft/apps/{app}/build/{image_name}* /out/build/; "
        f"cp -av /usr/src/unikraft/apps/{app}/{{kraft.yaml,config,build.log}} /out/build/; "
        f"cp -a /usr/src/unikraft/apps/{app} /out/src/",
    ]
    run_cmd(sudo_prefix + docker_cmd, exp_copy, log_path)

    docker_build = single_root / "docker_out" / "build"
    for name in (image_name, f"{image_name}.dbg", "build.log", "config", "kraft.yaml"):
        src = docker_build / name
        if src.is_file():
            shutil.copy2(src, single_build / name)

    if not (single_build / image_name).is_file():
        raise RuntimeError(f"missing fallback image: {single_build / image_name}")

    shutil.copy2(single_build / image_name, single_task / image_name)
    if (single_build / f"{image_name}.dbg").is_file():
        shutil.copy2(single_build / f"{image_name}.dbg", single_task / f"{image_name}.dbg")

    bench_csv = report_dir / f"benchmark_{app}.csv"
    test_cmd = sudo_prefix + [
        "env",
        f"ITERATIONS={test_iterations}",
        "DURATION=3s",
        "BOOT_WARMUP_SLEEP=5",
        f"RESULTS={bench_csv}",
        f"UNIKERNEL_INITRD={exp_copy / 'apps' / app / f'{app}.cpio'}",
        f"./apps/{app}/test.sh",
        str(single_results),
    ]
    run_cmd(test_cmd, exp_copy, log_path)

    bench = parse_benchmark_csv(bench_csv, app, baseline_metric)
    perf = {tid: mean(vals) for tid, vals in bench.items() if vals}
    metric = perf.get("task-single", 0.0)

    progress_csv = report_dir / "search_progress.csv"
    progress_csv.write_text(
        "query,taskid,metric,threshold,feasible,remaining\n"
        f"1,task-single,{metric:.6f},{threshold:.6f},{1 if metric >= threshold else 0},1\n",
        encoding="utf-8",
    )

    img_out = artifacts / "top_images"
    img_out.mkdir(parents=True, exist_ok=True)
    dst_task = img_out / "task-single"
    dst_task.mkdir(parents=True, exist_ok=True)
    copied_files: List[str] = []
    for name in (image_name, f"{image_name}.dbg", "build.log", "config", "kraft.yaml"):
        src = single_build / name
        if src.is_file():
            dst = dst_task / name
            shutil.copy2(src, dst)
            copied_files.append(str(dst.relative_to(artifacts)))

    selected = [{
        "taskid": "task-single",
        "mean_metric": metric,
        "vector": {
            "LIBLWIP_COMPARTMENT": 1,
            "LIBUKSCHED_COMPARTMENT": 1,
            "LIBLWIP_SFI": 0,
            "LIBUKSCHED_SFI": 0,
        },
        "copied_files": copied_files,
    }]

    meta = {
        "mode": "single-config-fallback",
        "query_count": 1,
        "first_hit_query": 1 if metric > 0 else 0,
        "frontier_taskids": ["task-single"],
    }
    return perf, selected, meta


def main() -> int:
    parser = argparse.ArgumentParser(description="Config search with real benchmark on fig-06 workflow")
    parser.add_argument("--job-id", required=True)
    parser.add_argument("--source-zip", required=True)
    parser.add_argument("--experiment-dir", required=True)
    parser.add_argument("--work-root", required=True)
    parser.add_argument("--overlay-subdir", default="")
    parser.add_argument("--num-compartments", default="3")
    parser.add_argument("--host-cores", default="3,4")
    parser.add_argument("--wayfinder-cores", default="1,2")
    parser.add_argument("--test-iterations", default="3")
    parser.add_argument("--baseline-metric", default="REQ")
    parser.add_argument("--baseline-threshold", required=True)
    parser.add_argument("--top-k", default="3")
    parser.add_argument("--use-sudo", default="0")
    parser.add_argument("--app", default="nginx")
    parser.add_argument("--allow-fallback", default="0")
    parser.add_argument("--single-test-script", default="website/scripts/run_single_query_test.py")
    parser.add_argument("--single-test-arg", action="append", default=[])
    parser.add_argument("--per-query-timeout-sec", default="900")
    parser.add_argument("--max-queries", default="0")
    args = parser.parse_args()

    source_zip = Path(args.source_zip).resolve()
    experiment_dir = Path(args.experiment_dir).resolve()
    work_root = Path(args.work_root).resolve()
    app = str(args.app).strip().lower()
    baseline_metric = normalize_metric(app, args.baseline_metric)
    single_test_script = Path(args.single_test_script)
    if not single_test_script.is_absolute():
        single_test_script = (Path.cwd() / single_test_script).resolve()
    if not single_test_script.is_file():
        raise SystemExit(f"single test script not found: {single_test_script}")
    single_test_args = [str(x) for x in (args.single_test_arg or [])]
    per_query_timeout_sec = max(int(str(args.per_query_timeout_sec)), 60)
    max_queries = max(int(str(args.max_queries)), 0)

    if not source_zip.is_file():
        raise SystemExit(f"source zip not found: {source_zip}")
    if not experiment_dir.is_dir():
        raise SystemExit(f"experiment dir not found: {experiment_dir}")
    if app not in {"nginx", "redis"}:
        raise SystemExit("--app must be nginx or redis")

    threshold = float(args.baseline_threshold)
    top_k = int(args.top_k)
    allow_fallback = str(args.allow_fallback).lower() in {"1", "true", "yes"}

    job_root = work_root if work_root.name == args.job_id else (work_root / args.job_id)
    extracted = job_root / "source"
    exp_copy = job_root / "work" / "fig-06_nginx-redis-perm"
    report_dir = job_root / "report"
    artifacts = job_root / "artifacts"
    log_path = job_root / "run.log"

    for d in (extracted, report_dir, artifacts, exp_copy.parent):
        d.mkdir(parents=True, exist_ok=True)

    overlay_root = extract_zip(source_zip, extracted)
    if args.overlay_subdir:
        overlay_root = overlay_root / args.overlay_subdir
    if not overlay_root.is_dir():
        raise SystemExit(f"overlay source dir not found: {overlay_root}")

    if exp_copy.exists():
        shutil.rmtree(exp_copy)
    shutil.copytree(experiment_dir, exp_copy)
    patch_experiment_for_overlay(exp_copy, overlay_root, app)

    sudo_prefix: List[str] = ["sudo", "-n", "-E"] if str(args.use_sudo).lower() in {"1", "true", "yes"} else []

    mode = "per-query-config"
    selected_payload: List[Dict[str, Any]] = []
    frontier: List[str] = []
    query_details: List[Dict[str, Any]] = []
    tasks_map_path = exp_copy / "apps" / app / f"permutations-{args.num_compartments}.csv"
    if not tasks_map_path.is_file():
        tasks_map_path = exp_copy / "apps" / app / "permutations-3.csv"
    if not tasks_map_path.is_file():
        raise RuntimeError(f"missing permutations csv: {tasks_map_path}")

    bench_csv = report_dir / f"benchmark_{app}.csv"
    progress_csv = report_dir / "search_progress.csv"
    query_detail_csv = report_dir / "query_detail.csv"
    task_timing_log = report_dir / "task_timings.csv"
    if not task_timing_log.exists():
        task_timing_log.write_text("phase,taskid,start_iso,end_iso,duration_sec,return_code\n", encoding="utf-8")
    phase_timings: List[Dict[str, Any]] = []
    vectors: Dict[str, Dict[str, int]] = {}

    try:
        tasks_all = parse_permutations_csv(tasks_map_path)
        safe_tasks, dropped_tasks = filter_safe_tasks(tasks_all)
        nodes = sorted(safe_tasks.keys())
        if not nodes:
            raise RuntimeError("no safe task configs after filtering")

        safe_space_csv = report_dir / "safe_search_space.csv"
        with safe_space_csv.open("w", encoding="utf-8", newline="") as sf:
            writer = csv.writer(sf)
            writer.writerow(["taskid", "status", "reason"])
            for tid in sorted(safe_tasks.keys()):
                writer.writerow([tid, "safe", "ok"])
            for tid, reason in sorted(dropped_tasks.items()):
                writer.writerow([tid, "dropped", reason])

        append_log_line(
            log_path,
            f"[safe-space] total={len(tasks_all)} safe={len(safe_tasks)} dropped={len(dropped_tasks)}",
        )

        vectors = build_vectors(safe_tasks)
        all_keys = sorted({k for tid in nodes for k in vectors[tid].keys()})
        anc, desc = closures(nodes, vectors, all_keys)
        dag_edges = build_hasse_edges(nodes, vectors, all_keys)
        dag_csv = report_dir / "search_dag_edges.csv"
        with dag_csv.open("w", encoding="utf-8", newline="") as df:
            writer = csv.writer(df)
            writer.writerow(["src", "dst"])
            writer.writerows(dag_edges)

        use_sudo = str(args.use_sudo).lower() in {"1", "true", "yes"}

        def evaluator(query_index: int, taskid: str) -> Dict[str, Any]:
            return run_single_query_evaluator(
                query_index=query_index,
                taskid=taskid,
                task_config=safe_tasks[taskid],
                app=app,
                baseline_metric=baseline_metric,
                test_iterations=str(args.test_iterations),
                use_sudo=use_sudo,
                exp_copy=exp_copy,
                report_dir=report_dir,
                log_path=log_path,
                single_test_script=single_test_script,
                single_test_args=single_test_args,
                task_timing_log=task_timing_log,
                per_query_timeout_sec=per_query_timeout_sec,
            )

        search_start = datetime.now(timezone.utc)
        sr, perf, query_details = run_balanced_live(
            nodes=nodes,
            threshold=threshold,
            anc=anc,
            desc=desc,
            progress_csv=progress_csv,
            query_detail_csv=query_detail_csv,
            log_path=log_path,
            evaluator=evaluator,
            max_queries=max_queries,
            feasible_target=top_k,
        )
        search_end = datetime.now(timezone.utc)
        phase_timings.append(
            {
                "label": f"query-test {app}",
                "duration_sec": (search_end - search_start).total_seconds(),
                "return_code": 0,
            }
        )

        frontier = list(sr.frontier)
        with bench_csv.open("w", encoding="utf-8", newline="") as bf:
            writer = csv.writer(bf)
            writer.writerow(["TASKID", "CHUNK", "ITERATION", "METHOD", "VALUE"])
            for taskid, metric in sorted(perf.items(), key=lambda x: x[0]):
                writer.writerow([taskid, 0, 1, baseline_metric, f"{metric:.6f}"])

        selected = frontier[:top_k]
        if len(selected) < top_k:
            extras = [n for n in sorted(perf.keys(), key=lambda x: perf.get(x, 0.0), reverse=True) if n not in selected]
            selected.extend(extras[: (top_k - len(selected))])

        img_out = artifacts / "top_images"
        img_out.mkdir(parents=True, exist_ok=True)
        detail_by_task = {str(d.get("taskid", "")): d for d in query_details}

        for tid in selected:
            src_task_raw = str(detail_by_task.get(tid, {}).get("task_dir", "")).strip()
            if not src_task_raw:
                continue
            src_task = Path(src_task_raw)
            if not src_task.is_dir():
                continue
            dst_task = img_out / tid
            dst_task.mkdir(parents=True, exist_ok=True)

            copied = []
            image_glob = "*nginx_kvm-x86_64*" if app == "nginx" else "*redis_kvm-x86_64*"
            for p in src_task.rglob(image_glob):
                if p.is_file():
                    target = dst_task / p.name
                    shutil.copy2(p, target)
                    copied.append(str(target.relative_to(artifacts)))

            for name in ("build.log", "config", "kraft.yaml"):
                for p in src_task.rglob(name):
                    if p.is_file():
                        target = dst_task / p.name
                        shutil.copy2(p, target)
                        copied.append(str(target.relative_to(artifacts)))
                        break

            selected_payload.append(
                {
                    "taskid": tid,
                    "mean_metric": perf.get(tid, 0.0),
                    "vector": vectors.get(tid, {}),
                    "copied_files": copied,
                }
            )

        balanced_meta = {
            "query_count": sr.query_count,
            "first_hit_query": sr.first_hit_query,
            "feasible_count_observed": sr.feasible_count,
        }

    except Exception as exc:
        if not allow_fallback:
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"[fatal] real wayfinder flow failed and fallback is disabled: {exc}\n")
            raise

        mode = "dataset-search-fallback"
        with log_path.open("a", encoding="utf-8") as logf:
            logf.write(f"[fallback] wayfinder flow failed: {exc}\n")

        try:
            perf, selected_payload, meta = run_dataset_search_fallback(
                exp_copy=exp_copy,
                artifacts=artifacts,
                report_dir=report_dir,
                app=app,
                baseline_metric=baseline_metric,
                threshold=threshold,
                top_k=top_k,
            )
            frontier = meta["frontier_taskids"]
            balanced_meta = {
                "query_count": meta["query_count"],
                "first_hit_query": meta["first_hit_query"],
                "feasible_count_observed": len([x for x in perf if perf[x] >= threshold]),
            }
        except Exception as dataset_exc:
            mode = "single-config-fallback"
            with log_path.open("a", encoding="utf-8") as logf:
                logf.write(f"[fallback] dataset flow failed: {dataset_exc}\n")

            perf, selected_payload, meta = run_single_config_fallback(
                exp_copy=exp_copy,
                artifacts=artifacts,
                report_dir=report_dir,
                log_path=log_path,
                test_iterations=args.test_iterations,
                sudo_prefix=sudo_prefix,
                app=app,
                baseline_metric=baseline_metric,
                threshold=threshold,
            )
            frontier = meta["frontier_taskids"]
            balanced_meta = {
                "query_count": meta["query_count"],
                "first_hit_query": meta["first_hit_query"],
                "feasible_count_observed": len([x for x in selected_payload if x.get("mean_metric", 0.0) >= threshold]),
            }

    with tarfile.open(artifacts / "top_images.tar.gz", "w:gz") as tf:
        tf.add(artifacts / "top_images", arcname="top_images")

    if bench_csv.is_file():
        shutil.copy2(bench_csv, artifacts / f"benchmark_{app}.csv")
    if progress_csv.is_file():
        shutil.copy2(progress_csv, artifacts / "search_progress.csv")
    if query_detail_csv.is_file():
        shutil.copy2(query_detail_csv, artifacts / "query_detail.csv")
    if tasks_map_path.is_file():
        shutil.copy2(tasks_map_path, artifacts / "tasks_map.csv")
    if (report_dir / "safe_search_space.csv").is_file():
        shutil.copy2(report_dir / "safe_search_space.csv", artifacts / "safe_search_space.csv")
    if (report_dir / "search_dag_edges.csv").is_file():
        shutil.copy2(report_dir / "search_dag_edges.csv", artifacts / "search_dag_edges.csv")

    report = {
        "job_id": args.job_id,
        "status": "ok",
        "mode": mode,
        "app": app,
        "baseline_metric": baseline_metric,
        "baseline_threshold": threshold,
        "num_nodes_with_perf": len(perf),
        "balanced_search": balanced_meta,
        "frontier_size": len(frontier),
        "frontier_taskids": frontier,
        "selected_top_k": selected_payload,
        "commands_log": str(log_path),
    }

    (report_dir / "performance_report.json").write_text(json.dumps(report, indent=2, ensure_ascii=True), encoding="utf-8")

    md = [
        "# Performance Report",
        "",
        f"- app: {app}",
        f"- baseline_metric: {baseline_metric}",
        f"- baseline_threshold: {threshold}",
        f"- mode: {mode}",
        f"- measured nodes: {len(selected_payload)}",
        f"- balanced query_count: {balanced_meta['query_count']}",
        f"- balanced first_hit_query: {balanced_meta['first_hit_query']}",
        f"- frontier_size: {len(frontier)}",
        "",
        "## Selected Top Images",
    ]
    for item in selected_payload:
        md.append(f"- task={item['taskid']}, mean_metric={item['mean_metric']:.2f}, files={len(item['copied_files'])}")
    task_timing_rows = read_timing_rows(task_timing_log)
    for detail in query_details:
        task_timing_rows.append(
            {
                "phase": "test",
                "taskid": str(detail.get("taskid", "")),
                "start_iso": str(detail.get("started_at", "")),
                "end_iso": str(detail.get("ended_at", "")),
                "duration_sec": f"{float(detail.get('duration_sec', 0.0) or 0.0):.6f}",
                "return_code": "0",
            }
        )
    task_summary = summarize_task_timings(task_timing_rows)
    md.extend(["", "## Timing Summary"])
    if phase_timings:
        md.extend(["### Command Timings", "| phase | duration |", "| --- | ---: |"])
        for item in phase_timings:
            md.append(f"| {item.get('label', '-') } | {format_duration(float(item.get('duration_sec', 0.0)))} |")
    else:
        md.append("- no command timings recorded")

    if task_summary:
        md.extend(["", "### Per-config Timings", "| taskid | build_time | test_time |", "| --- | ---: | ---: |"])
        for item in task_summary:
            build_sec = item.get("build_sec")
            test_sec = item.get("test_sec")
            md.append(
                f"| {item['taskid']} | {format_duration(float(build_sec)) if build_sec is not None else 'n/a'} | {format_duration(float(test_sec)) if test_sec is not None else 'n/a'} |"
            )
    else:
        md.append("- no per-config timings recorded")
    (report_dir / "performance_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    render_timing_report(report_dir, phase_timings, task_timing_rows)

    shutil.copy2(report_dir / "performance_report.json", artifacts / "performance_report.json")
    shutil.copy2(report_dir / "performance_report.md", artifacts / "performance_report.md")
    if (report_dir / "timing_report.md").is_file():
        shutil.copy2(report_dir / "timing_report.md", artifacts / "timing_report.md")
    if (report_dir / "task_timings.csv").is_file():
        shutil.copy2(report_dir / "task_timings.csv", artifacts / "task_timings.csv")
    shutil.copy2(log_path, artifacts / "build_and_test.log")

    print(f"job_id={args.job_id}")
    print(f"artifact_dir={artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
