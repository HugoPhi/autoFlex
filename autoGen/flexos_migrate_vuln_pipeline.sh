#!/usr/bin/env bash
set -euo pipefail

# FlexOS migration + vulnerability detection pipeline.
# It reuses the workflow from unikraft/flexos-support/porthelper and adds
# post-migration security checks in one command.

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
AUTOGEN_DIR="$SCRIPT_DIR"
THIRD_PARTY_DIR="$AUTOGEN_DIR/third_party"
DEFAULT_UNIKRAFT_DIR="$THIRD_PARTY_DIR/unikraft"
WORK_DIR="$AUTOGEN_DIR/.flexos_pipeline"

UNICOLOR_RED='\033[0;31m'
UNICOLOR_GREEN='\033[0;32m'
UNICOLOR_YELLOW='\033[1;33m'
UNICOLOR_BLUE='\033[0;34m'
UNICOLOR_NC='\033[0m'

log() {
  printf "%b[INFO]%b %s\n" "$UNICOLOR_BLUE" "$UNICOLOR_NC" "$*"
}

warn() {
  printf "%b[WARN]%b %s\n" "$UNICOLOR_YELLOW" "$UNICOLOR_NC" "$*"
}

err() {
  printf "%b[ERR ]%b %s\n" "$UNICOLOR_RED" "$UNICOLOR_NC" "$*" >&2
}

ok() {
  printf "%b[ OK ]%b %s\n" "$UNICOLOR_GREEN" "$UNICOLOR_NC" "$*"
}

usage() {
  cat <<'EOF'
Usage:
  ./flexos_migrate_vuln_pipeline.sh --target-file <path/to/file.c> [options]

Required:
  --target-file <path>         Target C source file to migrate.

Optional:
  --unikraft-dir <path>        Unikraft repo path.
                               Default: autoGen/third_party/unikraft
  --report-dir <path>          Output report directory.
                               Default: autoGen/.flexos_pipeline/reports/<timestamp>
  --skip-clone                 Do not clone unikraft when repo is missing.
  --no-proxy                   Do not auto-enable proxy before cloning.
  --clone-depth <n>            Clone depth when auto-cloning. Default: 1
  --help                       Show this help.

Examples:
  ./flexos_migrate_vuln_pipeline.sh \
    --target-file autoGen/dataset/nginx/raw/src/http/ngx_http.c

  ./flexos_migrate_vuln_pipeline.sh \
    --target-file autoGen/dataset/redis/raw/src/server.c \
    --unikraft-dir autoGen/third_party/unikraft
EOF
}

require_cmd() {
  local cmd="$1"
  if ! command -v "$cmd" >/dev/null 2>&1; then
    err "Missing required command: $cmd"
    return 1
  fi
}

enable_proxy_if_possible() {
  if [[ "${NO_PROXY_AUTO}" == "1" ]]; then
    return 0
  fi

  if [[ -n "${http_proxy:-}" || -n "${https_proxy:-}" || -n "${all_proxy:-}" ]]; then
    ok "Proxy env already present; keep using current proxy settings."
    return 0
  fi

  if command -v zsh >/dev/null 2>&1; then
    # The user's proxy helper is typically a zsh function in ~/.zshrc.
    if zsh -lc 'source ~/.zshrc >/dev/null 2>&1; type proxy >/dev/null 2>&1'; then
      log "Enabling proxy via zsh function: proxy"
      zsh -lc 'source ~/.zshrc && proxy' || true
      return 0
    fi
  fi

  warn "No proxy helper found; cloning will use current network settings."
}

clone_unikraft_if_needed() {
  if [[ -d "$UNIKRAFT_DIR/.git" ]]; then
    ok "Found existing unikraft repo: $UNIKRAFT_DIR"
    return 0
  fi

  if [[ "$SKIP_CLONE" == "1" ]]; then
    err "Unikraft repo missing and --skip-clone is set."
    return 1
  fi

  mkdir -p "$(dirname "$UNIKRAFT_DIR")"
  enable_proxy_if_possible

  log "Cloning project-flexos/unikraft into $UNIKRAFT_DIR"
  git clone --depth "$CLONE_DEPTH" https://github.com/project-flexos/unikraft.git "$UNIKRAFT_DIR"
  ok "Clone finished"
}

prepare_workspace() {
  TIMESTAMP="$(date +%Y%m%d_%H%M%S)"
  REPORT_DIR="${REPORT_DIR:-$WORK_DIR/reports/$TIMESTAMP}"
  TMP_DIR="$WORK_DIR/tmp/$TIMESTAMP"

  mkdir -p "$REPORT_DIR" "$TMP_DIR"
  CALLFILE="$TMP_DIR/callfile.csv"
  RULEFILE="$TMP_DIR/porthelper.cocci"
  RAW_DEPS="$TMP_DIR/res.deps"
  RAW_SYMS="$TMP_DIR/res.symb"
  RAW_CSCOPE="$TMP_DIR/cscope"
  MIGRATION_DIFF="$REPORT_DIR/migration.diff"
  GATE_COVERAGE="$REPORT_DIR/gate_coverage.txt"

  ok "Report directory: $REPORT_DIR"
}

