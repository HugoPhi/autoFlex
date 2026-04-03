#!/usr/bin/env bash

# Path appended to each subdirectory to reach the executable
SUFFIX="usr/src/unikraft/apps/nginx/build"
EXECUTABLE="nginx_kvm-x86_64"

# Counters
success=0
empty=0
failed=0
failed_dirs=()

# Loop over immediate subdirectories only
for dir in */ ; do
    # Remove trailing slash
    dir="${dir%/}"

    # Skip if it's not actually a directory (shouldn't happen)
    [ -d "$dir" ] || continue

    # Check if the directory is empty
    if [ -z "$(ls -A "$dir")" ]; then
        ((empty++))
        continue
    fi

    # Build the full path to the executable
    exec_path="$dir/$SUFFIX/$EXECUTABLE"

    # Check if the executable exists and is executable
    if [ -x "$exec_path" ]; then
        ((success++))
    else
        ((failed++))
        failed_dirs+=("$dir")
    fi
done

total=$((success + empty + failed))

echo "========================================================"
echo "Scan results for subdirectories of: $(pwd)"
echo "========================================================"
echo "Total subdirectories             : $total"
echo "Successful (executable found)    : $success"
echo "Empty subdirectories             : $empty"
echo "Failed (non‑empty, no executable): $failed"
echo

if [ $failed -gt 0 ]; then
    echo "List of failed subdirectories:"
    for d in "${failed_dirs[@]}"; do
        echo "  - $d"
    done
fi
