#!/usr/bin/env python3
from __future__ import annotations

import json
import csv
import re
import shutil
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, render_template, request, send_file

WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
JOBS_ROOT = WEB_ROOT / "jobs"
TEST_BENCH_CONFIG_ROOT = WEB_ROOT / "config" / "test_benches"

app = Flask(__name__)


@dataclass
class Job:
    id: str
    kind: str
    status: str
    created_at: float
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    params: Dict[str, Any] = field(default_factory=dict)
    command: str = ""
    cwd: str = ""
    log_file: str = ""
    output_dir: str = ""
    return_code: Optional[int] = None
    error: str = ""


JOBS: Dict[str, Job] = {}
LOCK = threading.Lock()
RUNNING_PROCS: Dict[str, subprocess.Popen[str]] = {}
STOP_REQUESTED: set[str] = set()


def load_test_bench_configs() -> Dict[str, Dict[str, Any]]:
    configs: Dict[str, Dict[str, Any]] = {}
    if not TEST_BENCH_CONFIG_ROOT.exists():
        return configs

    for path in sorted(TEST_BENCH_CONFIG_ROOT.glob("*.json")):
        if path.stem.lower() == "template":
            continue
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
            bench_id = str(raw.get("id", "")).strip()
            app_name = str(raw.get("app", "")).strip().lower()
            if not bench_id or app_name not in {"nginx", "redis"}:
                continue

            defaults = raw.get("defaults")
            if not isinstance(defaults, dict):
                defaults = {}

            single_test_script = str(raw.get("single_test_script", "website/scripts/run_single_query_test.py")).strip()
            single_test_args_raw = raw.get("single_test_args", [])
            single_test_args: List[str] = []
            if isinstance(single_test_args_raw, list):
                for item in single_test_args_raw:
                    if isinstance(item, str) and item.strip():
                        single_test_args.append(item.strip())

            configs[bench_id] = {
                "id": bench_id,
                "name": str(raw.get("name", bench_id)),
                "description": str(raw.get("description", "")),
                "app": app_name,
                "defaults": {k: str(v) for k, v in defaults.items()},
                "single_test_script": single_test_script,
                "single_test_args": single_test_args,
                "config_file": str(path.relative_to(WEB_ROOT)),
            }
        except Exception:
            continue

    return configs


def get_test_bench_or_400(bench_id: str) -> tuple[Optional[Dict[str, Any]], Optional[Response]]:
    benches = load_test_bench_configs()
    bench = benches.get(bench_id)
    if bench is None:
        return None, jsonify({"error": f"unknown test_bench: {bench_id}"}),
    return bench, None


def _parse_delete_ids(payload: Any) -> List[str]:
    if not isinstance(payload, dict):
        return []
    ids = payload.get("job_ids")
    if not isinstance(ids, list):
        return []
    out: List[str] = []
    for x in ids:
        if isinstance(x, str) and x.strip():
            out.append(x.strip())
    return out


def _delete_job(job_id: str) -> tuple[bool, str]:
    job = JOBS.get(job_id)
    if not job:
        return False, "not_found"
    if job.status in {"queued", "running"}:
        return False, "still_active"

    JOBS.pop(job_id, None)
    shutil.rmtree(JOBS_ROOT / job_id, ignore_errors=True)
    return True, "deleted"


def now_ts() -> float:
    return time.time()


def persist_job(job: Job) -> None:
    job_dir = JOBS_ROOT / job.id
    job_dir.mkdir(parents=True, exist_ok=True)
    metadata = job_dir / "metadata.json"
    metadata.write_text(json.dumps(asdict(job), indent=2, ensure_ascii=True), encoding="utf-8")


def list_files_recursive(base: Path, limit: int = 3000) -> List[str]:
    out: List[str] = []
    if not base.exists():
        return out
    for p in sorted(base.rglob("*")):
        if p.is_file():
            out.append(str(p.relative_to(base)))
            if len(out) >= limit:
                break
    return out


def resolve_job_log_path(job: Job) -> Path | None:
    log_candidates: List[Path] = []
    if job.log_file:
        log_candidates.append(Path(job.log_file))
    if job.output_dir:
        log_candidates.append(Path(job.output_dir) / "build_and_test.log")
    return next((p for p in log_candidates if p.is_file()), None)


def safe_resolve_under(base: Path, rel_path: str) -> Path:
    candidate = (base / rel_path).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ValueError("path escapes base directory")
    return candidate


