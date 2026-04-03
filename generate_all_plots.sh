#!/usr/bin/env bash

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
CONFIG_FILE="${PLOT_CONFIG_FILE:-$SCRIPT_DIR/plot-config.yaml}"
PYTHON_BIN="${PYTHON_BIN:-python3}"

if [[ ! -f "$CONFIG_FILE" ]]; then
  echo "[error] config file not found: $CONFIG_FILE" >&2
  exit 1
fi

exec "$PYTHON_BIN" "$SCRIPT_DIR/generate_figure.py" --config "$CONFIG_FILE" --all "$@"
