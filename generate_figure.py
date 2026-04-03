#!/usr/bin/env python3
"""
Unified plotting entrypoint for the whole repository.

This script reads plot-config.yaml, runs plotting commands, and stores outputs under:
    figures/<source>/<figure_name>/

Usage examples:
  python3 generate_figure.py --list
  python3 generate_figure.py --all
  python3 generate_figure.py --target search
  python3 generate_figure.py --target figure06 --no-run
"""

from __future__ import annotations

import argparse
import os
import shlex
import shutil
import subprocess
import sys
import importlib
from pathlib import Path
from typing import Any, Dict, Iterable, List


class PlotOrchestrator:
    def __init__(self, config_path: str) -> None:
        self.root_dir = Path(__file__).resolve().parent
        self.config_path = (self.root_dir / config_path).resolve()
        self.config = self._load_config()

    def _load_config(self) -> Dict[str, Any]:
        try:
            yaml = importlib.import_module("yaml")
        except Exception as exc:
            raise RuntimeError(
                "PyYAML is required. Install it with: python3 -m pip install pyyaml"
            ) from exc

        if not self.config_path.exists():
            raise FileNotFoundError(f"Config file not found: {self.config_path}")
        with self.config_path.open("r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        if "targets" not in data or not isinstance(data["targets"], dict):
            raise ValueError("Invalid config: missing top-level 'targets' map")
        return data

    def _ctx(self) -> Dict[str, str]:
        global_cfg = self.config.get("global", {})
        figures_root = global_cfg.get("figures_root", "figures")
        png_dpi = global_cfg.get("png_dpi", 300)
        python_bin = global_cfg.get("python_bin", "python3")
        return {
            "root": str(self.root_dir),
            "figures_root": str((self.root_dir / figures_root).resolve()),
            "png_dpi": str(png_dpi),
            "python_bin": str(python_bin),
        }

    def list_targets(self) -> List[str]:
        return sorted(self.config.get("targets", {}).keys())

    def _render(self, value: str, ctx: Dict[str, str]) -> str:
        return value.format(**ctx)

    def _iter_selected_targets(self, selected: List[str] | None) -> Iterable[tuple[str, Dict[str, Any]]]:
        all_targets = self.config.get("targets", {})
        if selected:
            unknown = [name for name in selected if name not in all_targets]
            if unknown:
                raise ValueError(f"Unknown target(s): {', '.join(unknown)}")
            for name in selected:
                yield name, all_targets[name]
            return
        for name in self.list_targets():
            cfg = all_targets[name]
            if cfg.get("enabled", True):
                yield name, cfg

    def run(self, *, selected_targets: List[str] | None, execute: bool) -> bool:
        ok = True
        for target_name, target_cfg in self._iter_selected_targets(selected_targets):
            print(f"[target] {target_name}")
            if not self._run_target(target_name, target_cfg, execute=execute):
                ok = False
            print()
        return ok

    def _run_target(self, target_name: str, target_cfg: Dict[str, Any], *, execute: bool) -> bool:
        ctx = self._ctx()
        workdir = self.root_dir / target_cfg.get("workdir", ".")
        workdir = workdir.resolve()

        if not workdir.exists():
            print(f"  [error] workdir not found: {workdir}")
            return False

        env = os.environ.copy()
        for key, raw_val in (target_cfg.get("env") or {}).items():
            env[key] = self._render(str(raw_val), ctx)

        commands = target_cfg.get("commands") or []
        command_failed = False
        if execute:
            for raw_cmd in commands:
                cmd = self._render(str(raw_cmd), ctx)
                print(f"  [run] {cmd}")
                ret = subprocess.run(cmd, cwd=workdir, shell=True, env=env)
                if ret.returncode != 0:
                    print(f"  [error] command failed ({ret.returncode})")
                    command_failed = True
                    break
        else:
            for raw_cmd in commands:
                cmd = self._render(str(raw_cmd), ctx)
                print(f"  [skip-run] {cmd}")

        copied = self._collect_outputs(target_name, target_cfg, ctx, workdir)
        print(f"  [done] copied {copied} file(s)")
        return not command_failed

    def _collect_outputs(
        self,
        target_name: str,
        target_cfg: Dict[str, Any],
        ctx: Dict[str, str],
        workdir: Path,
    ) -> int:
        del target_name
        figures_root = Path(ctx["figures_root"])
        copied = 0

        source_group = target_cfg.get("source_group", "misc")
        source_group = self._render(str(source_group), ctx)

        stem_alias = target_cfg.get("stem_alias") or {}
        collect_rules = target_cfg.get("collect") or []

        for rule in collect_rules:
            src_glob = self._render(str(rule.get("src_glob", "")), ctx)
            dst_group = self._render(str(rule.get("dst_group", "")), ctx).strip()

            if not src_glob:
                continue

            matched = sorted(workdir.glob(src_glob))
            for src in matched:
                if not src.is_file():
                    continue
                ext = src.suffix.lower().lstrip(".")
                if ext not in {"svg", "png"}:
                    continue

                stem = src.stem
                display_stem = stem_alias.get(stem, stem)
                if dst_group:
                    dst_dir = figures_root / source_group / dst_group / display_stem
                else:
                    dst_dir = figures_root / source_group / display_stem
                dst_dir.mkdir(parents=True, exist_ok=True)
                dst_file = dst_dir / src.name
                shutil.copy2(src, dst_file)
                copied += 1
                print(f"  [copy] {src} -> {dst_file}")

        return copied


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Unified plotting entrypoint")
    parser.add_argument("--config", default="plot-config.yaml", help="Path to YAML config")
    parser.add_argument("--list", action="store_true", help="List configured targets")
    parser.add_argument("--all", action="store_true", help="Run all enabled targets")
    parser.add_argument(
        "--target",
        action="append",
        help="Run only the given target (repeatable)",
    )
    parser.add_argument("--no-run", action="store_true", help="Do not execute commands, only collect outputs")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    try:
        orchestrator = PlotOrchestrator(args.config)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    if args.list:
        print("Configured targets:")
        for name in orchestrator.list_targets():
            print(f"  - {name}")
        return 0

    selected = args.target
    if not args.all and not selected:
        # Default behavior: run all enabled targets.
        args.all = True

    try:
        success = orchestrator.run(selected_targets=selected if not args.all else None, execute=not args.no_run)
    except Exception as exc:
        print(f"[error] {exc}", file=sys.stderr)
        return 1

    return 0 if success else 2


if __name__ == "__main__":
    sys.exit(main())