def resolve_script_under_project(script_path: str) -> Path:
    raw = (script_path or "").strip()
    if not raw:
        raise ValueError("missing script path")

    candidate = Path(raw)
    if not candidate.is_absolute():
        candidate = PROJECT_ROOT / candidate
    candidate = candidate.resolve()

    project_resolved = PROJECT_ROOT.resolve()
    if project_resolved not in candidate.parents and candidate != project_resolved:
        raise ValueError("script path escapes project root")
    if not candidate.is_file():
        raise ValueError(f"script not found: {candidate}")
    return candidate


SEARCH_PROGRESS_RE = re.compile(
    r"^\[search-progress\]\s+query=(\d+)\s+task=([0-9a-f]{32})\s+metric=([0-9.]+)\s+threshold=([0-9.]+)\s+feasible=(\d+)"
)
SCHEDULE_BUILD_RE = re.compile(r"Scheduling task run ([0-9a-f]{32})-build")
RFC3339_RE = re.compile(r'time="([0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9:.+-]+)"')


def _parse_rfc3339(ts: str) -> Optional[float]:
    try:
        return datetime.fromisoformat(ts).timestamp()
    except Exception:
        return None


def _read_search_progress_rows(job: Job) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    if not job.output_dir:
        return out
    progress_csv = Path(job.output_dir) / "search_progress.csv"
    if not progress_csv.is_file():
        return out

    with progress_csv.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            taskid = str(row.get("taskid", "")).strip()
            query_str = str(row.get("query", "")).strip()
            if not taskid or not query_str:
                continue
            try:
                q = int(query_str)
            except Exception:
                continue
            out.append(
                {
                    "query": q,
                    "taskid": taskid,
                    "metric": float(row.get("metric", 0.0) or 0.0),
                    "threshold": float(row.get("threshold", 0.0) or 0.0),
                    "feasible": int(float(row.get("feasible", 0) or 0)) == 1,
                    "remaining": int(float(row.get("remaining", 0) or 0)),
                }
            )
    return out


def _extract_build_time_windows_from_log(log_path: Path) -> Dict[str, Dict[str, Optional[float]]]:
    windows: Dict[str, Dict[str, Optional[float]]] = {}
    current_task: Optional[str] = None
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None

    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            m_sched = SCHEDULE_BUILD_RE.search(line)
            if m_sched:
                if current_task is not None:
                    windows[current_task] = {
                        "build_start_ts": first_ts,
                        "build_end_ts": last_ts,
                    }
                current_task = m_sched.group(1)
                first_ts = None
                last_ts = None
                continue

            if current_task is None:
                continue

            for ts_s in RFC3339_RE.findall(line):
                ts = _parse_rfc3339(ts_s)
                if ts is None:
                    continue
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

    if current_task is not None:
        windows[current_task] = {
            "build_start_ts": first_ts,
            "build_end_ts": last_ts,
        }
    return windows


def _extract_test_phase_window_from_log(log_path: Path) -> Dict[str, Optional[float]]:
    in_test_phase = False
    first_ts: Optional[float] = None
    last_ts: Optional[float] = None

    with log_path.open("r", encoding="utf-8", errors="ignore") as f:
        for line in f:
            if line.startswith("$") and " test-app-" in line:
                in_test_phase = True
                continue
            if line.startswith("$") and in_test_phase:
                break
            if not in_test_phase:
                continue
            for ts_s in RFC3339_RE.findall(line):
                ts = _parse_rfc3339(ts_s)
                if ts is None:
                    continue
                if first_ts is None:
                    first_ts = ts
                last_ts = ts

    return {
        "test_phase_start_ts": first_ts,
        "test_phase_end_ts": last_ts,
    }


def _task_build_log_mtime(job: Job, taskid: str) -> Optional[float]:
    if not job.id:
        return None
    work_root = JOBS_ROOT / job.id / "work"
    if not work_root.is_dir():
        return None

    patterns = [
        f"tmp-*/wayfinder-build-*/results/{taskid}/usr/src/unikraft/apps/*/build.log",
        f"tmp-*/wayfinder-build-*/results/{taskid}/build.log",
    ]
    for pat in patterns:
        for p in work_root.glob(pat):
            try:
                if p.is_file():
                    return p.stat().st_mtime
            except Exception:
                continue
    return None


