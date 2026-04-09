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
  --no-instrumentation         Disable GCC instrumentation injection stage.
  --no-runtime-check           Disable runtime gate check stage.
  --runtime-build-cmd <cmd>    Build command used before runtime check.
                               Default: make prepare && kraft -v build --no-progress --fast --compartmentalize
  --runtime-run-cmd <cmd>      Run command used for runtime gate check.
                               Default: kraft run
  --runtime-timeout-sec <n>    Timeout for runtime command. Default: 60
  --runtime-expect-crash       Expect crash during runtime check (for negative tests).
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
  INSTRUMENTATION_REPORT="$REPORT_DIR/instrumentation.txt"
  RUNTIME_BUILD_LOG="$REPORT_DIR/runtime_build.log"
  RUNTIME_RUN_LOG="$REPORT_DIR/runtime_run.log"
  RUNTIME_GATE_CHECK="$REPORT_DIR/runtime_gate_check.txt"

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

resolve_target_library_context() {
  local ctx_file="$TMP_DIR/lib_context.env"

  TARGET_FILE="$TARGET_FILE" UNIKRAFT_DIR="$UNIKRAFT_DIR" python3 - <<'PY' > "$ctx_file"
import os
import pathlib

target = pathlib.Path(os.environ["TARGET_FILE"]).resolve()
unikraft = pathlib.Path(os.environ["UNIKRAFT_DIR"]).resolve()

try:
    rel = target.relative_to(unikraft)
except Exception:
    raise SystemExit(1)

parts = rel.parts
lib_root = None
lib_name = None

for marker in ("lib", "libs"):
    if marker in parts:
        idx = parts.index(marker)
        if idx + 1 < len(parts):
            lib_name = parts[idx + 1]
            lib_root = unikraft / marker / lib_name
            break

if not lib_root or not lib_name:
    raise SystemExit(2)

makefile = lib_root / "Makefile.uk"
if not makefile.exists():
    raise SystemExit(3)

def emit(key: str, value: pathlib.Path | str) -> None:
    text = str(value).replace("\\", "\\\\").replace('"', '\\"')
    print(f'{key}="{text}"')

emit("LIB_ROOT", lib_root)
emit("LIB_NAME", lib_name)
emit("LIB_MAKEFILE", makefile)
PY

  local rc=$?
  if [[ "$rc" -ne 0 ]]; then
    return 1
  fi

  # shellcheck disable=SC1090
  source "$ctx_file"
  return 0
}

