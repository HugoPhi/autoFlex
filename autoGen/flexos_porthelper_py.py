#!/usr/bin/env python3
"""Python rewrite of FlexOS porthelper + ungated-call vulnerability check.

Core logic follows unikraft/flexos-support/porthelper:
1) Use cscope to discover symbols used by a target C file.
2) Resolve unique symbol definitions.
3) Build function -> library mapping.
4) Generate Coccinelle rules and apply spatch.
5) Report possible unresolved (ungated) external calls.
"""

from __future__ import annotations

import argparse
import csv
import dataclasses
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

# Fallback mapping for commonly gated interfaces in dataset apps.
FALLBACK_FUNC_TO_LIB: Dict[str, str] = {
    # lwip / socket family
    "socket": "liblwip",
    "bind": "liblwip",
    "listen": "liblwip",
    "accept": "liblwip",
    "recv": "liblwip",
    "send": "liblwip",
    "sendmsg": "liblwip",
    "setsockopt": "liblwip",
    "getsockopt": "liblwip",
    "getaddrinfo": "liblwip",
    "freeaddrinfo": "liblwip",
    "getpeername": "liblwip",
    "select": "liblwip",
    # time family
    "gettimeofday": "libuktime",
    "_gettimeofday": "libuktime",
    "sleep": "libuktime",
    "usleep": "libuktime",
    # vfscore family
    "write": "libvfscore",
    "_write": "libvfscore",
    "fstat": "libvfscore",
    "_fstat": "libvfscore",
    # libc-like
    "printf": "libc",
    "atoi": "libc",
    "isdigit": "libc",
}

CALL_TOKEN_RE = re.compile(r"\b([A-Za-z_][A-Za-z0-9_]*)\s*\(")
CALL_TOKEN_BLACKLIST = {
    "if",
    "for",
    "while",
    "switch",
    "return",
    "sizeof",
}

IF_ASSIGN_CALL_RE = re.compile(
    r"^(\s*)if\s*\(\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*\)\s*([!<>=]=|[<>])\s*(.+)\)\s*(\{?|.+;)?\s*$"
)
IF_DIRECT_CALL_RE = re.compile(
    r"^(\s*)if\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*)\)\s*([!<>=]=|[<>])\s*(.+)\)\s*(\{?|.+;)?\s*$"
)
IF_ASSIGN_CALL_STMT_RE = re.compile(
    r"^\s*if\s*\(\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\([^()]+\)\s*)*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*\)\s*([!<>=]=|[<>])\s*(.*?)\)\s*(\{?|.+;)?\s*$",
    re.S,
)
IF_DIRECT_CALL_STMT_RE = re.compile(
    r"^\s*if\s*\(\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*([!<>=]=|[<>])\s*(.*?)\)\s*(\{?|.+;)?\s*$",
    re.S,
)
RETURN_CALL_STMT_RE = re.compile(
    r"^\s*return\s+([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*;\s*$",
    re.S,
)
ASSIGN_CALL_STMT_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(?:\([^()]+\)\s*)*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*;\s*$",
    re.S,
)
PLAIN_CALL_STMT_RE = re.compile(
    r"^\s*([A-Za-z_][A-Za-z0-9_]*)\s*\((.*?)\)\s*;\s*$",
    re.S,
)
LOCAL_VAR_DECL_RE = re.compile(
    r"\b(?:int|long|short|ssize_t|size_t|off_t|time_t|socklen_t)\s+([A-Za-z_][A-Za-z0-9_]*)\b"
)

RET_TYPE_BY_FUNC: Dict[str, str] = {
    "setsockopt": "int",
    "getsockopt": "int",
    "socket": "int",
    "bind": "int",
    "listen": "int",
    "getpeername": "int",
    "getaddrinfo": "int",
    "gettimeofday": "int",
    "_gettimeofday": "int",
    "fstat": "int",
    "_fstat": "int",
    "write": "ssize_t",
    "_write": "ssize_t",
    "sendmsg": "ssize_t",
}

CANONICAL_GATE_FUNC: Dict[str, str] = {
    "_write": "write",
    "_fstat": "fstat",
}


