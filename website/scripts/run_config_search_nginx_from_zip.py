#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import tarfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Set, Tuple


@dataclass
class SearchResult:
    strategy: str
    threshold: float
    query_count: int
    first_hit_query: int
    feasible_count: int
    frontier: List[str]


def run_cmd(cmd: List[str], cwd: Path, log_path: Path) -> None:
    with log_path.open("a", encoding="utf-8") as logf:
        logf.write("$ " + " ".join(cmd) + "\n")
        proc = subprocess.Popen(cmd, cwd=str(cwd), stdout=logf, stderr=subprocess.STDOUT, text=True)
        rc = proc.wait()
        if rc != 0:
            raise RuntimeError(f"command failed ({rc}): {' '.join(cmd)}")


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
    wrapper = (
        "#!/bin/bash\n"
        "set -euo pipefail\n"
        "export USE_UKSP=${USE_UKSP:-n}\n"
        f"if [[ -d /source-overlay ]]; then cp -a /source-overlay/. /usr/src/unikraft/apps/{app}/; fi\n"
    )
    wrap_build.write_text(wrapper + orig_build.read_text(encoding="utf-8"), encoding="utf-8")
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


def parse_benchmark_csv(csv_path: Path, app: str) -> Dict[str, List[float]]:
    out: Dict[str, List[float]] = {}
    lines = csv_path.read_text(encoding="utf-8", errors="ignore").splitlines()
    for ln in lines[1:]:
        row = [x.strip().strip('"') for x in next(csv.reader([ln]))]
        if len(row) < 5:
            continue
        taskid, _chunk, _iter, method, value = row[:5]
        if app == "nginx" and method != "REQ":
            continue
        if app == "redis" and method.upper() == "TIMEOUT":
            continue
        try:
            v = float(value)
        except Exception:
            continue
        out.setdefault(taskid, []).append(v)
    return out


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