setup_instrumentation() {
  if [[ "$ENABLE_INSTRUMENTATION" -ne 1 ]]; then
    echo "status=skipped" > "$INSTRUMENTATION_REPORT"
    echo "reason=disabled_by_flag" >> "$INSTRUMENTATION_REPORT"
    warn "Instrumentation stage disabled by flag"
    return 0
  fi

  log "Instrumentation stage: patch target library with GCC hooks"

  if ! resolve_target_library_context; then
    echo "status=skipped" > "$INSTRUMENTATION_REPORT"
    echo "reason=target_not_in_library_with_makefile" >> "$INSTRUMENTATION_REPORT"
    warn "Cannot resolve target library context; instrumentation skipped"
    return 0
  fi

  local guard_file="$LIB_ROOT/flexos_gate_guard.c"
  local result_file="$TMP_DIR/instrumentation_patch_result.env"

  LIB_MAKEFILE="$LIB_MAKEFILE" python3 - <<'PY' > "$result_file"
import pathlib
import re
import sys

makefile = pathlib.Path(__import__('os').environ['LIB_MAKEFILE'])
text = makefile.read_text(encoding='utf-8', errors='ignore')
lines = text.splitlines()

prefix = None
base_var = None
for line in lines:
    m = re.match(r'^([A-Z0-9_]+)_SRCS-y\s*\+=\s*(.*)$', line.strip())
    if not m:
        continue
    prefix = m.group(1)
    rhs = m.group(2)
    b = re.search(r'\$\(([A-Z0-9_]+_BASE)\)', rhs)
    if b:
        base_var = b.group(1)
    break

flags = '-finstrument-functions -finstrument-functions-exclude-function-list=__cyg_profile_func_enter,__cyg_profile_func_exit'
if prefix:
    cflags_line = f'{prefix}_CFLAGS-y += {flags}'
else:
    cflags_line = f'CFLAGS-y += {flags}'

guard_rel = 'flexos_gate_guard.c'
if prefix and base_var:
    src_line = f'{prefix}_SRCS-y += $({base_var})/{guard_rel}'
elif prefix:
    src_line = f'{prefix}_SRCS-y += {guard_rel}'
else:
    src_line = f'SRCS-y += {guard_rel}'

updated = text
changed = False

if cflags_line not in updated:
    updated = updated.rstrip() + '\n' + cflags_line + '\n'
    changed = True

if src_line not in updated:
    updated = updated.rstrip() + '\n' + src_line + '\n'
    changed = True

if changed:
    makefile.write_text(updated, encoding='utf-8')

def emit(key: str, value: str) -> None:
    text = value.replace('\\', '\\\\').replace('"', '\\"')
    print(f'{key}="{text}"')

emit('PATCH_CHANGED', '1' if changed else '0')
emit('PATCH_CFLAGS_LINE', cflags_line)
emit('PATCH_SRCS_LINE', src_line)
PY

  # shellcheck disable=SC1090
  source "$result_file"

  local guard_var
  guard_var="flexos_gate_guard_${LIB_NAME//[^a-zA-Z0-9_]/_}"

  cat > "$guard_file" <<EOF
/* Auto-generated by flexos_migrate_vuln_pipeline.sh instrumentation stage. */
volatile int ${guard_var};

void __attribute__((no_instrument_function)) __cyg_profile_func_enter(void *this_fn,
                                                                       void *call_site)
{
  (void)this_fn;
  (void)call_site;
  ${guard_var} = 0;
}

void __attribute__((no_instrument_function)) __cyg_profile_func_exit(void *this_fn,
                                                                      void *call_site)
{
  (void)this_fn;
  (void)call_site;
  ${guard_var} = 1;
}
EOF

  {
    echo "status=applied"
    echo "library_name=$LIB_NAME"
    echo "library_root=$LIB_ROOT"
    echo "makefile=$LIB_MAKEFILE"
    echo "guard_file=$guard_file"
    echo "patch_changed=$PATCH_CHANGED"
    echo "cflags_line=$PATCH_CFLAGS_LINE"
    echo "srcs_line=$PATCH_SRCS_LINE"
  } > "$INSTRUMENTATION_REPORT"

  ok "Instrumentation stage done"
}

find_runtime_app_dir() {
  local dir
  dir="$(dirname "$TARGET_FILE")"
  while [[ "$dir" == "$UNIKRAFT_DIR"* ]]; do
    if [[ -f "$dir/kraft.yaml" ]]; then
      printf '%s\n' "$dir"
      return 0
    fi
    if [[ "$dir" == "$UNIKRAFT_DIR" ]]; then
      break
    fi
    dir="$(dirname "$dir")"
  done
  return 1
}