def compute_query_timings(job: Job) -> Dict[str, Any]:
    rows = _read_search_progress_rows(job)
    if not rows:
        return {
            "rows": [],
            "summary": {
                "query_count": 0,
                "has_per_query_build_timing": False,
                "has_per_query_test_timing": False,
                "note": "no search_progress.csv found",
            },
        }

    detail_by_query: Dict[int, Dict[str, Any]] = {}
    task_timing_by_task: Dict[str, Dict[str, float]] = {}

    if job.output_dir:
        detail_csv = Path(job.output_dir) / "query_detail.csv"
        if detail_csv.is_file():
            with detail_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    try:
                        q = int(str(row.get("query", "")).strip())
                    except Exception:
                        continue
                    detail_by_query[q] = {
                        "test_duration_sec": float(row.get("test_duration_sec", 0.0) or 0.0),
                    }

        timings_csv = Path(job.output_dir) / "task_timings.csv"
        if timings_csv.is_file():
            with timings_csv.open("r", encoding="utf-8", newline="") as f:
                reader = csv.DictReader(f)
                for row in reader:
                    taskid = str(row.get("taskid", "")).strip()
                    phase = str(row.get("phase", "")).strip()
                    if not taskid or phase not in {"build", "test"}:
                        continue
                    try:
                        duration = float(row.get("duration_sec", 0.0) or 0.0)
                    except Exception:
                        duration = 0.0
                    item = task_timing_by_task.setdefault(taskid, {"build_duration_sec": 0.0, "test_duration_sec": 0.0})
                    key = "build_duration_sec" if phase == "build" else "test_duration_sec"
                    item[key] += duration

    with_build = 0
    with_test = 0
    out_rows: List[Dict[str, Any]] = []
    for r in rows:
        taskid = r["taskid"]
        q = int(r.get("query", 0) or 0)
        per_task = task_timing_by_task.get(taskid, {})
        build_dur = per_task.get("build_duration_sec")
        test_dur = per_task.get("test_duration_sec")
        if (test_dur is None or test_dur <= 0.0) and q in detail_by_query:
            test_dur = detail_by_query[q].get("test_duration_sec")

        if isinstance(build_dur, (int, float)) and build_dur > 0:
            with_build += 1
        if isinstance(test_dur, (int, float)) and test_dur > 0:
            with_test += 1

        out_rows.append(
            {
                **r,
                "build_start_ts": None,
                "build_end_ts": None,
                "build_duration_sec": build_dur,
                "test_duration_sec": test_dur,
            }
        )

    return {
        "rows": out_rows,
        "summary": {
            "query_count": len(out_rows),
            "has_per_query_build_timing": with_build > 0,
            "has_per_query_test_timing": with_test > 0,
            "test_phase_start_ts": None,
            "test_phase_end_ts": None,
            "test_phase_duration_sec": None,
            "note": "timings are read from query_detail.csv and task_timings.csv generated by per-query build+test flow.",
        },
    }


def build_command(job_id: str, kind: str, params: Dict[str, Any]) -> tuple[List[str], Path, Path]:
    if kind == "workflow_code_porting":
        source_zip_path = (params.get("source_zip_path") or "").strip()
        job_root = JOBS_ROOT / job_id
        script = WEB_ROOT / "scripts" / "run_code_porting_from_zip.py"
        cmd = [
            "python3",
            str(script),
            "--job-id",
            job_id,
            "--source-zip",
            source_zip_path,
            "--work-root",
            str(job_root),
        ]
        return cmd, PROJECT_ROOT, job_root / "artifacts"

    if kind == "workflow_config_search":
        source_zip_path = (params.get("source_zip_path") or "").strip()
        overlay_subdir = (params.get("overlay_subdir") or "").strip()
        app_name = (params.get("app") or "nginx").strip().lower()
        num_compartments = str(params.get("num_compartments", "3"))
        host_cores = str(params.get("host_cores", "3,4"))
        wayfinder_cores = str(params.get("wayfinder_cores", "1,2"))
        test_iterations = str(params.get("test_iterations", "3"))
        baseline_metric = str(params.get("baseline_metric", "REQ"))
        baseline_threshold = str(params.get("baseline_threshold", "45000"))
        top_k = str(params.get("top_k", "3"))
        per_query_timeout_sec = str(params.get("per_query_timeout_sec", "900"))
        max_queries = str(params.get("max_queries", "0"))

        experiment_dir = PROJECT_ROOT / "asplos22-ae" / "experiments" / "fig-06_nginx-redis-perm"
        job_root = JOBS_ROOT / job_id
        script = WEB_ROOT / "scripts" / "run_config_search_nginx_from_zip.py"
        single_test_script = str(params.get("single_test_script") or "website/scripts/run_single_query_test.py")
        single_test_args_raw = params.get("single_test_args")
        single_test_args: List[str] = []
        if isinstance(single_test_args_raw, list):
            for item in single_test_args_raw:
                if isinstance(item, str) and item.strip():
                    single_test_args.append(item.strip())
        single_test_script_path = resolve_script_under_project(single_test_script)

        cmd = [
            "python3",
            str(script),
            "--job-id",
            job_id,
            "--source-zip",
            source_zip_path,
            "--experiment-dir",
            str(experiment_dir),
            "--work-root",
            str(job_root),
            "--app",
            app_name,
            "--num-compartments",
            num_compartments,
            "--host-cores",
            host_cores,
            "--wayfinder-cores",
            wayfinder_cores,
            "--test-iterations",
            test_iterations,
            "--baseline-metric",
            baseline_metric,
            "--baseline-threshold",
            baseline_threshold,
            "--top-k",
            top_k,
            "--use-sudo",
            "1",
            "--single-test-script",
            str(single_test_script_path),
            "--per-query-timeout-sec",
            per_query_timeout_sec,
            "--max-queries",
            max_queries,
        ]
        for arg in single_test_args:
            cmd.extend(["--single-test-arg", arg])
        if overlay_subdir:
            cmd.extend(["--overlay-subdir", overlay_subdir])

        return cmd, PROJECT_ROOT, job_root / "artifacts"

    raise ValueError(f"unknown job kind: {kind}")


