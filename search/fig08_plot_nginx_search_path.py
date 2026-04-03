#!/usr/bin/env python3

import argparse
import csv
import os
import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from fig08_build_poset_python import grayscale_for_hardening, maybe_render_svg
from validate_all_hypothesis import build_cover_edges, load_config_rows


@dataclass
class NginxConfigMeta:
    config_id: str
    layout_key: str
    hardened_components: Set[str]
    hardening_level: int
    req_mean: float


@dataclass
class TraceStep:
    step: int
    centroid: str
    feasible: bool


def parse_layout_key(layout_text: str) -> str:
    parts = dict((k, int(v)) for k, v in re.findall(r"(nginx|newlib|lwip|uksched):C(\d+)", layout_text))
    return f"R{parts['nginx']}N{parts['newlib']}S{parts['lwip']}L{parts['uksched']}"


def parse_hardening(sfi_text: str) -> Set[str]:
    mapping = {
        "nginx": "R",
        "newlib": "N",
        "lwip": "S",
        "uksched": "L",
    }
    hard = set()
    for comp, flag in re.findall(r"(nginx|newlib|lwip|uksched):([YN])", sfi_text):
        if flag == "Y":
            hard.add(mapping[comp])
    return hard


def load_nginx_meta(config_map_csv: str) -> Dict[str, NginxConfigMeta]:
    meta: Dict[str, NginxConfigMeta] = {}
    with open(config_map_csv, "r", encoding="utf-8", newline="") as f:
        r = csv.DictReader(f)
        for row in r:
            cid = row["ConfigID"]
            hard = parse_hardening(row["SFI"])
            meta[cid] = NginxConfigMeta(
                config_id=cid,
                layout_key=parse_layout_key(row["CompartmentLayout"]),
                hardened_components=hard,
                hardening_level=len(hard),
                req_mean=float(row["REQ_mean"]),
            )
    return meta


def select_threshold(rows: List[dict], threshold: Optional[float]) -> float:
    candidates = []
    for row in rows:
        if row.get("dataset", "") != "nginx:REQ":
            continue
        candidates.append(float(row["threshold"]))

    if not candidates:
        raise ValueError("No nginx:REQ rows found in trace CSV")

    if threshold is None:
        return candidates[0]

    for t in candidates:
        if abs(t - threshold) < 1e-9:
            return t
    raise ValueError(f"Requested threshold {threshold} not found for nginx:REQ")


def load_nginx_trace(trace_csv: str, threshold: Optional[float]) -> Tuple[float, List[TraceStep]]:
    with open(trace_csv, "r", encoding="utf-8", newline="") as f:
        all_rows = list(csv.DictReader(f))

    chosen_threshold = select_threshold(all_rows, threshold)

    trace: List[TraceStep] = []
    for row in all_rows:
        if row.get("dataset", "") != "nginx:REQ":
            continue
        if row.get("search_method", "balanced") != "balanced":
            continue
        if abs(float(row["threshold"]) - chosen_threshold) > 1e-9:
            continue
        trace.append(
            TraceStep(
                step=int(row["step"]),
                centroid=row["centroid"],
                feasible=(int(row["feasible"]) == 1),
            )
        )

    trace.sort(key=lambda x: x.step)
    if not trace:
        raise ValueError("Selected nginx trace is empty")

    return chosen_threshold, trace


def load_nginx_summary(summary_csv: str, threshold: float) -> dict:
    with open(summary_csv, "r", encoding="utf-8", newline="") as f:
        for row in csv.DictReader(f):
            if row.get("dataset") != "nginx:REQ":
                continue
            if row.get("search_method", "balanced") != "balanced":
                continue
            if abs(float(row.get("threshold", "nan")) - threshold) < 1e-9:
                return row
    return {}


def build_nodes_and_edges_for_nginx(config_map_csv: str) -> Tuple[List[str], List[Tuple[str, str]]]:
    rows = load_config_rows(config_map_csv, ("REQ",))
    nodes = sorted([r.config_id for r in rows])
    edges = sorted(build_cover_edges(rows))
    return nodes, edges


