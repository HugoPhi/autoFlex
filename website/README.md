# AutoFlex Workflow Platform

## Local start

```bash
cd website
bash scripts/setup_links.sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Open: http://127.0.0.1:8080

## Workflow

### Stage A: Code Porting

- API: `POST /api/workflows/code-porting`
- Input: `source_zip`
- Output artifacts:
  - `migrated_source.zip`
  - `migration_report.json`
  - `migration_report.md`

### Stage B: Config Search

- API: `POST /api/workflows/config-search`
- Inputs:
  - `source_zip`
  - `app` (`nginx` or `redis`)
  - `baseline_metric`
  - `baseline_threshold`
  - `num_compartments`
  - `host_cores`
  - `wayfinder_cores`
  - `test_iterations`
  - `top_k`
  - `overlay_subdir` (optional)
- Notes:
  - `sudo -E` is forced by backend.
  - If wayfinder path fails, script falls back to single-config real build+test.
  - Runner script is selected by the chosen test bench config (`runner_script`), so different benches can execute different scripts.
- Output artifacts:
  - `top_images.tar.gz`
  - `benchmark_<app>.csv`
  - `search_progress.csv`
  - `performance_report.json`
  - `performance_report.md`
  - `build_and_test.log`

## Log view

- UI uses incremental log stream API:
  - `GET /api/jobs/<job_id>/log-stream?offset=<n>`
- Supports long-running job observation and scrollback.

## Test bench extensibility

Test bench definitions are loaded from `website/config/test_benches/*.json`.

Each bench can define its own Stage B runner script:

- `runner_script`: script path, absolute or relative to project root.
- `runner_args`: optional extra CLI arguments appended to the runner command.
- `defaults`: default form values shown/used in UI submission.

Example (`website/config/test_benches/template.json`):

```json
{
  "id": "your-bench-id",
  "name": "human readable bench name",
  "description": "short description of this bench",
  "app": "nginx",
  "runner_script": "website/scripts/run_config_search_nginx_from_zip.py",
  "runner_args": [],
  "defaults": {
    "baseline_metric": "REQ",
    "baseline_threshold": "45000",
    "num_compartments": "3",
    "top_k": "3",
    "host_cores": "3,4",
    "wayfinder_cores": "1,2",
    "test_iterations": "3",
    "overlay_subdir": ""
  }
}
```

Backend implementation location:

- Bench config load: `website/app.py` (`load_test_bench_configs` reads `runner_script` / `runner_args`)
- Stage B command build: `website/app.py` (`build_command` resolves and executes bench-defined `runner_script`)
- Stage B job creation: `website/app.py` (`create_workflow_config_search_job` persists selected bench runner into `params`)

Compatibility note:

- A custom `runner_script` should accept the same Stage B CLI options currently passed by backend (`--job-id`, `--source-zip`, `--experiment-dir`, `--work-root`, `--app`, `--num-compartments`, `--host-cores`, `--wayfinder-cores`, `--test-iterations`, `--baseline-metric`, `--baseline-threshold`, `--top-k`, `--use-sudo`, and optional `--overlay-subdir`).