def run_job(job: Job) -> None:
    try:
        cmd, cwd, output_dir = build_command(job.id, job.kind, job.params)
        job_dir = JOBS_ROOT / job.id
        job_dir.mkdir(parents=True, exist_ok=True)
        log_path = job_dir / "run.log"

        with LOCK:
            job.status = "running"
            job.started_at = now_ts()
            job.command = shlex.join(cmd)
            job.cwd = str(cwd)
            job.log_file = str(log_path)
            job.output_dir = str(output_dir)
            persist_job(job)

        with log_path.open("w", encoding="utf-8") as logf:
            proc = subprocess.Popen(
                cmd,
                cwd=str(cwd),
                stdout=logf,
                stderr=subprocess.STDOUT,
                text=True,
            )
            with LOCK:
                RUNNING_PROCS[job.id] = proc
            rc = proc.wait()

        with LOCK:
            was_stopped = job.id in STOP_REQUESTED
            STOP_REQUESTED.discard(job.id)
            RUNNING_PROCS.pop(job.id, None)
            job.return_code = rc
            job.finished_at = now_ts()
            if was_stopped:
                job.status = "failed"
                job.error = "stopped by user"
            else:
                job.status = "succeeded" if rc == 0 else "failed"
            persist_job(job)
    except Exception as exc:  # noqa: BLE001
        with LOCK:
            STOP_REQUESTED.discard(job.id)
            RUNNING_PROCS.pop(job.id, None)
            job.status = "failed"
            job.finished_at = now_ts()
            job.error = str(exc)
            persist_job(job)


def load_jobs_from_disk() -> None:
    if not JOBS_ROOT.exists():
        return
    for p in JOBS_ROOT.iterdir():
        meta = p / "metadata.json"
        if not meta.exists():
            continue
        try:
            data = json.loads(meta.read_text(encoding="utf-8"))
            job = Job(**data)
            if job.status == "running":
                job.status = "failed"
                job.error = "interrupted before completion (service restart or manual stop)"
                job.finished_at = now_ts()
                persist_job(job)
            JOBS[job.id] = job
        except Exception:
            continue


load_jobs_from_disk()


@app.route("/")
def index() -> str:
    return render_template("index.html")


@app.get("/api/health")
def health() -> Response:
    return jsonify({"ok": True, "project_root": str(PROJECT_ROOT), "web_root": str(WEB_ROOT)})