def run_single_config_fallback(
    exp_copy: Path,
    artifacts: Path,
    report_dir: Path,
    log_path: Path,
    test_iterations: str,
    sudo_prefix: List[str],
    app: str,
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

    bench = parse_benchmark_csv(bench_csv, app)
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
        "mean_req": metric,
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
    args = parser.parse_args()

    source_zip = Path(args.source_zip).resolve()
    experiment_dir = Path(args.experiment_dir).resolve()
    work_root = Path(args.work_root).resolve()
    app = str(args.app).strip().lower()

    if not source_zip.is_file():
        raise SystemExit(f"source zip not found: {source_zip}")
    if not experiment_dir.is_dir():
        raise SystemExit(f"experiment dir not found: {experiment_dir}")
    if app not in {"nginx", "redis"}:
        raise SystemExit("--app must be nginx or redis")

    threshold = float(args.baseline_threshold)
    top_k = int(args.top_k)

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

    mode = "wayfinder"
    selected_payload: List[Dict[str, Any]] = []
    frontier: List[str] = []
    tasks_json: Path | None = None
    bench_csv = report_dir / f"benchmark_{app}.csv"
    progress_csv = report_dir / "search_progress.csv"

    try:
        wayfinder_bin = Path("/tmp/fig-06_nginx-redis-perm/wayfinder/dist/wayfinder")
        if not wayfinder_bin.is_file():
            run_cmd(sudo_prefix + ["make", "install-wayfinder"], exp_copy, log_path)

        run_cmd(sudo_prefix + ["make", f"NUM_COMPARTMENTS={args.num_compartments}", f"prepare-wayfinder-app-{app}"], exp_copy, log_path)
        run_cmd(
            sudo_prefix
            + [
                "make",
                f"NUM_COMPARTMENTS={args.num_compartments}",
                f"HOST_CORES={args.host_cores}",
                f"WAYFINDER_CORES={args.wayfinder_cores}",
                f"run-wayfinder-app-{app}",
            ],
            exp_copy,
            log_path,
        )
        run_cmd(sudo_prefix + ["make", f"TEST_ITERATIONS={args.test_iterations}", f"RESULTS={bench_csv}", f"test-app-{app}"], exp_copy, log_path)

        results_dir = Path(f"/tmp/fig-06_nginx-redis-perm/wayfinder-build-{app}/results")
        tasks_json = results_dir / "tasks.json"
        if not tasks_json.is_file():
            raise RuntimeError(f"missing tasks.json: {tasks_json}")

        tasks = parse_tasks(tasks_json)
        bench = parse_benchmark_csv(bench_csv, app)
        perf: Dict[str, float] = {tid: mean(vals) for tid, vals in bench.items() if vals}
        nodes = sorted([tid for tid in tasks.keys() if tid in perf])
        if not nodes:
            raise RuntimeError("no benchmark data parsed from test output")

        vectors = build_vectors(tasks)
        all_keys = sorted({k for tid in nodes for k in vectors[tid].keys()})
        anc, desc = closures(nodes, vectors, all_keys)
        sr = run_balanced(nodes, perf, threshold, anc, desc, progress_csv)

        feasible = {n for n in nodes if perf.get(n, 0.0) >= threshold}
        frontier = maximal(feasible, vectors, all_keys)

        selected = frontier[:top_k]
        if len(selected) < top_k:
            extras = [n for n in sorted(nodes, key=lambda x: perf.get(x, 0.0), reverse=True) if n not in selected]
            selected.extend(extras[: (top_k - len(selected))])

        img_out = artifacts / "top_images"
        img_out.mkdir(parents=True, exist_ok=True)
        image_glob = "*nginx_kvm-x86_64*" if app == "nginx" else "*redis_kvm-x86_64*"

        for tid in selected:
            src_task = results_dir / tid
            dst_task = img_out / tid
            dst_task.mkdir(parents=True, exist_ok=True)

            copied = []
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
                    "mean_req": perf.get(tid, 0.0),
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
        mode = "single-config-fallback"
        with log_path.open("a", encoding="utf-8") as logf:
            logf.write(f"[fallback] wayfinder flow failed: {exc}\n")

        perf, selected_payload, meta = run_single_config_fallback(
            exp_copy=exp_copy,
            artifacts=artifacts,
            report_dir=report_dir,
            log_path=log_path,
            test_iterations=args.test_iterations,
            sudo_prefix=sudo_prefix,
            app=app,
            threshold=threshold,
        )
        frontier = meta["frontier_taskids"]
        balanced_meta = {
            "query_count": meta["query_count"],
            "first_hit_query": meta["first_hit_query"],
            "feasible_count_observed": len([x for x in selected_payload if x.get("mean_req", 0.0) >= threshold]),
        }

    with tarfile.open(artifacts / "top_images.tar.gz", "w:gz") as tf:
        tf.add(artifacts / "top_images", arcname="top_images")

    if bench_csv.is_file():
        shutil.copy2(bench_csv, artifacts / f"benchmark_{app}.csv")
    if progress_csv.is_file():
        shutil.copy2(progress_csv, artifacts / "search_progress.csv")
    if tasks_json and tasks_json.is_file():
        shutil.copy2(tasks_json, artifacts / "tasks.json")

    report = {
        "job_id": args.job_id,
        "status": "ok",
        "mode": mode,
        "app": app,
        "baseline_metric": args.baseline_metric,
        "baseline_threshold": threshold,
        "num_nodes_with_perf": len(selected_payload),
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
        f"- baseline_metric: {args.baseline_metric}",
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
        md.append(f"- task={item['taskid']}, mean_metric={item['mean_req']:.2f}, files={len(item['copied_files'])}")
    (report_dir / "performance_report.md").write_text("\n".join(md) + "\n", encoding="utf-8")

    shutil.copy2(report_dir / "performance_report.json", artifacts / "performance_report.json")
    shutil.copy2(report_dir / "performance_report.md", artifacts / "performance_report.md")
    shutil.copy2(log_path, artifacts / "build_and_test.log")

    print(f"job_id={args.job_id}")
    print(f"artifact_dir={artifacts}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
