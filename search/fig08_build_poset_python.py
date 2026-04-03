#!/usr/bin/env python3

import argparse
import os
import shutil
import subprocess
from typing import Dict, List, Tuple

from validate_all_hypothesis import build_cover_edges, load_config_rows

COMPONENTS = ("R", "N", "S", "L")


def grayscale_for_hardening(level):
    # Dark for less hardening, lighter for more hardening.
    shades = ["#3a3a3a", "#727272", "#a8a8a8", "#d8d8d8", "#f0f0f0"]
    return shades[max(0, min(level, len(shades) - 1))]


def _build_tooltip(comp: Dict[str, int], sfi: Dict[str, int]) -> str:
    alias = {
        "nginx": "R",
        "newlib": "N",
        "lwip": "S",
        "uksched": "L",
    }
    parts: List[str] = []
    for lib, symbol in alias.items():
        comp_v = comp.get(lib, 0)
        sfi_v = sfi.get(lib, 0)
        suffix = "H" if sfi_v == 1 else ""
        parts.append(f"{symbol}{comp_v}{suffix}")
    return " ".join(parts)


def generate_nodes_and_edges(config_map_path: str, method: str) -> Tuple[Dict[str, dict], List[Tuple[str, str]]]:
    rows = load_config_rows(config_map_path, (method,))
    if not rows:
        raise ValueError(f"No rows loaded from {config_map_path}")

    nodes: Dict[str, dict] = {}
    for row in rows:
        hardening_level = int(sum(row.sfi.values()))
        nodes[row.config_id] = {
            "tooltip": _build_tooltip(row.comp, row.sfi),
            "fillcolor": grayscale_for_hardening(hardening_level),
            "shape": "circle",
            "color": "black",
        }

    edges = build_cover_edges(rows)

    # Prefer C01 as baseline when available to keep historical behavior.
    if "C01" in nodes:
        nodes["C01"]["shape"] = "doublecircle"

    return nodes, sorted(edges)


def write_dot(path, nodes, edges):
    with open(path, "w", encoding="utf-8") as f:
        f.write("digraph g {\n")
        f.write("    ratio=0.6;\n")
        f.write('    graph [fontname="Times New Roman"];\n')
        f.write('    node [style="filled,setlinewidth(2)", shape=circle, color=black, fillcolor=white, fontname="Times New Roman"]\n')
        f.write('    edge [arrowsize=1.4, len=.75, fontname="Times New Roman"]\n\n')

        for nid in sorted(nodes.keys()):
            meta = nodes[nid]
            f.write(
                f'    {nid} [label="", tooltip="{meta["tooltip"]}", '
                f'fillcolor="{meta["fillcolor"]}", shape={meta["shape"]}, color="{meta["color"]}"]\n'
            )

        f.write("\n")
        for s, d in edges:
            f.write(f"    {s} -> {d}\n")

        f.write("}\n")


def maybe_render_svg(dot_path, svg_path, png_path=None, png_dpi=None):
    dot = shutil.which("dot")
    if not dot:
        print("[warn] graphviz 'dot' not found; generated only DOT file.")
        return

    subprocess.run([dot, f"-Tsvg", dot_path, "-o", svg_path], check=True)
    print(f"Generated SVG: {svg_path}")

    if png_path:
        dpi_arg = f"-Gdpi={png_dpi}" if png_dpi else ""
        cmd = [dot, f"-Tpng", dot_path, "-o", png_path]
        if dpi_arg:
            cmd.insert(2, dpi_arg)
        subprocess.run(cmd, check=True)
        print(f"Generated PNG: {png_path}")


def parse_args():
    p = argparse.ArgumentParser(description="Rebuild fig08 poset relations using config-map data")
    p.add_argument("--config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--method", default="REQ", help="Performance method key in config-map (e.g., REQ/GET/SET)")
    p.add_argument("--out-dot", default="./result/fig08_relations.dot")
    p.add_argument("--out-svg", default="./result/svg/fig08_plot.svg")
    p.add_argument("--out-png", default="./result/png/fig08_plot.png", help="Output PNG path (optional)")
    p.add_argument("--png-dpi", type=int, default=300, help="PNG resolution in DPI")
    return p.parse_args()


def main():
    args = parse_args()
    os.makedirs(os.path.dirname(os.path.abspath(args.out_dot)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_svg)), exist_ok=True)
    if args.out_png:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_png)), exist_ok=True)

    nodes, edges = generate_nodes_and_edges(args.config_map, args.method)
    write_dot(args.out_dot, nodes, edges)
    print(f"Generated DOT: {args.out_dot}")
    print(f"Nodes: {len(nodes)}, Edges: {len(edges)}")
    maybe_render_svg(args.out_dot, args.out_svg, args.out_png if args.out_png else None, args.png_dpi)


if __name__ == "__main__":
    main()
