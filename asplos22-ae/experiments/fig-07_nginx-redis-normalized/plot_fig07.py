#!/usr/bin/env python3

import argparse
import subprocess
import sys
from pathlib import Path


def run_cmd(cmd: list[str], cwd: Path) -> None:
    print("[run]", " ".join(cmd))
    ret = subprocess.run(cmd, cwd=str(cwd))
    if ret.returncode != 0:
        raise RuntimeError(f"Command failed with code {ret.returncode}: {' '.join(cmd)}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate fig07 normalized scatter plot without Makefile")
    parser.add_argument("--python", default=sys.executable, help="Python interpreter")
    parser.add_argument("--output-root", required=True, help="Output root directory")
    parser.add_argument(
        "--formats",
        nargs="+",
        default=["svg", "png"],
        help="Output formats to generate (default: svg png)",
    )
    args = parser.parse_args()
    out_root = Path(args.output_root).resolve()

    root = Path(__file__).resolve().parent
    fig6 = (root / "../fig-06_nginx-redis-perm").resolve()

    script = root / "plot_scatter.py"
    redis_perm = fig6 / "apps/redis/permutations-3.csv"
    nginx_perm = fig6 / "apps/nginx/permutations-3.csv"
    redis_csv = fig6 / "paperresults/redis.csv"
    nginx_csv = fig6 / "paperresults/nginx.csv"

    for fmt in args.formats:
        fmt = fmt.lower().strip(".")
        if fmt not in {"svg", "png"}:
            raise ValueError(f"Unsupported format: {fmt}")

        out = out_root / "fig-07_nginx-redis-normalized" / f"fig-07_nginx-redis-normalized.{fmt}"
        out.parent.mkdir(parents=True, exist_ok=True)
        run_cmd(
            [
                args.python,
                str(script),
                str(redis_perm),
                str(nginx_perm),
                str(redis_csv),
                str(nginx_csv),
                str(out),
            ],
            root,
        )

    print("Done generating fig07 plot")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
