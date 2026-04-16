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