@app.post("/api/workflows/code-porting")
def create_workflow_code_porting_job() -> Response:
    source_zip = request.files.get("source_zip")
    if source_zip is None:
        return jsonify({"error": "missing file field: source_zip"}), 400

    filename = source_zip.filename or ""
    if not filename.lower().endswith(".zip"):
        return jsonify({"error": "source_zip must be a .zip file"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    source_zip_path = input_dir / "source.zip"
    source_zip.save(str(source_zip_path))

    params = {"source_zip_path": str(source_zip_path)}

    job = Job(id=job_id, kind="workflow_code_porting", status="queued", created_at=now_ts(), params=params)
    with LOCK:
        JOBS[job.id] = job
        persist_job(job)

    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return jsonify({"job": asdict(job)})


@app.post("/api/workflows/config-search")
def create_workflow_config_search_job() -> Response:
    source_zip = request.files.get("source_zip")
    if source_zip is None:
        return jsonify({"error": "missing file field: source_zip"}), 400

    filename = source_zip.filename or ""
    if not filename.lower().endswith(".zip"):
        return jsonify({"error": "source_zip must be a .zip file"}), 400

    test_bench = (request.form.get("test_bench") or "").strip()
    if not test_bench:
        return jsonify({"error": "missing test_bench"}), 400

    bench, bench_error = get_test_bench_or_400(test_bench)
    if bench_error is not None:
        return bench_error
    assert bench is not None

    app_name = str(bench["app"])
    defaults = bench.get("defaults") if isinstance(bench, dict) else {}
    if not isinstance(defaults, dict):
        defaults = {}

    baseline_metric = (request.form.get("baseline_metric") or str(defaults.get("baseline_metric", "REQ"))).strip()
    baseline_threshold = (request.form.get("baseline_threshold") or "").strip()

    overlay_subdir = (request.form.get("overlay_subdir") or str(defaults.get("overlay_subdir", ""))).strip()
    num_compartments = (request.form.get("num_compartments") or str(defaults.get("num_compartments", "3"))).strip()
    host_cores = (request.form.get("host_cores") or str(defaults.get("host_cores", "3,4"))).strip()
    wayfinder_cores = (request.form.get("wayfinder_cores") or str(defaults.get("wayfinder_cores", "1,2"))).strip()
    test_iterations = (request.form.get("test_iterations") or str(defaults.get("test_iterations", "3"))).strip()
    top_k = (request.form.get("top_k") or str(defaults.get("top_k", "3"))).strip()
    per_query_timeout_sec = (request.form.get("per_query_timeout_sec") or str(defaults.get("per_query_timeout_sec", "900"))).strip()
    max_queries = (request.form.get("max_queries") or str(defaults.get("max_queries", "0"))).strip()
    if not baseline_threshold:
        baseline_threshold = str(defaults.get("baseline_threshold", "")).strip()
    if not baseline_threshold:
        return jsonify({"error": "missing baseline_threshold"}), 400

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    source_zip_path = input_dir / "migrated_source.zip"
    source_zip.save(str(source_zip_path))

    params = {
        "test_bench": test_bench,
        "app": app_name,
        "source_zip_path": str(source_zip_path),
        "single_test_script": str(bench.get("single_test_script", "website/scripts/run_single_query_test.py")),
        "single_test_args": bench.get("single_test_args") if isinstance(bench.get("single_test_args"), list) else [],
        "overlay_subdir": overlay_subdir,
        "num_compartments": num_compartments,
        "host_cores": host_cores,
        "wayfinder_cores": wayfinder_cores,
        "test_iterations": test_iterations,
        "baseline_metric": baseline_metric,
        "baseline_threshold": baseline_threshold,
        "top_k": top_k,
        "per_query_timeout_sec": per_query_timeout_sec or "900",
        "max_queries": max_queries or "0",
        "use_sudo": True,
    }

    job = Job(id=job_id, kind="workflow_config_search", status="queued", created_at=now_ts(), params=params)
    with LOCK:
        JOBS[job.id] = job
        persist_job(job)

    threading.Thread(target=run_job, args=(job,), daemon=True).start()
    return jsonify({"job": asdict(job)})


@app.get("/api/jobs")
def list_jobs() -> Response:
    with LOCK:
        data = [asdict(j) for j in sorted(JOBS.values(), key=lambda x: x.created_at, reverse=True)]
    return jsonify({"jobs": data})


@app.get("/api/config/test-benches")
def list_test_benches() -> Response:
    benches = list(load_test_bench_configs().values())
    return jsonify({"test_benches": benches})


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    artifacts = list_files_recursive(Path(job.output_dir), limit=2000) if job.output_dir else []
    return jsonify({"job": asdict(job), "artifacts": artifacts})


@app.get("/api/jobs/<job_id>/query-timings")
def get_job_query_timings(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    data = compute_query_timings(job)
    return jsonify(data)


@app.delete("/api/jobs/<job_id>")
def delete_job(job_id: str) -> Response:
    with LOCK:
        deleted, reason = _delete_job(job_id)
    if deleted:
        return jsonify({"ok": True, "job_id": job_id})
    if reason == "still_active":
        return jsonify({"error": "cannot delete queued/running job"}), 409
    return jsonify({"error": "job not found"}), 404


@app.post("/api/jobs/<job_id>/stop")
def stop_job(job_id: str) -> Response:
    proc: Optional[subprocess.Popen[str]] = None

    with LOCK:
        job = JOBS.get(job_id)
        if not job:
            return jsonify({"error": "job not found"}), 404

        if job.status == "queued":
            job.status = "failed"
            job.finished_at = now_ts()
            job.error = "stopped by user"
            persist_job(job)
            return jsonify({"ok": True, "job_id": job_id, "state": "queued-cancelled"})

        if job.status != "running":
            return jsonify({"error": "job is not running"}), 409

        proc = RUNNING_PROCS.get(job_id)
        STOP_REQUESTED.add(job_id)

    if proc is None:
        return jsonify({"ok": True, "job_id": job_id, "state": "stop-requested-no-process"})

    try:
        proc.terminate()
    except Exception:
        try:
            proc.kill()
        except Exception:
            pass

    return jsonify({"ok": True, "job_id": job_id, "state": "stop-requested"})


@app.post("/api/jobs/delete-batch")
def delete_jobs_batch() -> Response:
    job_ids = _parse_delete_ids(request.get_json(silent=True) or {})
    if not job_ids:
        return jsonify({"error": "missing job_ids"}), 400

    deleted: List[str] = []
    skipped_active: List[str] = []
    not_found: List[str] = []

    with LOCK:
        for job_id in job_ids:
            ok, reason = _delete_job(job_id)
            if ok:
                deleted.append(job_id)
            elif reason == "still_active":
                skipped_active.append(job_id)
            else:
                not_found.append(job_id)

    return jsonify({
        "ok": True,
        "deleted": deleted,
        "skipped_active": skipped_active,
        "not_found": not_found,
    })


@app.get("/api/jobs/<job_id>/log-stream")
def get_job_log_stream(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    offset = int(request.args.get("offset", "0"))
    if offset < 0:
        offset = 0

    page_size = int(request.args.get("page_size", str(1024 * 1024)))
    if page_size <= 0:
        page_size = 1024 * 1024
    page_size = min(page_size, 1024 * 1024)

    log_path = resolve_job_log_path(job)
    if not log_path:
        return jsonify({
            "chunk": "",
            "offset": 0,
            "complete": job.status in {"succeeded", "failed"},
            "page": 0,
            "total_pages": 0,
            "total_bytes": 0,
            "page_size": page_size,
        })

    data = log_path.read_text(encoding="utf-8", errors="ignore")
    total_bytes = len(data)

    page_arg = request.args.get("page")
    if page_arg is not None:
        page = int(page_arg)
        if page < 0:
            page = 0
        if total_bytes == 0:
            total_pages = 0
            page = 0
            chunk = ""
        else:
            total_pages = (total_bytes + page_size - 1) // page_size
            if page >= total_pages:
                page = total_pages - 1
            start = page * page_size
            end = min(start + page_size, total_bytes)
            chunk = data[start:end]
        complete = job.status in {"succeeded", "failed"}
        return jsonify({
            "chunk": chunk,
            "offset": 0,
            "complete": complete,
            "page": page,
            "total_pages": total_pages,
            "total_bytes": total_bytes,
            "page_size": page_size,
        })

    if offset > total_bytes:
        offset = total_bytes

    end = min(offset + page_size, total_bytes)
    chunk = data[offset:end]
    new_offset = end
    complete = job.status in {"succeeded", "failed"}
    return jsonify({
        "chunk": chunk,
        "offset": new_offset,
        "complete": complete,
        "truncated": new_offset < total_bytes,
        "total_bytes": total_bytes,
        "page_size": page_size,
    })


@app.get("/api/jobs/<job_id>/log-download")
def download_job_log(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    log_path = resolve_job_log_path(job)
    if not log_path or not log_path.is_file():
        return jsonify({"error": "log not found"}), 404

    return send_file(str(log_path), as_attachment=True, download_name=f"{job_id}.log")


@app.get("/api/jobs/<job_id>/download")
def download_artifact(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    rel_path = (request.args.get("path") or "").strip()
    if not rel_path:
        return jsonify({"error": "missing path"}), 400

    try:
        output_base = Path(job.output_dir)
        real = safe_resolve_under(output_base, rel_path)
    except Exception:
        return jsonify({"error": "invalid path"}), 400

    if not real.is_file():
        return jsonify({"error": "artifact not found"}), 404

    return send_file(str(real), as_attachment=True)


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=8080, debug=False)
