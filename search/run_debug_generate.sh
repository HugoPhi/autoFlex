#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$ROOT_DIR/../figures/search}"

PYTHON_BIN="${PYTHON_BIN:-python3}"

log_stage() {
  local idx="$1"
  local total="$2"
  local msg="$3"
  echo "[$idx/$total] $msg"
}

require_file() {
  local path="$1"
  local label="$2"
  if [[ ! -f "$path" ]]; then
    echo "error: missing $label: $path" >&2
    exit 1
  fi
}

if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "error: python runtime not found: $PYTHON_BIN" >&2
  exit 1
fi

REQUIRED_SCRIPTS=(
  "fig08_build_poset_python.py"
  "validate_all_hypothesis.py"
  "dag_poset_search_cli.py"
  "epsilon_exceedance_stats.py"
  "fig08_plot_nginx_search_path.py"
  "evaluate_search_baselines_multi.py"
  "plot_search_baseline_multi_metric.py"
  "plot_search_baseline_by_threshold.py"
  "select_useful_thresholds_for_ours.py"
)

for s in "${REQUIRED_SCRIPTS[@]}"; do
  require_file "$ROOT_DIR/$s" "script"
done

NGINX_CONFIG_MAP="${NGINX_CONFIG_MAP:-$ROOT_DIR/data/nginx_config_map.csv}"
REDIS_CONFIG_MAP="${REDIS_CONFIG_MAP:-$ROOT_DIR/data/redis_config_map.csv}"
THRESHOLD_LIST="${THRESHOLD_LIST:-[45000,302000,140200]}"
EPSILON="${EPSILON:-0}"
EPSILON_MODE="${EPSILON_MODE:-absolute}"
TOP_N="${TOP_N:-20}"
NGINX_PATH_THRESHOLD="${NGINX_PATH_THRESHOLD:-45000}"
PNG_DPI="${PNG_DPI:-300}"
REQ_THRESHOLDS="${REQ_THRESHOLDS:-39000,42000,45000,48000,51000}"
GET_THRESHOLDS="${GET_THRESHOLDS:-250000,280000,302000,324000,346000}"
SET_THRESHOLDS="${SET_THRESHOLDS:-112000,126000,140200,154000,168000}"
SEEDS="${SEEDS:-0,1,2,3,4,5,6,7,8,9}"
FOCUS_TOP_K="${FOCUS_TOP_K:-3}"
FOCUS_QUERY_MARGIN="${FOCUS_QUERY_MARGIN:-0.01}"
FOCUS_FIRST_RESULT_MARGIN="${FOCUS_FIRST_RESULT_MARGIN:-1.0}"

require_file "$NGINX_CONFIG_MAP" "nginx config map"
require_file "$REDIS_CONFIG_MAP" "redis config map"

