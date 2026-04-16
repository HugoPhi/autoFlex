#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
WEB_ROOT="$(cd "$SCRIPT_DIR/.." && pwd)"
PROJECT_ROOT="$(cd "$WEB_ROOT/.." && pwd)"
LINK_DIR="$WEB_ROOT/linked"

mkdir -p "$LINK_DIR"

link_one() {
  local src="$1"
  local dst_name="$2"
  local dst="$LINK_DIR/$dst_name"

  if [[ -L "$dst" || -e "$dst" ]]; then
    rm -rf "$dst"
  fi

  ln -s "$src" "$dst"
  echo "linked: $dst -> $src"
}

link_one "$PROJECT_ROOT/autoGen" "autoGen"
link_one "$PROJECT_ROOT/search" "search"
link_one "$PROJECT_ROOT/figures" "figures"
link_one "$PROJECT_ROOT/generate_figure.py" "generate_figure.py"
link_one "$PROJECT_ROOT/plot-config.yaml" "plot-config.yaml"

echo "done"