create_callfile_from_deps() {
  local parser_py="$TMP_DIR/parse_results_local.py"

  cat > "$parser_py" <<'PY'
#!/usr/bin/env python3
import csv
import pathlib

raw_deps = pathlib.Path(__import__('os').environ['RAW_DEPS'])
out_file = pathlib.Path(__import__('os').environ['CALLFILE'])

lines = []
if raw_deps.exists():
    lines = [line.rstrip("\n") for line in raw_deps.read_text(encoding="utf-8", errors="ignore").splitlines() if line.strip()]

with out_file.open("w", newline="\n", encoding="utf-8") as f:
    writer = csv.writer(f, delimiter=",", lineterminator="\n", quotechar="|", quoting=csv.QUOTE_MINIMAL)
    for line in lines:
        parts = line.split()
        if len(parts) < 2:
            continue
        function_name = parts[1]

        lib_name = None
        if "unikraft/lib/" in line:
            try:
                segs = line.split("/")
                idx = segs.index("lib")
                base = segs[idx + 1]
                lib_name = "libc" if base in ("nolibc", "newlib") else f"lib{base}"
            except Exception:
                lib_name = None
        elif "libs/" in line:
            try:
                segs = line.split("/")
                idx = segs.index("libs")
                base = segs[idx + 1]
                lib_name = "libc" if base in ("nolibc", "newlib") else f"lib{base}"
            except Exception:
                lib_name = None

        if lib_name:
            writer.writerow([function_name, lib_name])
PY

  chmod +x "$parser_py"
  RAW_DEPS="$RAW_DEPS" CALLFILE="$CALLFILE" "$parser_py"
}

run_porthelper_migration() {
  local rel_target
  rel_target="${TARGET_FILE#$UNIKRAFT_DIR/}"

  if [[ "$rel_target" == "$TARGET_FILE" ]]; then
    err "Target file must be inside unikraft repo: $UNIKRAFT_DIR"
    return 1
  fi

  log "Step 1/4: build cscope DB and resolve external symbols"
  (
    cd "$UNIKRAFT_DIR"

    rm -f "$RAW_SYMS" "$RAW_DEPS"

    rm -f cscope* cscope.files
    cscope -L -2 ".*" "$rel_target" 2>/dev/null | grep -v "extern" | grep -v "/usr/" | awk '{print $2}' | sort -u > "$RAW_SYMS" || true

    find . -name '*.c' > cscope.files
    cscope -b -q -k

    : > "$RAW_DEPS"
    while IFS= read -r sym; do
      [[ -z "$sym" ]] && continue
      if [[ "$(cscope -d -L1 "$sym" | grep ".*(.*)" | grep -v "newlib" | grep -v "define" | grep -v "lwip-2.1.2/src/apps/" | sort -u | wc -l)" -eq 1 ]]; then
        cscope -d -L1 "$sym" | grep ".*(.*)" | grep -v "newlib" | grep -v "define" | grep -v "lwip-2.1.2/src/apps/" | sort -u >> "$RAW_DEPS"
      fi
    done < "$RAW_SYMS"

    rm -f cscope* cscope.files
  )

  log "Step 2/4: generate callfile and coccinelle rules"
  create_callfile_from_deps

  cat > "$RULEFILE" <<'EOF'
EOF
  local i=0
  while IFS=, read -r fname lname; do
    [[ -z "$fname" || -z "$lname" ]] && continue
    cat >> "$RULEFILE" <<EOF
@return${i}@
expression list EL;
expression ret, var;
@@
- var = ${fname}(EL);
+ flexos_gate(${lname}, var, ${fname}, EL);

@noreturn${i}@
expression list EL;
expression ret, var;
@@
- ${fname}(EL);
+ flexos_gate(${lname}, ${fname}, EL);

EOF
    i=$((i + 1))
  done < "$CALLFILE"

  log "Step 3/4: apply migration rules with spatch"
  cp "$TARGET_FILE" "$TMP_DIR/original.c"
  if [[ "$i" -gt 0 ]]; then
    spatch -sp_file "$RULEFILE" "$TARGET_FILE" | tee "$MIGRATION_DIFF" >/dev/null || true
  else
    echo "No external calls resolved; skip spatch rule application." > "$MIGRATION_DIFF"
    warn "No migration rules generated; skipping spatch."
  fi

  log "Step 4/4: post-migration gate coverage check"
  CALLFILE="$CALLFILE" TARGET_FILE="$TARGET_FILE" python3 - <<'PY' > "$GATE_COVERAGE"
import csv
import pathlib
import re
import os

callfile = pathlib.Path(os.environ["CALLFILE"])
target = pathlib.Path(os.environ["TARGET_FILE"])

if not callfile.exists():
    print("callfile missing; skip gate coverage check")
    raise SystemExit(0)

funcs = []
with callfile.open(encoding="utf-8", errors="ignore") as f:
    for row in csv.reader(f):
        if len(row) >= 1 and row[0].strip():
            funcs.append(row[0].strip())

src = target.read_text(encoding="utf-8", errors="ignore").splitlines()

hits = []
for ln, line in enumerate(src, start=1):
    if "flexos_gate(" in line or "flexos_gate_r(" in line:
        continue
    for fn in funcs:
        if re.search(rf"\b{re.escape(fn)}\s*\(", line):
            hits.append((ln, fn, line.strip()))

print(f"checked_functions={len(set(funcs))}")
print(f"possible_ungated_calls={len(hits)}")
for ln, fn, txt in hits[:200]:
    print(f"L{ln}: {fn}: {txt}")
PY

  ok "Migration stage done"
}