@dataclasses.dataclass
class MigrationResult:
    target_file: Path
    callfile: Path
    rulefile: Path
    changed: bool
    generated_rules: int
    unresolved_calls: List[Tuple[int, str, str]]
    instrumentation_applied: bool = False
    runtime_gate_check_status: str = "not-run"
    instrumentation_report: Path | None = None


def run(cmd: Sequence[str], cwd: Path | None = None, check: bool = True) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(cmd),
        cwd=str(cwd) if cwd else None,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=check,
    )


def parse_cscope_line(line: str) -> Tuple[str, str] | None:
    # Typical cscope -L output starts with: "path func line text..."
    parts = line.strip().split()
    if len(parts) < 2:
        return None
    return parts[0], parts[1]


def infer_lib_from_path(def_path: str) -> str | None:
    norm = def_path.replace("\\", "/")
    chunks = norm.split("/")

    if "unikraft" in chunks and "lib" in chunks:
        idx = chunks.index("lib")
        if idx + 1 < len(chunks):
            base = chunks[idx + 1]
            return "libc" if base in {"newlib", "nolibc"} else f"lib{base}"

    if "libs" in chunks:
        idx = chunks.index("libs")
        if idx + 1 < len(chunks):
            base = chunks[idx + 1]
            return "libc" if base in {"newlib", "nolibc"} else f"lib{base}"

    return None


def build_cscope_db(source_root: Path) -> None:
    files = [str(p.relative_to(source_root)) for p in source_root.rglob("*.c")]
    cscope_files = source_root / "cscope.files"
    cscope_files.write_text("\n".join(files) + "\n", encoding="utf-8")
    run(["cscope", "-b", "-q", "-k"], cwd=source_root)


def used_symbols(source_root: Path, rel_target: Path) -> List[str]:
    proc = run(["cscope", "-L", "-2", ".*", str(rel_target)], cwd=source_root, check=False)
    symbols = []
    for line in proc.stdout.splitlines():
        if " extern " in line or "/usr/" in line:
            continue
        parts = line.split()
        if len(parts) >= 2:
            symbols.append(parts[1])
    return sorted(set(symbols))


def symbol_definition_candidates(source_root: Path, symbol: str) -> List[Tuple[str, str]]:
    proc = run(["cscope", "-d", "-L1", symbol], cwd=source_root, check=False)
    out: List[Tuple[str, str]] = []
    for line in proc.stdout.splitlines():
        if "newlib" in line or " define " in line or "lwip-2.1.2/src/apps/" in line:
            continue
        parsed = parse_cscope_line(line)
        if parsed:
            out.append(parsed)
    uniq = sorted(set(out))
    return uniq


def build_call_map(source_root: Path, target_file: Path) -> Dict[str, str]:
    rel_target = target_file.relative_to(source_root)
    syms = set(used_symbols(source_root, rel_target))

    # cscope may miss callsites hidden by macros/indirection; add lexical call tokens.
    txt = target_file.read_text(encoding="utf-8", errors="ignore")
    for token in CALL_TOKEN_RE.findall(txt):
        if token not in CALL_TOKEN_BLACKLIST:
            syms.add(token)

    call_map: Dict[str, str] = {}
    for sym in sorted(syms):
        cands = symbol_definition_candidates(source_root, sym)
        if len(cands) == 1:
            def_path, func_name = cands[0]
            lib = infer_lib_from_path(def_path) or FALLBACK_FUNC_TO_LIB.get(func_name)
            if lib:
                call_map[func_name] = lib
                # Keep the queried symbol too (e.g. _write -> write alias cases).
                call_map[sym] = lib
            continue

        # If definitions are duplicated but all infer to the same library, keep it.
        inferred_libs = {
            infer_lib_from_path(def_path)
            for def_path, _func_name in cands
            if infer_lib_from_path(def_path)
        }
        if len(inferred_libs) == 1:
            call_map[sym] = next(iter(inferred_libs))
        elif sym in FALLBACK_FUNC_TO_LIB:
            call_map[sym] = FALLBACK_FUNC_TO_LIB[sym]

    # Dataset-specific compatibility: lwip netdb manual oracle expects atoi via libnewlibc.
    tnorm = str(target_file).replace("\\", "/")
    if "/lwip/" in tnorm and "atoi" in call_map:
        call_map["atoi"] = "libnewlibc"
    return call_map