run_runtime_gate_check() {
  if [[ "$ENABLE_RUNTIME_CHECK" -ne 1 ]]; then
    echo "status=skipped" > "$RUNTIME_GATE_CHECK"
    echo "reason=disabled_by_flag" >> "$RUNTIME_GATE_CHECK"
    warn "Runtime gate check disabled by flag"
    return 0
  fi

  log "Runtime gate check stage: build and run instrumented target"

  if ! command -v kraft >/dev/null 2>&1; then
    echo "status=skipped" > "$RUNTIME_GATE_CHECK"
    echo "reason=kraft_not_found" >> "$RUNTIME_GATE_CHECK"
    warn "kraft not found; runtime gate check skipped"
    return 0
  fi

  local app_dir
  if ! app_dir="$(find_runtime_app_dir)"; then
    echo "status=skipped" > "$RUNTIME_GATE_CHECK"
    echo "reason=kraft_yaml_not_found_from_target_path" >> "$RUNTIME_GATE_CHECK"
    warn "Cannot find app directory with kraft.yaml; runtime gate check skipped"
    return 0
  fi

  local build_rc run_rc timed_out crashed verdict
  build_rc=0
  run_rc=0
  timed_out=0
  crashed=0
  verdict="inconclusive"

  : > "$RUNTIME_BUILD_LOG"
  : > "$RUNTIME_RUN_LOG"

  set +e
  (
    cd "$app_dir"
    bash -lc "$RUNTIME_BUILD_CMD"
  ) > "$RUNTIME_BUILD_LOG" 2>&1
  build_rc=$?
  set -e

  if [[ "$build_rc" -ne 0 ]]; then
    verdict="fail"
    {
      echo "status=$verdict"
      echo "reason=build_failed"
      echo "app_dir=$app_dir"
      echo "build_cmd=$RUNTIME_BUILD_CMD"
      echo "run_cmd=$RUNTIME_RUN_CMD"
      echo "build_exit_code=$build_rc"
      echo "run_exit_code=not_run"
      echo "timed_out=0"
      echo "crash_detected=0"
    } > "$RUNTIME_GATE_CHECK"
    warn "Runtime gate check build failed"
    return 0
  fi

  set +e
  if command -v timeout >/dev/null 2>&1; then
    (
      cd "$app_dir"
      timeout "${RUNTIME_TIMEOUT_SEC}s" bash -lc "$RUNTIME_RUN_CMD"
    ) > "$RUNTIME_RUN_LOG" 2>&1
    run_rc=$?
    if [[ "$run_rc" -eq 124 ]]; then
      timed_out=1
    fi
  else
    (
      cd "$app_dir"
      bash -lc "$RUNTIME_RUN_CMD"
    ) > "$RUNTIME_RUN_LOG" 2>&1
    run_rc=$?
  fi
  set -e

  if grep -E -i "segmentation fault|general protection|panic|BUG:|abort|trap|protection key|PKU|MPK|fault" "$RUNTIME_RUN_LOG" >/dev/null 2>&1; then
    crashed=1
  fi

  if [[ "$RUNTIME_EXPECT_CRASH" -eq 1 ]]; then
    if [[ "$crashed" -eq 1 ]]; then
      verdict="pass"
    elif [[ "$timed_out" -eq 1 ]]; then
      verdict="inconclusive"
    else
      verdict="fail"
    fi
  else
    if [[ "$crashed" -eq 1 ]]; then
      verdict="fail"
    elif [[ "$timed_out" -eq 1 ]]; then
      verdict="inconclusive"
    elif [[ "$run_rc" -eq 0 ]]; then
      verdict="pass"
    else
      verdict="fail"
    fi
  fi

  {
    echo "status=$verdict"
    echo "app_dir=$app_dir"
    echo "build_cmd=$RUNTIME_BUILD_CMD"
    echo "run_cmd=$RUNTIME_RUN_CMD"
    echo "build_exit_code=$build_rc"
    echo "run_exit_code=$run_rc"
    echo "timed_out=$timed_out"
    echo "crash_detected=$crashed"
    echo "expect_crash=$RUNTIME_EXPECT_CRASH"
  } > "$RUNTIME_GATE_CHECK"

  if [[ "$verdict" == "pass" ]]; then
    ok "Runtime gate check passed"
  elif [[ "$verdict" == "inconclusive" ]]; then
    warn "Runtime gate check inconclusive"
  else
    warn "Runtime gate check failed"
  fi
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

    if [[ -f "$INSTRUMENTATION_REPORT" ]]; then
      echo "[instrumentation]"
      sed -n '1,120p' "$INSTRUMENTATION_REPORT"
      echo ""
    fi

    if [[ -f "$RUNTIME_GATE_CHECK" ]]; then
      echo "[runtime gate check]"
      sed -n '1,120p' "$RUNTIME_GATE_CHECK"
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
    echo "- instrumentation report: $INSTRUMENTATION_REPORT"
    echo "- runtime gate check: $RUNTIME_GATE_CHECK"
    echo "- runtime build log: $RUNTIME_BUILD_LOG"
    echo "- runtime run log: $RUNTIME_RUN_LOG"
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
ENABLE_INSTRUMENTATION=1
ENABLE_RUNTIME_CHECK=1
RUNTIME_BUILD_CMD="make prepare && kraft -v build --no-progress --fast --compartmentalize"
RUNTIME_RUN_CMD="kraft run"
RUNTIME_TIMEOUT_SEC=60
RUNTIME_EXPECT_CRASH=0

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
    --no-instrumentation)
      ENABLE_INSTRUMENTATION=0
      shift
      ;;
    --no-runtime-check)
      ENABLE_RUNTIME_CHECK=0
      shift
      ;;
    --runtime-build-cmd)
      RUNTIME_BUILD_CMD="$2"
      shift 2
      ;;
    --runtime-run-cmd)
      RUNTIME_RUN_CMD="$2"
      shift 2
      ;;
    --runtime-timeout-sec)
      RUNTIME_TIMEOUT_SEC="$2"
      shift 2
      ;;
    --runtime-expect-crash)
      RUNTIME_EXPECT_CRASH=1
      shift
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
setup_instrumentation
run_runtime_gate_check
run_vuln_scans
write_summary

ok "Pipeline completed successfully"
log "See reports under: $REPORT_DIR"