run_vuln_scans() {
  log "Running vulnerability scanners (if installed)"

  local has_any=0

  if command -v cppcheck >/dev/null 2>&1; then
    has_any=1
    cppcheck --enable=warning,style,performance,portability,information --inconclusive \
      --language=c --std=c11 --quiet "$TARGET_FILE" \
      2> "$REPORT_DIR/cppcheck.txt" || true
  else
    warn "cppcheck not found; skip cppcheck stage"
  fi

  if command -v semgrep >/dev/null 2>&1; then
    has_any=1
    semgrep --config auto "$TARGET_FILE" --text --quiet > "$REPORT_DIR/semgrep.txt" || true
  else
    warn "semgrep not found; skip semgrep stage"
  fi

  if command -v flawfinder >/dev/null 2>&1; then
    has_any=1
    flawfinder "$TARGET_FILE" > "$REPORT_DIR/flawfinder.txt" || true
  else
    warn "flawfinder not found; skip flawfinder stage"
  fi

  if [[ "$has_any" -eq 0 ]]; then
    warn "No vulnerability scanner found. Install cppcheck/semgrep/flawfinder for richer reports."
  fi

  ok "Vulnerability scan stage done"
}

write_summary() {
  local summary="$REPORT_DIR/summary.txt"
  {
    echo "FlexOS migration + vulnerability detection summary"
    echo "timestamp: $(date -Iseconds)"
    echo "unikraft_dir: $UNIKRAFT_DIR"
    echo "target_file: $TARGET_FILE"
    echo "callfile: $CALLFILE"
    echo "rulefile: $RULEFILE"
    echo ""

    if [[ -f "$GATE_COVERAGE" ]]; then
      echo "[gate coverage]"
      sed -n '1,80p' "$GATE_COVERAGE"
      echo ""
    fi

    for report in cppcheck.txt semgrep.txt flawfinder.txt; do
      if [[ -f "$REPORT_DIR/$report" ]]; then
        echo "[$report]"
        sed -n '1,80p' "$REPORT_DIR/$report"
        echo ""
      fi
    done

    echo "Files:"
    echo "- migration diff: $MIGRATION_DIFF"
    echo "- gate coverage: $GATE_COVERAGE"
    echo "- summary: $summary"
  } > "$summary"

  ok "Summary written: $summary"
}

TARGET_FILE=""
UNIKRAFT_DIR="$DEFAULT_UNIKRAFT_DIR"
REPORT_DIR=""
SKIP_CLONE=0
NO_PROXY_AUTO=0
CLONE_DEPTH=1

while [[ $# -gt 0 ]]; do
  case "$1" in
    --target-file)
      TARGET_FILE="$2"
      shift 2
      ;;
    --unikraft-dir)
      UNIKRAFT_DIR="$2"
      shift 2
      ;;
    --report-dir)
      REPORT_DIR="$2"
      shift 2
      ;;
    --skip-clone)
      SKIP_CLONE=1
      shift
      ;;
    --no-proxy)
      NO_PROXY_AUTO=1
      shift
      ;;
    --clone-depth)
      CLONE_DEPTH="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      err "Unknown option: $1"
      usage
      exit 1
      ;;
  esac
done

if [[ -z "$TARGET_FILE" ]]; then
  err "--target-file is required"
  usage
  exit 1
fi

TARGET_FILE="$(realpath "$TARGET_FILE")"
UNIKRAFT_DIR="$(realpath -m "$UNIKRAFT_DIR")"

require_cmd git
require_cmd cscope
require_cmd spatch
require_cmd python3

clone_unikraft_if_needed
prepare_workspace
run_porthelper_migration
run_vuln_scans
write_summary

ok "Pipeline completed successfully"
log "See reports under: $REPORT_DIR"
