#!/usr/bin/env python3
"""
Unified plotting configuration and output management tool.
Helps coordinate SVG/PNG generation across all experiments.
"""

import argparse
import os
import yaml
from pathlib import Path
from typing import Dict, List, Optional, Tuple


class PlotConfig:
    """Load and manage plot configuration from YAML."""

    def __init__(self, config_path: str = "plot-config.yaml"):
        self.config_path = config_path
        self.config = {}
        self.load()

    def load(self):
        """Load configuration from YAML file."""
        if not os.path.isfile(self.config_path):
            print(f"[warn] Config file not found: {self.config_path}")
            return
        
        try:
            with open(self.config_path, 'r') as f:
                self.config = yaml.safe_load(f) or {}
        except Exception as e:
            print(f"[error] Failed to load config: {e}")
            self.config = {}

    def get_plot_config(self, plot_name: str) -> Optional[Dict]:
        """Get configuration for a specific plot."""
        plots = self.config.get("plots", {})
        return plots.get(plot_name)

    def get_output_dir(self, plot_name: str) -> str:
        """Get base output directory for a plot."""
        plot_cfg = self.get_plot_config(plot_name)
        if plot_cfg:
            return plot_cfg.get("output_dir", "results")
        return "results"

    def get_png_dpi(self, plot_name: str) -> int:
        """Get PNG DPI setting for a plot."""
        plot_cfg = self.get_plot_config(plot_name)
        if plot_cfg:
            return plot_cfg.get("png_dpi", 300)
        return 300

    def get_formats(self, plot_name: str) -> List[str]:
        """Get output formats for a plot."""
        plot_cfg = self.get_plot_config(plot_name)
        if plot_cfg:
            return plot_cfg.get("formats", ["svg", "png"])
        return ["svg", "png"]

    def ensure_output_dirs(self, output_dir: str) -> Tuple[str, str]:
        """Create SVG and PNG subdirectories."""
        svg_dir = os.path.join(output_dir, "svg")
        png_dir = os.path.join(output_dir, "png")
        os.makedirs(svg_dir, exist_ok=True)
        os.makedirs(png_dir, exist_ok=True)
        return svg_dir, png_dir

    def list_plots(self) -> List[str]:
        """List all configured plots."""
        return list(self.config.get("plots", {}).keys())

    def print_config(self, plot_name: Optional[str] = None):
        """Print configuration for debugging."""
        if plot_name:
            cfg = self.get_plot_config(plot_name)
            if cfg:
                print(f"Plot: {plot_name}")
                print(f"  Output Dir: {cfg.get('output_dir')}")
                print(f"  PNG DPI: {cfg.get('png_dpi')}")
                print(f"  Formats: {cfg.get('formats')}")
        else:
            print("Available plots:")
            for pname in self.list_plots():
                print(f"  - {pname}")


def cli_list(args):
    """List all plots in config."""
    config = PlotConfig(args.config)
    for plot_name in config.list_plots():
        config.print_config(plot_name)


def cli_show(args):
    """Show configuration for a specific plot."""
    config = PlotConfig(args.config)
    config.print_config(args.plot)


def cli_init_dirs(args):
    """Initialize output directories for a plot."""
    config = PlotConfig(args.config)
    output_dir = config.get_output_dir(args.plot)
    svg_dir, png_dir = config.ensure_output_dirs(output_dir)
    print(f"Created directories:")
    print(f"  SVG: {svg_dir}")
    print(f"  PNG: {png_dir}")


def main():
    parser = argparse.ArgumentParser(
        description="Unified plotting configuration management tool"
    )
    parser.add_argument(
        "--config",
        default="plot-config.yaml",
        help="Path to plot-config.yaml"
    )
    
    subparsers = parser.add_subparsers(dest="command", help="Commands")
    
    # Subcommand: list
    list_parser = subparsers.add_parser("list", help="List all plots")
    list_parser.set_defaults(func=cli_list)
    
    # Subcommand: show
    show_parser = subparsers.add_parser("show", help="Show plot configuration")
    show_parser.add_argument("plot", help="Plot name")
    show_parser.set_defaults(func=cli_show)
    
    # Subcommand: init-dirs
    init_parser = subparsers.add_parser("init-dirs", help="Initialize output directories")
    init_parser.add_argument("plot", help="Plot name")
    init_parser.set_defaults(func=cli_init_dirs)
    
    args = parser.parse_args()
    
    if hasattr(args, 'func'):
        args.func(args)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