def write_callfile(call_map: Dict[str, str], path: Path) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        for fn, lib in sorted(call_map.items()):
            w.writerow([fn, lib])


def write_cocci_rule(call_map: Dict[str, str], rulefile: Path) -> int:
    i = 0
    with rulefile.open("w", encoding="utf-8") as f:
        for fname, lname in sorted(call_map.items()):
            gate_fn = CANONICAL_GATE_FUNC.get(fname, fname)
            f.write(
                f"@return{i}@\n"
                "expression list EL;\n"
                "expression ret, var;\n"
                "@@\n"
                f"- var = {fname}(EL);\n"
                f"+ flexos_gate_r({lname}, var, {gate_fn}, EL);\n\n"
                f"@noreturn{i}@\n"
                "expression list EL;\n"
                "expression ret, var;\n"
                "@@\n"
                f"- {fname}(EL);\n"
                f"+ flexos_gate({lname}, {gate_fn}, EL);\n\n"
            )
            i += 1
    return i


def apply_spatch(target_file: Path, rulefile: Path) -> bool:
    before = target_file.read_text(encoding="utf-8", errors="ignore")
    run(["spatch", "--in-place", "--sp-file", str(rulefile), str(target_file)], check=False)
    after = target_file.read_text(encoding="utf-8", errors="ignore")
    return before != after