def write_nginx_path_dot(
    out_dot: str,
    nodes: Sequence[str],
    edges: Sequence[Tuple[str, str]],
    meta: Dict[str, NginxConfigMeta],
    trace: Sequence[TraceStep],
    summary_row: dict,
    threshold: float,
) -> None:
    path_nodes = [s.centroid for s in trace]
    path_node_set = set(path_nodes)
    feasible_nodes = set(s.centroid for s in trace if s.feasible)

    final_answers = set()
    if summary_row.get("final_answers"):
        final_answers = set(x for x in summary_row["final_answers"].split("|") if x)

    path_edge_count: Dict[Tuple[str, str], int] = defaultdict(int)
    for i in range(len(path_nodes) - 1):
        a = path_nodes[i]
        b = path_nodes[i + 1]
        path_edge_count[(a, b)] += 1

    first_feasible_step = "0"
    if summary_row.get("first_feasible_query"):
        first_feasible_step = summary_row["first_feasible_query"]

    with open(out_dot, "w", encoding="utf-8") as f:
        f.write("digraph g {\n")
        f.write("    ratio=0.6;\n")
        f.write('    graph [labeljust=l, labelloc=t, fontsize=20, fontname="Times New Roman"];\n')
        f.write('    label="Nginx Search Path on Config Poset\\n')
        f.write(f'threshold={threshold:.6f}, query_count={len(trace)}, first_feasible_query={first_feasible_step}";\n')
        f.write('    node [style="filled,setlinewidth(2)", shape=circle, color=black, fillcolor=white, fontname="Times New Roman"]\n')
        f.write('    edge [arrowsize=1.2, len=.75, color="#B0B0B0", penwidth=1.0, fontname="Times New Roman"]\n\n')

        for nid in nodes:
            m = meta.get(nid)
            if m is None:
                tooltip = nid
                fill = "#ffffff"
            else:
                tooltip = (
                    f"{nid} | layout={m.layout_key} | hardening={m.hardening_level} | "
                    f"REQ_mean={m.req_mean:.3f}"
                )
                fill = grayscale_for_hardening(m.hardening_level)

            shape = "circle"
            color = "black"
            penwidth = "2"

            if nid in path_node_set:
                color = "#1f77b4"
                penwidth = "3"
            if nid in feasible_nodes:
                color = "#2ca02c"
                fill = "#d8f5d2"
                penwidth = "3"
            if nid in final_answers:
                shape = "doublecircle"
                color = "#d62728"
                penwidth = "3.2"

            # Keep node labels empty like fig08, rely on tooltip for details.
            f.write(
                f'    {nid} [label="", tooltip="{tooltip}", fillcolor="{fill}", '
                f'shape={shape}, color="{color}", penwidth={penwidth}]\n'
            )

        f.write("\n")
        base_edges = set(edges)
        for s, d in sorted(base_edges):
            f.write(f"    {s} -> {d}\n")

        if path_edge_count:
            f.write("\n    // Overlay search-path transitions between queried centroids\n")
            for (s, d), cnt in sorted(path_edge_count.items()):
                label = str(cnt) if cnt > 1 else ""
                f.write(
                    f'    {s} -> {d} [color="#ff7f0e", penwidth=2.8, arrowsize=1.4, '
                    f'constraint=false, label="{label}", fontcolor="#ff7f0e"]\n'
                )

        f.write("}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot nginx search path on fig08-style poset graph")
    p.add_argument("--trace-csv", default="./result/dag_search_trace.csv")
    p.add_argument("--summary-csv", default="./result/dag_search_summary.csv")
    p.add_argument("--nginx-config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--threshold", type=float, default=None, help="Target threshold for nginx:REQ")
    p.add_argument("--out-dot", default="./result/nginx_search_path.dot")
    p.add_argument("--out-svg", default="./result/svg/nginx_search_path.svg")
    p.add_argument("--out-png", default="./result/png/nginx_search_path.png", help="Output PNG path (optional)")
    p.add_argument("--png-dpi", type=int, default=300, help="PNG resolution in DPI")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out_dot)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_svg)), exist_ok=True)
    if args.out_png:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_png)), exist_ok=True)

    threshold, trace = load_nginx_trace(args.trace_csv, args.threshold)
    summary_row = load_nginx_summary(args.summary_csv, threshold)

    nodes, edges = build_nodes_and_edges_for_nginx(args.nginx_config_map)
    meta = load_nginx_meta(args.nginx_config_map)

    missing = [s.centroid for s in trace if s.centroid not in set(nodes)]
    if missing:
        raise ValueError(f"Trace contains centroids not present in nginx config graph: {missing[:5]}")

    write_nginx_path_dot(
        out_dot=args.out_dot,
        nodes=nodes,
        edges=edges,
        meta=meta,
        trace=trace,
        summary_row=summary_row,
        threshold=threshold,
    )

    print(f"Generated DOT: {args.out_dot}")
    print(f"Nodes: {len(nodes)}, Edges: {len(edges)}")
    print(f"Selected threshold: {threshold:.6f}, path_steps={len(trace)}")
    maybe_render_svg(args.out_dot, args.out_svg, args.out_png if args.out_png else None, args.png_dpi)


if __name__ == "__main__":
    main()