mkdir -p "$OUTPUT_DIR"/{svg,png}
rm -f "$OUTPUT_DIR"/{*.dot,*.svg,*.csv,svg/*,png/*}

echo "Configuration:"
echo "  PYTHON_BIN=$PYTHON_BIN"
echo "  THRESHOLD_LIST=$THRESHOLD_LIST"
echo "  NGINX_PATH_THRESHOLD=$NGINX_PATH_THRESHOLD"
echo "  EPSILON=$EPSILON"
echo "  EPSILON_MODE=$EPSILON_MODE"
echo "  TOP_N=$TOP_N"
echo "  PNG_DPI=$PNG_DPI"
echo "  REQ_THRESHOLDS=$REQ_THRESHOLDS"
echo "  GET_THRESHOLDS=$GET_THRESHOLDS"
echo "  SET_THRESHOLDS=$SET_THRESHOLDS"
echo "  SEEDS=$SEEDS"
echo "  FOCUS_TOP_K=$FOCUS_TOP_K"
echo "  FOCUS_QUERY_MARGIN=$FOCUS_QUERY_MARGIN"
echo "  FOCUS_FIRST_RESULT_MARGIN=$FOCUS_FIRST_RESULT_MARGIN"

log_stage 1 9 "Generating fig08 DAG artifacts..."
"$PYTHON_BIN" "$ROOT_DIR/fig08_build_poset_python.py" \
  --config-map "$NGINX_CONFIG_MAP" \
  --method REQ \
  --out-dot "$OUTPUT_DIR/fig08_relations.dot" \
  --out-svg "$OUTPUT_DIR/svg/fig08_plot.svg" \
  --out-png "$OUTPUT_DIR/png/fig08_plot.png" \
  --png-dpi "$PNG_DPI"

log_stage 2 9 "Generating hypothesis report artifacts and A-to-B scatter plots..."
"$PYTHON_BIN" "$ROOT_DIR/validate_all_hypothesis.py" \
  --nginx-config-map "$NGINX_CONFIG_MAP" \
  --redis-config-map "$REDIS_CONFIG_MAP" \
  --epsilon "$EPSILON" \
  --epsilon-mode "$EPSILON_MODE" \
  --top-n "$TOP_N" \
  --out-dir "$OUTPUT_DIR"

log_stage 3 9 "Generating DAG search summary and trace..."
"$PYTHON_BIN" "$ROOT_DIR/dag_poset_search_cli.py" \
  --nginx-config-map "$NGINX_CONFIG_MAP" \
  --redis-config-map "$REDIS_CONFIG_MAP" \
  --threshold-list "$THRESHOLD_LIST" \
  --out-summary "$OUTPUT_DIR/dag_search_summary.csv" \
  --out-trace "$OUTPUT_DIR/dag_search_trace.csv"

log_stage 4 9 "Generating epsilon exceedance statistics..."
"$PYTHON_BIN" "$ROOT_DIR/epsilon_exceedance_stats.py" \
  --nginx-config-map "$NGINX_CONFIG_MAP" \
  --redis-config-map "$REDIS_CONFIG_MAP" \
  --out-csv "$OUTPUT_DIR/epsilon_exceedance_stats_anomaly_edges.csv"

log_stage 5 9 "Generating nginx search-path figure..."
"$PYTHON_BIN" "$ROOT_DIR/fig08_plot_nginx_search_path.py" \
  --trace-csv "$OUTPUT_DIR/dag_search_trace.csv" \
  --summary-csv "$OUTPUT_DIR/dag_search_summary.csv" \
  --nginx-config-map "$NGINX_CONFIG_MAP" \
  --threshold "$NGINX_PATH_THRESHOLD" \
  --out-dot "$OUTPUT_DIR/nginx_search_path.dot" \
  --out-svg "$OUTPUT_DIR/svg/nginx_search_path.svg" \
  --out-png "$OUTPUT_DIR/png/nginx_search_path.png" \
  --png-dpi "$PNG_DPI"

log_stage 6 9 "Evaluating baselines across multiple thresholds and seeds..."
"$PYTHON_BIN" "$ROOT_DIR/evaluate_search_baselines_multi.py" \
  --nginx-config-map "$NGINX_CONFIG_MAP" \
  --redis-config-map "$REDIS_CONFIG_MAP" \
  --req-thresholds "$REQ_THRESHOLDS" \
  --get-thresholds "$GET_THRESHOLDS" \
  --set-thresholds "$SET_THRESHOLDS" \
  --seeds "$SEEDS" \
  --out-detail "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --out-agg "$OUTPUT_DIR/dag_search_multi_agg.csv"

log_stage 7 9 "Generating averaged metric comparison figures..."
"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_multi_metric.py" \
  --agg-csv "$OUTPUT_DIR/dag_search_multi_agg.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/svg/search_baseline_query_ratio_avg.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_multi_metric.py" \
  --agg-csv "$OUTPUT_DIR/dag_search_multi_agg.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/png/search_baseline_query_ratio_avg.png"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_multi_metric.py" \
  --agg-csv "$OUTPUT_DIR/dag_search_multi_agg.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/svg/search_baseline_first_result_avg.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_multi_metric.py" \
  --agg-csv "$OUTPUT_DIR/dag_search_multi_agg.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/png/search_baseline_first_result_avg.png"

log_stage 8 9 "Generating threshold-panel metric figures..."
"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/svg/search_baseline_query_ratio_by_threshold.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/png/search_baseline_query_ratio_by_threshold.png"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/svg/search_baseline_first_result_by_threshold.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/png/search_baseline_first_result_by_threshold.png"

log_stage 9 9 "Selecting useful thresholds for ours and generating focus panels..."
"$PYTHON_BIN" "$ROOT_DIR/select_useful_thresholds_for_ours.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail.csv" \
  --top-k "$FOCUS_TOP_K" \
  --query-margin "$FOCUS_QUERY_MARGIN" \
  --first-result-margin "$FOCUS_FIRST_RESULT_MARGIN" \
  --out-focus-detail "$OUTPUT_DIR/dag_search_multi_detail_focus.csv"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail_focus.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/svg/search_baseline_query_ratio_focus.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail_focus.csv" \
  --metric query_ratio \
  --output "$OUTPUT_DIR/png/search_baseline_query_ratio_focus.png"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail_focus.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/svg/search_baseline_first_result_focus.svg"

"$PYTHON_BIN" "$ROOT_DIR/plot_search_baseline_by_threshold.py" \
  --detail-csv "$OUTPUT_DIR/dag_search_multi_detail_focus.csv" \
  --metric first_result_query \
  --output "$OUTPUT_DIR/png/search_baseline_first_result_focus.png"

echo "done. generated files in $OUTPUT_DIR:"
ls -1 "$OUTPUT_DIR" | sort