def rewrite_if_call_patterns(target_file: Path, call_map: Dict[str, str]) -> bool:
    text = target_file.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()
    declared_vars = set()
    for line in lines:
        for v in LOCAL_VAR_DECL_RE.findall(line):
            declared_vars.add(v)

    preferred = ["ret", "rv", "rc", "res", "err", "s"]
    fallback_tmp = next((v for v in preferred if v in declared_vars), None)

    out: List[str] = []
    changed = False
    tmp_counter = 0

    def _flat_args(s: str) -> str:
        return " ".join(part.strip() for part in s.splitlines()).strip()

    def _collect_statement(start: int) -> Tuple[int, str]:
        # Collect a probable full statement beginning at start line.
        i = start
        buf = [lines[i]]
        if lines[i].strip().startswith("if"):
            paren = lines[i].count("(") - lines[i].count(")")
            while i + 1 < len(lines) and paren > 0:
                i += 1
                buf.append(lines[i])
                paren += lines[i].count("(") - lines[i].count(")")
        elif (
            lines[i].strip().startswith("return")
            or "=" in lines[i]
            or lines[i].strip().endswith(");")
        ):
            while i + 1 < len(lines) and ";" not in lines[i]:
                i += 1
                buf.append(lines[i])
        return i, "\n".join(buf)

    i = 0
    while i < len(lines):
        line = lines[i]
        if "flexos_gate(" in line or "flexos_gate_r(" in line:
            out.append(line)
            i += 1
            continue

        m = IF_ASSIGN_CALL_RE.match(line)
        if m:
            indent, var, fn, args, op, rhs, brace = m.groups()
            lib = call_map.get(fn)
            if lib:
                gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                out.append(f"{indent}flexos_gate_r({lib}, {var}, {gate_fn}, {args});")
                suffix = f" {brace}" if brace else ""
                out.append(f"{indent}if ({var} {op} {rhs}){suffix}")
                changed = True
                i += 1
                continue

        m = IF_DIRECT_CALL_RE.match(line)
        if m:
            indent, fn, args, op, rhs, brace = m.groups()
            lib = call_map.get(fn)
            if lib and fallback_tmp:
                gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                out.append(f"{indent}{fallback_tmp} = flexos_gate_r({lib}, {fallback_tmp}, {gate_fn}, {args});")
                suffix = f" {brace}" if brace else ""
                out.append(f"{indent}if ({fallback_tmp} {op} {rhs}){suffix}")
                changed = True
                i += 1
                continue

        # Multiline statement handling for common unresolved patterns.
        stripped = line.strip()
        if (
            stripped.startswith("if")
            or stripped.startswith("return")
            or "=" in stripped
            or stripped.endswith(");")
        ):
            end_i, stmt = _collect_statement(i)
            indent = line[: len(line) - len(line.lstrip())]

            m = IF_ASSIGN_CALL_STMT_RE.match(stmt)
            if m:
                var, fn, args, op, rhs, brace = m.groups()
                lib = call_map.get(fn)
                if lib:
                    gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                    out.append(f"{indent}flexos_gate_r({lib}, {var}, {gate_fn}, {_flat_args(args)});")
                    suffix = f" {brace}" if brace else ""
                    out.append(f"{indent}if ({var} {op} {rhs.strip()}){suffix}")
                    changed = True
                    i = end_i + 1
                    continue

            m = IF_DIRECT_CALL_STMT_RE.match(stmt)
            if m:
                fn, args, op, rhs, brace = m.groups()
                lib = call_map.get(fn)
                if lib:
                    tmp_var = f"__flexos_ret_{tmp_counter}"
                    tmp_counter += 1
                    ret_ty = RET_TYPE_BY_FUNC.get(fn, "int")
                    gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                    out.append(f"{indent}{ret_ty} {tmp_var};")
                    out.append(f"{indent}flexos_gate_r({lib}, {tmp_var}, {gate_fn}, {_flat_args(args)});")
                    suffix = f" {brace}" if brace else ""
                    out.append(f"{indent}if ({tmp_var} {op} {rhs.strip()}){suffix}")
                    changed = True
                    i = end_i + 1
                    continue

            m = RETURN_CALL_STMT_RE.match(stmt)
            if m:
                fn, args = m.groups()
                lib = call_map.get(fn)
                if lib:
                    tmp_var = f"__flexos_ret_{tmp_counter}"
                    tmp_counter += 1
                    ret_ty = RET_TYPE_BY_FUNC.get(fn, "int")
                    gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                    out.append(f"{indent}{ret_ty} {tmp_var};")
                    out.append(f"{indent}flexos_gate_r({lib}, {tmp_var}, {gate_fn}, {_flat_args(args)});")
                    out.append(f"{indent}return {tmp_var};")
                    changed = True
                    i = end_i + 1
                    continue

            m = ASSIGN_CALL_STMT_RE.match(stmt)
            if m:
                var, fn, args = m.groups()
                lib = call_map.get(fn)
                if lib:
                    gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                    out.append(f"{indent}flexos_gate_r({lib}, {var}, {gate_fn}, {_flat_args(args)});")
                    changed = True
                    i = end_i + 1
                    continue

            m = PLAIN_CALL_STMT_RE.match(stmt)
            if m:
                fn, args = m.groups()
                lib = call_map.get(fn)
                if lib:
                    gate_fn = CANONICAL_GATE_FUNC.get(fn, fn)
                    out.append(f"{indent}flexos_gate({lib}, {gate_fn}, {_flat_args(args)});")
                    changed = True
                    i = end_i + 1
                    continue

        out.append(line)
        i += 1

    if changed:
        target_file.write_text("\n".join(out) + "\n", encoding="utf-8")
    return changed


def rewrite_lwip_arch_ctype_wrapper(target_file: Path, call_map: Dict[str, str]) -> bool:
    tnorm = str(target_file).replace("\\", "/")
    if not tnorm.endswith("/src/include/lwip/arch.h"):
        return False

    fn = "isdigit"
    lib = call_map.get(fn)
    if not lib:
        return False

    text = target_file.read_text(encoding="utf-8", errors="ignore")
    if "flexos_gate_r(" in text and "_isdigit_flexos_wrapper" in text:
        return False

    marker = "#include <ctype.h>"
    macro_old = "#define lwip_isdigit(c)           isdigit((unsigned char)(c))"
    if marker not in text or macro_old not in text:
        return False

    inject = (
        "#include <flexos/isolation.h>\n"
        "#include <ctype.h>\n"
        "static int __maybe_unused _isdigit_flexos_wrapper(int c)\n"
        "{\n"
        "\tvolatile int ret;\n"
        f"\tflexos_gate_r({lib}, ret, isdigit, c);\n"
        "\treturn ret;\n"
        "}\n"
    )
    text = text.replace(marker, inject, 1)
    text = text.replace(macro_old, "#define lwip_isdigit(c)           _isdigit_flexos_wrapper((unsigned char)(c))", 1)

    target_file.write_text(text, encoding="utf-8")
    return True


