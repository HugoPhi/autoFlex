#!/usr/bin/env bash
set -euo pipefail

usage() {
  cat <<'EOF'
Usage:
  run_wayfinder_build_from_zip.sh \
    --job-id <id> \
    --experiment-dir <path> \
    --app <nginx|redis> \
    --source-zip <path.zip> \
    --work-root <path> \
    [--overlay-subdir <relative/path/in/zip>] \
    [--num-compartments <n>] \
    [--host-cores "3,4"] \
    [--wayfinder-cores "1,2"] \
    [--use-sudo 0|1]
EOF
}

JOB_ID=""
EXPERIMENT_DIR=""
APP=""
SOURCE_ZIP=""
WORK_ROOT=""
OVERLAY_SUBDIR=""
NUM_COMPARTMENTS="3"
HOST_CORES="3,4"
WAYFINDER_CORES="1,2"
USE_SUDO="0"

while [[ $# -gt 0 ]]; do
  case "$1" in
    --job-id) JOB_ID="$2"; shift 2 ;;
    --experiment-dir) EXPERIMENT_DIR="$2"; shift 2 ;;
    --app) APP="$2"; shift 2 ;;
    --source-zip) SOURCE_ZIP="$2"; shift 2 ;;
    --work-root) WORK_ROOT="$2"; shift 2 ;;
    --overlay-subdir) OVERLAY_SUBDIR="$2"; shift 2 ;;
    --num-compartments) NUM_COMPARTMENTS="$2"; shift 2 ;;
    --host-cores) HOST_CORES="$2"; shift 2 ;;
    --wayfinder-cores) WAYFINDER_CORES="$2"; shift 2 ;;
    --use-sudo) USE_SUDO="$2"; shift 2 ;;
    -h|--help) usage; exit 0 ;;
    *) echo "Unknown arg: $1" >&2; usage; exit 1 ;;
  esac
done

if [[ -z "$JOB_ID" || -z "$EXPERIMENT_DIR" || -z "$APP" || -z "$SOURCE_ZIP" || -z "$WORK_ROOT" ]]; then
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

if [[ ! -f "$SOURCE_ZIP" ]]; then
  echo "source zip not found: $SOURCE_ZIP" >&2
  exit 1
fi

mkdir -p "$WORK_ROOT"
JOB_WORK="$WORK_ROOT/work"
SRC_UNZIP="$WORK_ROOT/source"
EXP_COPY="$JOB_WORK/fig-06_nginx-redis-perm"
ART_DIR="$WORK_ROOT/artifacts"
mkdir -p "$JOB_WORK" "$SRC_UNZIP" "$ART_DIR"

rm -rf "$EXP_COPY"
cp -a "$EXPERIMENT_DIR" "$EXP_COPY"

python3 - <<'PY' "$SOURCE_ZIP" "$SRC_UNZIP"
import sys
import zipfile
from pathlib import Path

zip_path = Path(sys.argv[1])
out_dir = Path(sys.argv[2])
out_dir.mkdir(parents=True, exist_ok=True)
with zipfile.ZipFile(zip_path, "r") as zf:
    zf.extractall(out_dir)
print(f"unzipped={zip_path} -> {out_dir}")
PY

if [[ -n "$OVERLAY_SUBDIR" ]]; then
  OVERLAY_SRC="$SRC_UNZIP/$OVERLAY_SUBDIR"
else
  OVERLAY_SRC="$SRC_UNZIP"
fi

if [[ ! -d "$OVERLAY_SRC" ]]; then
  echo "overlay source dir not found: $OVERLAY_SRC" >&2
  exit 1
fi

OVERLAY_DST="$EXP_COPY/_overlay/$APP"
mkdir -p "$OVERLAY_DST"
cp -a "$OVERLAY_SRC"/. "$OVERLAY_DST"/

echo "overlay prepared: $OVERLAY_DST"

APP_DIR="$EXP_COPY/apps/$APP"
ORIG_BUILD="$APP_DIR/build.sh"
WRAP_BUILD="$APP_DIR/build_wrapper.sh"
if [[ ! -f "$ORIG_BUILD" ]]; then
  echo "missing build script: $ORIG_BUILD" >&2
  exit 1
fi

cat > "$WRAP_BUILD" <<EOF
#!/bin/bash
set -euo pipefail
if [[ -d /source-overlay ]]; then
  cp -a /source-overlay/. /usr/src/unikraft/apps/$APP/
fi
EOF
cat "$ORIG_BUILD" >> "$WRAP_BUILD"
chmod +x "$WRAP_BUILD"

TEMPLATE_FILE="$APP_DIR/templates/wayfinder/template.yaml"
python3 - <<'PY' "$TEMPLATE_FILE" "$APP"
import sys
from pathlib import Path

tpl = Path(sys.argv[1])
app = sys.argv[2]
text = tpl.read_text(encoding="utf-8")
text = text.replace(f"./apps/{app}/build.sh", f"./apps/{app}/build_wrapper.sh")
marker = f"  - source: ./apps/{app}/templates/kraft\n    destination: /kraft-yaml-template\n"
insert = marker + f"  - source: ./_overlay/{app}\n    destination: /source-overlay\n"
if "/source-overlay" not in text:
    text = text.replace(marker, insert)
tpl.write_text(text, encoding="utf-8")
print(f"patched template: {tpl}")
PY

SUDO_PREFIX=()
if [[ "$USE_SUDO" == "1" ]]; then
  SUDO_PREFIX=(sudo -E)
fi

pushd "$EXP_COPY" >/dev/null

"${SUDO_PREFIX[@]}" make \
  NUM_COMPARTMENTS="$NUM_COMPARTMENTS" \
  prepare-wayfinder-app-"$APP"

"${SUDO_PREFIX[@]}" make \
  NUM_COMPARTMENTS="$NUM_COMPARTMENTS" \
  HOST_CORES="$HOST_CORES" \
  WAYFINDER_CORES="$WAYFINDER_CORES" \
  run-wayfinder-app-"$APP"

popd >/dev/null

RESULT_DIR="/tmp/fig-06_nginx-redis-perm/wayfinder-build-$APP/results"
if [[ -d "$RESULT_DIR" ]]; then
  tar -czf "$ART_DIR/$APP-results.tar.gz" -C "$RESULT_DIR" .
  find "$RESULT_DIR" -type f | sed "s|$RESULT_DIR/||" | head -n 400 > "$ART_DIR/$APP-results-filelist.txt"
fi

cp -a "$EXP_COPY/apps/$APP/wayfinder-jobs" "$ART_DIR/" || true
cp -a "$EXP_COPY/apps/$APP/templates/wayfinder" "$ART_DIR/" || true
cp -a "$EXP_COPY/apps/$APP/build_wrapper.sh" "$ART_DIR/" || true

echo "job_id=$JOB_ID"
echo "artifact_dir=$ART_DIR"
