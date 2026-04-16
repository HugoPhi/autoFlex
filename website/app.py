#!/usr/bin/env python3
from __future__ import annotations

import json
import shlex
import subprocess
import threading
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

from flask import Flask, Response, jsonify, render_template, request, send_file

WEB_ROOT = Path(__file__).resolve().parent
PROJECT_ROOT = WEB_ROOT.parent
JOBS_ROOT = WEB_ROOT / "jobs"

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


def safe_resolve_under(base: Path, rel_path: str) -> Path:
    candidate = (base / rel_path).resolve()
    base_resolved = base.resolve()
    if base_resolved not in candidate.parents and candidate != base_resolved:
        raise ValueError("path escapes base directory")
    return candidate


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

        experiment_dir = PROJECT_ROOT / "asplos22-ae" / "experiments" / "fig-06_nginx-redis-perm"
        job_root = JOBS_ROOT / job_id
        script = WEB_ROOT / "scripts" / "run_config_search_nginx_from_zip.py"

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
        ]
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
            rc = proc.wait()

        with LOCK:
            job.return_code = rc
            job.finished_at = now_ts()
            job.status = "succeeded" if rc == 0 else "failed"
            persist_job(job)
    except Exception as exc:  # noqa: BLE001
        with LOCK:
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

    app_name = (request.form.get("app") or "nginx").strip().lower()
    if app_name not in {"nginx", "redis"}:
        return jsonify({"error": "app must be nginx or redis"}), 400

    baseline_metric = (request.form.get("baseline_metric") or "REQ").strip()
    baseline_threshold = (request.form.get("baseline_threshold") or "").strip()
    if not baseline_threshold:
        return jsonify({"error": "missing baseline_threshold"}), 400

    overlay_subdir = (request.form.get("overlay_subdir") or "").strip()
    num_compartments = (request.form.get("num_compartments") or "3").strip()
    host_cores = (request.form.get("host_cores") or "3,4").strip()
    wayfinder_cores = (request.form.get("wayfinder_cores") or "1,2").strip()
    test_iterations = (request.form.get("test_iterations") or "3").strip()
    top_k = (request.form.get("top_k") or "3").strip()

    job_id = uuid.uuid4().hex[:12]
    job_dir = JOBS_ROOT / job_id
    input_dir = job_dir / "input"
    input_dir.mkdir(parents=True, exist_ok=True)
    source_zip_path = input_dir / "migrated_source.zip"
    source_zip.save(str(source_zip_path))

    params = {
        "app": app_name,
        "source_zip_path": str(source_zip_path),
        "overlay_subdir": overlay_subdir,
        "num_compartments": num_compartments,
        "host_cores": host_cores,
        "wayfinder_cores": wayfinder_cores,
        "test_iterations": test_iterations,
        "baseline_metric": baseline_metric,
        "baseline_threshold": baseline_threshold,
        "top_k": top_k,
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


@app.get("/api/jobs/<job_id>")
def get_job(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    artifacts = list_files_recursive(Path(job.output_dir), limit=2000) if job.output_dir else []
    return jsonify({"job": asdict(job), "artifacts": artifacts})


@app.get("/api/jobs/<job_id>/log-stream")
def get_job_log_stream(job_id: str) -> Response:
    job = JOBS.get(job_id)
    if not job:
        return jsonify({"error": "job not found"}), 404

    offset = int(request.args.get("offset", "0"))
    if offset < 0:
        offset = 0

    log_candidates: List[Path] = []
    if job.log_file:
        log_candidates.append(Path(job.log_file))
    if job.output_dir:
        log_candidates.append(Path(job.output_dir) / "build_and_test.log")

    log_path = next((p for p in log_candidates if p.is_file()), None)
    if not log_path:
        return jsonify({"chunk": "", "offset": 0, "complete": job.status in {"succeeded", "failed"}})

    data = log_path.read_text(encoding="utf-8", errors="ignore")
    if offset > len(data):
        offset = len(data)

    chunk = data[offset:]
    new_offset = len(data)
    complete = job.status in {"succeeded", "failed"}
    return jsonify({"chunk": chunk, "offset": new_offset, "complete": complete})


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