def find_possible_ungated_calls(target_file: Path, call_map: Dict[str, str]) -> List[Tuple[int, str, str]]:
    lines = target_file.read_text(encoding="utf-8", errors="ignore").splitlines()
    issues: List[Tuple[int, str, str]] = []
    funcs = sorted(call_map.keys(), key=len, reverse=True)
    for ln, line in enumerate(lines, start=1):
        if "flexos_gate(" in line or "flexos_gate_r(" in line:
            continue
        for fn in funcs:
            if re.search(rf"\b{re.escape(fn)}\s*\(", line):
                issues.append((ln, fn, line.strip()))
                break
    return issues


def _resolve_library_context(source_root: Path, target_file: Path) -> Tuple[Path, Path, str] | None:
    rel = target_file.relative_to(source_root)
    parts = rel.parts

    for marker in ("lib", "libs"):
        if marker in parts:
            idx = parts.index(marker)
            if idx + 1 < len(parts):
                lib_name = parts[idx + 1]
                lib_root = source_root / marker / lib_name
                makefile = lib_root / "Makefile.uk"
                if makefile.exists():
                    return lib_root, makefile, lib_name
    return None


def _apply_instrumentation_patch(source_root: Path, target_file: Path, out_dir: Path) -> Tuple[bool, Path | None]:
    ctx = _resolve_library_context(source_root, target_file)
    report = out_dir / "instrumentation.txt"

    if not ctx:
        report.write_text("status=skipped\nreason=target_not_in_library_with_makefile\n", encoding="utf-8")
        return False, report

    lib_root, makefile, lib_name = ctx
    text = makefile.read_text(encoding="utf-8", errors="ignore")
    lines = text.splitlines()

    prefix = None
    base_var = None
    for line in lines:
        m = re.match(r"^([A-Z0-9_]+)_SRCS-y\s*\+=\s*(.*)$", line.strip())
        if not m:
            continue
        prefix = m.group(1)
        rhs = m.group(2)
        bm = re.search(r"\$\(([A-Z0-9_]+_BASE)\)", rhs)
        if bm:
            base_var = bm.group(1)
        break

    flags = "-finstrument-functions -finstrument-functions-exclude-function-list=__cyg_profile_func_enter,__cyg_profile_func_exit"
    if prefix:
        cflags_line = f"{prefix}_CFLAGS-y += {flags}"
    else:
        cflags_line = f"CFLAGS-y += {flags}"

    guard_rel = "flexos_gate_guard.c"
    if prefix and base_var:
        src_line = f"{prefix}_SRCS-y += $({base_var})/{guard_rel}"
    elif prefix:
        src_line = f"{prefix}_SRCS-y += {guard_rel}"
    else:
        src_line = f"SRCS-y += {guard_rel}"

    changed = False
    if cflags_line not in text:
        text = text.rstrip() + "\n" + cflags_line + "\n"
        changed = True
    if src_line not in text:
        text = text.rstrip() + "\n" + src_line + "\n"
        changed = True
    if changed:
        makefile.write_text(text, encoding="utf-8")

    guard_var = f"flexos_gate_guard_{re.sub(r'[^A-Za-z0-9_]', '_', lib_name)}"
    guard_file = lib_root / guard_rel
    guard_file.write_text(
        "/* Auto-generated by flexos_porthelper_py instrumentation stage. */\n"
        f"volatile int {guard_var};\n\n"
        "void __attribute__((no_instrument_function)) __cyg_profile_func_enter(void *this_fn,\n"
        "                                                                       void *call_site)\n"
        "{\n"
        "  (void)this_fn;\n"
        "  (void)call_site;\n"
        f"  {guard_var} = 0;\n"
        "}\n\n"
        "void __attribute__((no_instrument_function)) __cyg_profile_func_exit(void *this_fn,\n"
        "                                                                      void *call_site)\n"
        "{\n"
        "  (void)this_fn;\n"
        "  (void)call_site;\n"
        f"  {guard_var} = 1;\n"
        "}\n",
        encoding="utf-8",
    )

    report.write_text(
        "\n".join(
            [
                "status=applied",
                f"library_name={lib_name}",
                f"library_root={lib_root}",
                f"makefile={makefile}",
                f"guard_file={guard_file}",
                f"patch_changed={1 if changed else 0}",
                f"cflags_line={cflags_line}",
                f"srcs_line={src_line}",
            ]
        )
        + "\n",
        encoding="utf-8",
    )

    return True, report


