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
