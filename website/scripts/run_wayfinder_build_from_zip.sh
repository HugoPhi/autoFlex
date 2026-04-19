#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_wayfinder_build_from_zip.sh \
    --job-id <id> \
    --experiment-dir <prepared fig06 path> \
    --app <nginx|redis> \
    --work-root <path> \
    --task-id <task id> \
    --task-config-json <config json file> \
    [--use-sudo 0|1]
EOF
}

JOB_ID=""
EXPERIMENT_DIR=""
APP=""
WORK_ROOT=""
TASK_ID=""
TASK_CONFIG_JSON=""
USE_SUDO="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id) JOB_ID="$2"; shift 2 ;;
    --experiment-dir) EXPERIMENT_DIR="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --work-root) WORK_ROOT="$2"; shift 2 ;;
    --task-id) TASK_ID="$2"; shift 2 ;;
    --task-config-json) TASK_CONFIG_JSON="$2"; shift 2 ;;
    --use-sudo) USE_SUDO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$JOB_ID" || -z "$EXPERIMENT_DIR" || -z "$APP" || -z "$WORK_ROOT" || -z "$TASK_ID" || -z "$TASK_CONFIG_JSON" ]]; then
  usage
  exit 1
fi

if [[ "$APP" != "nginx" && "$APP" != "redis" ]]; then
  echo "APP must be nginx or redis" >&2
  exit 1
fi

if [[ ! -d "$EXPERIMENT_DIR" ]]; then
  echo "experiment dir not found: $EXPERIMENT_DIR" >&2
  exit 1
fi

if [[ ! -f "$TASK_CONFIG_JSON" ]]; then
  echo "task config json not found: $TASK_CONFIG_JSON" >&2
  exit 1
fi

mkdir -p "$WORK_ROOT"
QUERY_ROOT="$WORK_ROOT/query-builds/$TASK_ID"
OUT_TASK_DIR="$QUERY_ROOT/results/$TASK_ID"
DOCKER_OUT="$QUERY_ROOT/docker_out"
ART_DIR="$WORK_ROOT/artifacts"
mkdir -p "$OUT_TASK_DIR" "$DOCKER_OUT" "$ART_DIR"

APP_DIR="$EXPERIMENT_DIR/apps/$APP"
WRAP_BUILD="$APP_DIR/build_wrapper.sh"
if [[ ! -f "$WRAP_BUILD" ]]; then
  echo "missing build wrapper script: $WRAP_BUILD" >&2
  exit 1
fi

KRAFT_TEMPLATE_DIR="$APP_DIR/templates/kraft"
if [[ ! -d "$KRAFT_TEMPLATE_DIR" ]]; then
  echo "missing kraft template dir: $KRAFT_TEMPLATE_DIR" >&2
  exit 1
fi

OVERLAY_DIR="$EXPERIMENT_DIR/_overlay/$APP"
if [[ ! -d "$OVERLAY_DIR" ]]; then
  echo "overlay dir not found (expected to be prepared by runner): $OVERLAY_DIR" >&2
  exit 1
fi

IMAGE_NAME="nginx_kvm-x86_64"
APP_IMAGE="ghcr.io/project-flexos/nginx:latest"
if [[ "$APP" == "redis" ]]; then
  IMAGE_NAME="redis_kvm-x86_64"
  APP_IMAGE="ghcr.io/project-flexos/redis:latest"
fi

ENV_FILE="$QUERY_ROOT/build.env"
python3 - <<'PY' "$TASK_CONFIG_JSON" "$ENV_FILE"
import json
import re
import sys
from pathlib import Path

config_path = Path(sys.argv[1])
env_path = Path(sys.argv[2])
data = json.loads(config_path.read_text(encoding="utf-8"))
if not isinstance(data, dict):
    raise SystemExit("task config must be a json object")

items = {}
for k, v in data.items():
    key = str(k).strip().upper()
    if key == "TASKID":
        continue
    if not re.match(r"^[A-Z0-9_]+$", key):
        raise SystemExit(f"invalid env key: {key}")
    items[key] = str(v).strip()

if not items.get("NUM_COMPARTMENTS"):
    items["NUM_COMPARTMENTS"] = "3"

lines = [f"{k}={v}" for k, v in sorted(items.items())]
env_path.parent.mkdir(parents=True, exist_ok=True)
env_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
PY

SUDO_PREFIX=()
if [[ "$USE_SUDO" == "1" ]]; then
  SUDO_PREFIX=(sudo -n -E)
fi

DOCKER_CMD=(
  docker run --rm --entrypoint ""
  --env-file "$ENV_FILE"
  -e TEMPLDIR=/kraft-yaml-template
  -v "$WRAP_BUILD:/build.sh:ro"
  -v "$KRAFT_TEMPLATE_DIR:/kraft-yaml-template:ro"
  -v "$OVERLAY_DIR:/source-overlay:ro"
  -v "$DOCKER_OUT:/out"
  "$APP_IMAGE"
  bash -lc
  "set -euo pipefail; /build.sh; mkdir -p /out/build; cp -av /usr/src/unikraft/apps/$APP/build/${IMAGE_NAME}* /out/build/; cp -av /usr/src/unikraft/apps/$APP/{kraft.yaml,config,build.log} /out/build/"
)

echo "[single-build] task=$TASK_ID app=$APP"
echo "$ ${DOCKER_CMD[*]}"
"${SUDO_PREFIX[@]}" "${DOCKER_CMD[@]}"

APP_OUT_DIR="$OUT_TASK_DIR/usr/src/unikraft/apps/$APP"
mkdir -p "$APP_OUT_DIR/build"

cp -f "$DOCKER_OUT/build/$IMAGE_NAME" "$APP_OUT_DIR/build/$IMAGE_NAME"
if [[ -f "$DOCKER_OUT/build/$IMAGE_NAME.dbg" ]]; then
  cp -f "$DOCKER_OUT/build/$IMAGE_NAME.dbg" "$APP_OUT_DIR/build/$IMAGE_NAME.dbg"
fi
for f in build.log config kraft.yaml; do
  if [[ -f "$DOCKER_OUT/build/$f" ]]; then
    cp -f "$DOCKER_OUT/build/$f" "$APP_OUT_DIR/$f"
  fi
done

python3 - <<'PY' "$TASK_CONFIG_JSON" "$QUERY_ROOT/build_meta.json" "$TASK_ID" "$APP" "$APP_OUT_DIR/build/$IMAGE_NAME"
import json
import sys
from pathlib import Path

cfg = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
meta_path = Path(sys.argv[2])
task_id = sys.argv[3]
app = sys.argv[4]
image = Path(sys.argv[5])
meta = {
    "taskid": task_id,
    "app": app,
    "image": str(image),
    "config": cfg,
}
meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=True), encoding="utf-8")
PY

echo "job_id=$JOB_ID"
echo "artifact_dir=$ART_DIR"
echo "task_dir=$OUT_TASK_DIR"