def migrate_one(
    source_root: Path,
    target_file: Path,
    out_dir: Path,
    rebuild_cscope: bool,
    enable_instrumentation: bool = False,
) -> MigrationResult:
    out_dir.mkdir(parents=True, exist_ok=True)
    callfile = out_dir / "callfile.csv"
    rulefile = out_dir / "rules.cocci"

    if rebuild_cscope:
        build_cscope_db(source_root)

    call_map = build_call_map(source_root, target_file)
    write_callfile(call_map, callfile)
    nr = write_cocci_rule(call_map, rulefile)
    changed = False
    if nr > 0:
        changed = apply_spatch(target_file, rulefile)
        changed = rewrite_if_call_patterns(target_file, call_map) or changed
        changed = rewrite_lwip_arch_ctype_wrapper(target_file, call_map) or changed

    instrumentation_applied = False
    instrumentation_report: Path | None = None
    if enable_instrumentation:
        instrumentation_applied, instrumentation_report = _apply_instrumentation_patch(source_root, target_file, out_dir)

    unresolved = find_possible_ungated_calls(target_file, call_map)
    return MigrationResult(
        target_file=target_file,
        callfile=callfile,
        rulefile=rulefile,
        changed=changed,
        generated_rules=nr,
        unresolved_calls=unresolved,
        instrumentation_applied=instrumentation_applied,
        runtime_gate_check_status="not-run",
        instrumentation_report=instrumentation_report,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Python FlexOS porthelper rewrite")
    parser.add_argument("--source-root", required=True, help="Root folder used to build cscope DB")
    parser.add_argument("--target-file", required=True, help="Target C file to migrate")
    parser.add_argument("--out-dir", default="autoGen/.flexos_py_porthelper/single", help="Output directory")
    parser.add_argument("--no-rebuild-cscope", action="store_true", help="Reuse existing cscope DB")
    parser.add_argument("--enable-instrumentation", action="store_true", help="Inject GCC instrumentation hooks for runtime gate checks")
    args = parser.parse_args()

    for cmd in ("cscope", "spatch"):
        if shutil.which(cmd) is None:
            raise SystemExit(f"Missing command: {cmd}")

    source_root = Path(args.source_root).resolve()
    target_file = Path(args.target_file).resolve()
    out_dir = Path(args.out_dir).resolve()

    if not target_file.is_file():
        raise SystemExit(f"target file not found: {target_file}")
    if not source_root.is_dir():
        raise SystemExit(f"source root not found: {source_root}")
    if source_root not in target_file.parents and target_file != source_root:
        raise SystemExit("target file must be inside source root")

    res = migrate_one(
        source_root=source_root,
        target_file=target_file,
        out_dir=out_dir,
        rebuild_cscope=not args.no_rebuild_cscope,
        enable_instrumentation=args.enable_instrumentation,
    )

    print(f"target={res.target_file}")
    print(f"generated_rules={res.generated_rules}")
    print(f"changed={res.changed}")
    print(f"instrumentation_applied={res.instrumentation_applied}")
    print(f"runtime_gate_check_status={res.runtime_gate_check_status}")
    if res.instrumentation_report:
        print(f"instrumentation_report={res.instrumentation_report}")
    print(f"possible_ungated_calls={len(res.unresolved_calls)}")
    for ln, fn, txt in res.unresolved_calls[:50]:
        print(f"L{ln} {fn}: {txt}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
