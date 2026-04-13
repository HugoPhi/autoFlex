#!/usr/bin/env python3

import argparse
import hashlib
import math
import os
import re
from collections import defaultdict, deque
from dataclasses import dataclass
from typing import Dict, List, Optional, Sequence, Set, Tuple

from dag_poset_search import DagPosetSearch
from fig08_build_poset_python import grayscale_for_hardening, maybe_render_svg
from validate_all_hypothesis import build_cover_edges, load_config_rows


@dataclass
class NodeMeta:
    hardening_level: int
    tooltip: str


def _build_node_meta(config_map_csv: str, method: str) -> Tuple[List[str], List[Tuple[str, str]], Dict[str, NodeMeta]]:
    rows = load_config_rows(config_map_csv, (method,))
    if not rows:
        raise ValueError(f"No rows loaded from {config_map_csv} using method={method}")

    nodes = sorted(r.config_id for r in rows)
    edges = sorted(build_cover_edges(rows))

    meta: Dict[str, NodeMeta] = {}
    for r in rows:
        hardening = int(sum(r.sfi.values()))
        layout = f"R{r.comp.get('nginx', 0)} N{r.comp.get('newlib', 0)} S{r.comp.get('lwip', 0)} L{r.comp.get('uksched', 0)}"
        meta[r.config_id] = NodeMeta(
            hardening_level=hardening,
            tooltip=f"{r.config_id} | {layout} | hardening={hardening}",
        )

    return nodes, edges, meta


def _pick_query_node(
    nodes: Sequence[str],
    anc_bits: Sequence[int],
    desc_bits: Sequence[int],
    explicit_query: Optional[str],
) -> str:
    if explicit_query:
        if explicit_query not in set(nodes):
            raise ValueError(f"query node not found: {explicit_query}")
        return explicit_query

    full_mask = (1 << len(nodes)) - 1
    best = None
    for i, nid in enumerate(nodes):
        a = (anc_bits[i] & full_mask).bit_count()
        d = (desc_bits[i] & full_mask).bit_count()
        score = min(a, d)
        balance = abs(a - d)
        key = (score, -balance, nid)
        if best is None or key > best[0]:
            best = (key, nid)

    if best is None:
        raise RuntimeError("Failed to select query node")
    return best[1]


def _induced_edges(nodes_subset: Set[str], edges: Sequence[Tuple[str, str]]) -> List[Tuple[str, str]]:
    return [(s, d) for (s, d) in edges if s in nodes_subset and d in nodes_subset]


def _escape_dot(s: str) -> str:
    return s.replace('"', '\\"')


def _stable_key(edge: Tuple[str, str]) -> int:
    h = hashlib.md5(f"{edge[0]}->{edge[1]}".encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _stable_node_key(node_id: str) -> int:
    h = hashlib.md5(node_id.encode("utf-8")).hexdigest()
    return int(h[:8], 16)


def _arrange_nodes_symmetric(
    nodes: Sequence[str],
    score_map: Dict[str, int],
    center_node: Optional[str] = None,
) -> List[str]:
    ranked = sorted(nodes, key=lambda n: (-score_map.get(n, 0), _stable_node_key(n)))
    center = None
    if center_node is not None and center_node in ranked:
        center = center_node
        ranked = [n for n in ranked if n != center_node]

    left: List[str] = []
    right: List[str] = []
    for i, n in enumerate(ranked):
        if i % 2 == 0:
            left.insert(0, n)
        else:
            right.append(n)

    if center is not None:
        return left + [center] + right
    return left + right


def _bfs_dist(start: str, graph: Dict[str, Set[str]]) -> Dict[str, int]:
    dist: Dict[str, int] = {start: 0}
    q = deque([start])
    while q:
        u = q.popleft()
        for v in graph.get(u, set()):
            if v in dist:
                continue
            dist[v] = dist[u] + 1
            q.append(v)
    return dist


def _build_sparse_edges(
    subset_nodes: Set[str],
    subset_edges: Sequence[Tuple[str, str]],
    query_node: str,
) -> List[Tuple[str, str]]:
    succ: Dict[str, Set[str]] = defaultdict(set)
    pred: Dict[str, Set[str]] = defaultdict(set)
    for s, d in subset_edges:
        succ[s].add(d)
        pred[d].add(s)

    dist_from_query = _bfs_dist(query_node, succ)
    dist_to_query = _bfs_dist(query_node, pred)

    backbone_candidates: List[Tuple[str, str]] = []
    for s, d in subset_edges:
        # Ancestor side: move one step toward query.
        if s in dist_to_query and d in dist_to_query and dist_to_query[s] > 0 and dist_to_query[d] == dist_to_query[s] - 1:
            backbone_candidates.append((s, d))
            continue
        # Descendant side: move one step away from query.
        if s in dist_from_query and d in dist_from_query and dist_from_query[d] == dist_from_query[s] + 1:
            backbone_candidates.append((s, d))
            continue

    keep: Set[Tuple[str, str]] = set()
    out_deg: Dict[str, int] = defaultdict(int)
    in_deg: Dict[str, int] = defaultdict(int)

    # Keep a sparse layered skeleton.
    for e in sorted(backbone_candidates, key=_stable_key):
        s, d = e
        if out_deg[s] >= 2 or in_deg[d] >= 2:
            continue
        keep.add(e)
        out_deg[s] += 1
        in_deg[d] += 1

    # Add a few extra irregular edges (still restrained).
    for e in sorted(subset_edges, key=_stable_key):
        if e in keep:
            continue
        s, d = e
        if out_deg[s] >= 3 or in_deg[d] >= 3:
            continue
        if (_stable_key(e) % 100) < 16:
            keep.add(e)
            out_deg[s] += 1
            in_deg[d] += 1

    return sorted(keep)


def _build_levels(query_node: str, sparse_edges: Sequence[Tuple[str, str]]) -> Dict[str, int]:
    succ: Dict[str, Set[str]] = defaultdict(set)
    pred: Dict[str, Set[str]] = defaultdict(set)
    for s, d in sparse_edges:
        succ[s].add(d)
        pred[d].add(s)

    dist_from_query = _bfs_dist(query_node, succ)
    dist_to_query = _bfs_dist(query_node, pred)

    anc_depth = max([d for n, d in dist_to_query.items() if n != query_node], default=0)

    level: Dict[str, int] = {}
    level[query_node] = anc_depth

    for n, d in dist_to_query.items():
        if n == query_node:
            continue
        level[n] = anc_depth - d

    for n, d in dist_from_query.items():
        if n == query_node:
            continue
        level[n] = anc_depth + d

    return level


def _fill_missing_levels(
    levels: Dict[str, int],
    query_node: str,
    anc_set: Set[str],
    desc_set: Set[str],
) -> Dict[str, int]:
    filled = dict(levels)
    q_level = filled.get(query_node, 0)
    for n in anc_set:
        if n not in filled:
            filled[n] = q_level - 1
    for n in desc_set:
        if n not in filled:
            filled[n] = q_level + 1
    if query_node not in filled:
        filled[query_node] = q_level
    return filled


def _trim_far_levels(
    levels: Dict[str, int],
    sparse_edges: Sequence[Tuple[str, str]],
    query_node: str,
    max_hops: int = 3,
) -> Tuple[Dict[str, int], List[Tuple[str, str]]]:
    q_level = levels.get(query_node, 0)
    keep_nodes: Set[str] = {
        n for n, lv in levels.items() if abs(lv - q_level) <= max_hops or n == query_node
    }
    trimmed_levels = {n: lv for n, lv in levels.items() if n in keep_nodes}
    trimmed_edges = [(s, d) for (s, d) in sparse_edges if s in keep_nodes and d in keep_nodes]
    return trimmed_levels, trimmed_edges


def _compress_levels(
    levels: Dict[str, int],
    sparse_edges: Sequence[Tuple[str, str]],
    query_node: str,
    max_nodes_per_level: int,
    mandatory_nodes: Set[str],
) -> Tuple[Dict[str, int], List[Tuple[str, str]]]:
    if not levels:
        return levels, list(sparse_edges)

    # Target skeleton from top to bottom.
    pattern = [2, 4, 3, 1, 3, 4, 2]

    degree: Dict[str, int] = defaultdict(int)
    for s, d in sparse_edges:
        degree[s] += 1
        degree[d] += 1

    q_level = levels.get(query_node, 0)
    ancestors = [n for n, lv in levels.items() if lv < q_level and n != query_node]
    descendants = [n for n, lv in levels.items() if lv > q_level and n != query_node]

    anc_dist = {n: q_level - levels[n] for n in ancestors}
    desc_dist = {n: levels[n] - q_level for n in descendants}

    anc1 = [n for n in ancestors if anc_dist[n] == 1]
    anc2 = [n for n in ancestors if anc_dist[n] == 2]
    anc3p = [n for n in ancestors if anc_dist[n] >= 3]
    desc1 = [n for n in descendants if desc_dist[n] == 1]
    desc2 = [n for n in descendants if desc_dist[n] == 2]
    desc3p = [n for n in descendants if desc_dist[n] >= 3]

    def rank_nodes(nodes: Sequence[str]) -> List[str]:
        return sorted(nodes, key=lambda n: (-degree.get(n, 0), _stable_node_key(n)))

    taken: Set[str] = set()

    all_pool_nodes = [n for n in levels.keys() if n != query_node]

    def pick(pool_groups: Sequence[Sequence[str]], quota: int, mandatory: Optional[Sequence[str]] = None) -> List[str]:
        chosen: List[str] = []
        if mandatory:
            for n in mandatory:
                if n not in taken and n not in chosen:
                    chosen.append(n)
                    taken.add(n)
        if len(chosen) >= quota:
            return chosen[:quota]

        for group in pool_groups:
            for n in rank_nodes(group):
                if n in taken:
                    continue
                chosen.append(n)
                taken.add(n)
                if len(chosen) >= quota:
                    return chosen

        # Final fallback: fill from any remaining node.
        for n in rank_nodes(all_pool_nodes):
            if n in taken:
                continue
            chosen.append(n)
            taken.add(n)
            if len(chosen) >= quota:
                break
        return chosen

    layer_nodes: List[List[str]] = []
    layer_nodes.append(pick([anc3p, anc2, anc1], pattern[0]))
    layer_nodes.append(pick([anc2, anc3p, anc1], pattern[1]))
    layer_nodes.append(pick([anc1, anc2, anc3p], pattern[2]))
    taken.add(query_node)
    layer_nodes.append([query_node])
    layer_nodes.append(pick([desc1, desc2, desc3p], pattern[4]))
    layer_nodes.append(pick([desc2, desc1, desc3p], pattern[5]))
    layer_nodes.append(pick([desc3p, desc2, desc1], pattern[6]))

    node_to_layer: Dict[str, int] = {}
    for li, group in enumerate(layer_nodes):
        for n in group:
            if n not in node_to_layer:
                node_to_layer[n] = li

    # Ensure query is present in the dedicated middle layer.
    node_to_layer[query_node] = 3

    selected = set(node_to_layer.keys())

    # Build per-layer symmetric order for prettier placement and edge routing.
    rows: Dict[int, List[str]] = {}
    for lv in range(len(pattern)):
        nodes_in_lv = [n for n, l in node_to_layer.items() if l == lv]
        center = query_node if lv == 3 else None
        rows[lv] = _arrange_nodes_symmetric(nodes_in_lv, degree, center)

    candidate_edges = [
        (s, d)
        for (s, d) in sparse_edges
        if s in selected and d in selected and node_to_layer[s] < node_to_layer[d]
    ]

    edge_set = set(candidate_edges)
    kept: Set[Tuple[str, str]] = set()

    # Keep connections mostly between adjacent layers for a cleaner skeleton.
    pair_candidates: Dict[Tuple[int, int], List[Tuple[str, str]]] = defaultdict(list)
    for s, d in candidate_edges:
        ls = node_to_layer[s]
        ld = node_to_layer[d]
        if ld == ls + 1:
            pair_candidates[(ls, ld)].append((s, d))

    for li in range(len(pattern) - 1):
        upper = rows.get(li, [])
        lower = rows.get(li + 1, [])
        if not upper or not lower:
            continue

        up_pos = {n: i for i, n in enumerate(upper)}
        dn_pos = {n: i for i, n in enumerate(lower)}

        # Around the middle 3->1->3, force fan-in/fan-out so center is clearly connected.
        if len(lower) == 1:
            center = lower[0]
            for s in upper:
                e = (s, center)
                if e in edge_set:
                    kept.add(e)
                else:
                    kept.add(e)
            continue
        if len(upper) == 1:
            center = upper[0]
            for d in lower:
                e = (center, d)
                if e in edge_set:
                    kept.add(e)
                else:
                    kept.add(e)
            continue

        cands = pair_candidates.get((li, li + 1), [])
        if not cands:
            # Fallback: nearest synthetic links if this pair has no explicit edges.
            scale = (len(upper) - 1) / max(1, (len(lower) - 1))
            for j, d in enumerate(lower):
                i = int(round(j * scale))
                i = max(0, min(i, len(upper) - 1))
                kept.add((upper[i], d))
            continue

        def dist(e: Tuple[str, str]) -> float:
            s, d = e
            return abs(up_pos[s] - dn_pos[d])

        # Cover every lower node.
        for d in lower:
            c = [e for e in cands if e[1] == d]
            if c:
                kept.add(sorted(c, key=lambda e: (dist(e), _stable_key(e)))[0])

        # Cover every upper node.
        for s in upper:
            c = [e for e in cands if e[0] == s]
            if c and not any(e[0] == s for e in kept if node_to_layer.get(e[0]) == li and node_to_layer.get(e[1]) == li + 1):
                kept.add(sorted(c, key=lambda e: (dist(e), _stable_key(e)))[0])

        # Add a few short-span edges to keep structure rich but readable.
        in_deg_pair: Dict[str, int] = defaultdict(int)
        out_deg_pair: Dict[str, int] = defaultdict(int)
        for s, d in kept:
            if node_to_layer.get(s) == li and node_to_layer.get(d) == li + 1:
                out_deg_pair[s] += 1
                in_deg_pair[d] += 1

        for e in sorted(cands, key=lambda e: (dist(e), _stable_key(e))):
            if e in kept:
                continue
            s, d = e
            if dist(e) > 1.2:
                continue
            if out_deg_pair[s] >= 2 or in_deg_pair[d] >= 2:
                continue
            kept.add(e)
            out_deg_pair[s] += 1
            in_deg_pair[d] += 1

    # Deduplicate and keep forward-only edges in selected skeleton.
    kept = {(s, d) for (s, d) in kept if s in selected and d in selected and node_to_layer[s] < node_to_layer[d]}

    return node_to_layer, sorted(kept)


def _find_cluster_bounds(svg_text: str, cluster_title: str) -> Optional[Tuple[float, float, float, float]]:
    m = re.search(rf"<title>{re.escape(cluster_title)}</title>\s*<path[^>]* d=\"([^\"]+)\"", svg_text)
    if not m:
        return None
    nums = [float(v) for v in re.findall(r"-?\d+(?:\.\d+)?", m.group(1))]
    if len(nums) < 8:
        return None
    xs = nums[0::2]
    ys = nums[1::2]
    return (min(xs), max(xs), min(ys), max(ys))


def _find_node_center(svg_text: str, node_title: str) -> Optional[Tuple[float, float]]:
    m = re.search(
        rf"<title>{re.escape(node_title)}</title>.*?<ellipse[^>]* cx=\"([^\"]+)\" cy=\"([^\"]+)\"",
        svg_text,
        re.S,
    )
    if not m:
        return None
    return (float(m.group(1)), float(m.group(2)))


def _arrow_points(end_x: float, end_y: float, dir_x: float, dir_y: float) -> str:
    n = math.hypot(dir_x, dir_y)
    if n < 1e-6:
        dir_x, dir_y = 0.0, 1.0
        n = 1.0
    ux = dir_x / n
    uy = dir_y / n
    size = 12.0
    half_w = 4.5
    bx = end_x - ux * size
    by = end_y - uy * size
    px = -uy
    py = ux
    p1x = bx + px * half_w
    p1y = by + py * half_w
    p2x = bx - px * half_w
    p2y = by - py * half_w
    return f"{end_x:.2f},{end_y:.2f} {p1x:.2f},{p1y:.2f} {p2x:.2f},{p2y:.2f}"


def _rewrite_edge_group(
    svg_text: str,
    edge_title: str,
    path_d: str,
    poly_points: str,
    text_x: float,
    text_y: float,
) -> str:
    group_pat = re.compile(
        rf"(<g id=\"edge\d+\" class=\"edge\">\s*<title>{re.escape(edge_title)}</title>)(.*?)(</g>)",
        re.S,
    )
    gm = group_pat.search(svg_text)
    if not gm:
        return svg_text

    body = gm.group(2)
    body = re.sub(
        r'(<path[^>]* d=")[^"]*(")',
        lambda m: f"{m.group(1)}{path_d}{m.group(2)}",
        body,
        count=1,
    )
    body = re.sub(
        r'(<polygon[^>]* points=")[^"]*(")',
        lambda m: f"{m.group(1)}{poly_points}{m.group(2)}",
        body,
        count=1,
    )
    body = re.sub(
        r'(<text[^>]* x=")[^"]*(" y=")[^"]*(")',
        lambda m: f"{m.group(1)}{text_x:.2f}{m.group(2)}{text_y:.2f}{m.group(3)}",
        body,
        count=1,
    )

    return svg_text[: gm.start()] + gm.group(1) + body + gm.group(3) + svg_text[gm.end() :]


def _postprocess_prune_curves(svg_path: str, query_node: str) -> None:
    if not svg_path or not os.path.exists(svg_path):
        return

    with open(svg_path, "r", encoding="utf-8") as f:
        svg = f.read()

    ib = _find_cluster_bounds(svg, "cluster_I")
    fb = _find_cluster_bounds(svg, "cluster_F")
    iq = _find_node_center(svg, f"I_{query_node}")
    fq = _find_node_center(svg, f"F_{query_node}")
    if not ib or not fb or not iq or not fq:
        return

    i_xmin, i_xmax, i_ymin, i_ymax = ib
    f_xmin, f_xmax, f_ymin, f_ymax = fb
    iqx, iqy = iq
    fqx, fqy = fq

    # Descendant prune trend: smooth outward-down curve toward lower-right whitespace.
    i_start_x = iqx + 10.0
    i_start_y = iqy + 6.0
    i_end_x = i_xmax - 22.0
    i_end_y = i_ymax - 32.0
    i_c1_x = i_start_x + 78.0
    i_c1_y = i_start_y + 18.0
    i_c2_x = i_end_x - 16.0
    i_c2_y = i_end_y - 92.0
    i_d = (
        f"M{i_start_x:.2f},{i_start_y:.2f} "
        f"C{i_c1_x:.2f},{i_c1_y:.2f} {i_c2_x:.2f},{i_c2_y:.2f} {i_end_x:.2f},{i_end_y:.2f}"
    )
    i_poly = _arrow_points(i_end_x, i_end_y, i_end_x - i_c2_x, i_end_y - i_c2_y)
    svg = _rewrite_edge_group(
        svg,
        f"I_{query_node}&#45;&gt;I_trend",
        i_d,
        i_poly,
        i_end_x - 120.0,
        i_end_y + 16.0,
    )

    # Ancestor prune trend: smooth outward-up curve toward upper-left whitespace.
    f_start_x = fqx - 10.0
    f_start_y = fqy - 8.0
    f_end_x = f_xmin + 24.0
    f_end_y = f_ymin + 34.0
    f_c1_x = f_start_x - 84.0
    f_c1_y = f_start_y - 48.0
    f_c2_x = f_end_x + 18.0
    f_c2_y = f_end_y + 92.0
    f_d = (
        f"M{f_start_x:.2f},{f_start_y:.2f} "
        f"C{f_c1_x:.2f},{f_c1_y:.2f} {f_c2_x:.2f},{f_c2_y:.2f} {f_end_x:.2f},{f_end_y:.2f}"
    )
    f_poly = _arrow_points(f_end_x, f_end_y, f_end_x - f_c2_x, f_end_y - f_c2_y)
    svg = _rewrite_edge_group(
        svg,
        f"F_{query_node}&#45;&gt;F_trend",
        f_d,
        f_poly,
        f_end_x + 14.0,
        f_end_y + 18.0,
    )

    with open(svg_path, "w", encoding="utf-8") as f:
        f.write(svg)


def _pick_prune_hints(
    query_node: str,
    sparse_edges: Sequence[Tuple[str, str]],
) -> Tuple[str, str]:
    succ: Dict[str, Set[str]] = defaultdict(set)
    pred: Dict[str, Set[str]] = defaultdict(set)
    for s, d in sparse_edges:
        succ[s].add(d)
        pred[d].add(s)

    dist_from_query = _bfs_dist(query_node, succ)
    dist_to_query = _bfs_dist(query_node, pred)

    desc_candidates = [n for n, d in dist_from_query.items() if n != query_node and d > 0]
    anc_candidates = [n for n, d in dist_to_query.items() if n != query_node and d > 0]

    desc_hint = query_node
    anc_hint = query_node
    if desc_candidates:
        # Keep the hint close to query so the directional dashed line stays inside panel bounds.
        desc_hint = sorted(desc_candidates, key=lambda n: (dist_from_query[n], n))[0]
    if anc_candidates:
        anc_hint = sorted(anc_candidates, key=lambda n: (dist_to_query[n], n))[0]

    return anc_hint, desc_hint


def _node_style(
    node_id: str,
    query_node: str,
    meta: Dict[str, NodeMeta],
) -> Tuple[str, str, str, str]:
    m = meta[node_id]
    fill = grayscale_for_hardening(m.hardening_level)
    color = "#000000"
    penwidth = "2.1"
    shape = "circle"

    if node_id == query_node:
        fill = "#ffe8cc"
        color = "#ff7f0e"
        penwidth = "3.2"
        shape = "doublecircle"

    return fill, color, penwidth, shape


def _emit_panel(
    f,
    panel_prefix: str,
    panel_title: str,
    formula_text: str,
    query_node: str,
    sparse_edges: Sequence[Tuple[str, str]],
    levels: Dict[str, int],
    meta: Dict[str, NodeMeta],
) -> None:
    f.write(f'    subgraph cluster_{panel_prefix} {{\n')
    f.write(
        '        label=<'
        '<TABLE BORDER="0" CELLBORDER="0" CELLPADDING="1" CELLSPACING="0" WIDTH="320">'
        f'<TR><TD ALIGN="CENTER"><FONT POINT-SIZE="21"><B>{panel_title}</B></FONT></TD></TR>'
        f'<TR><TD ALIGN="CENTER"><FONT POINT-SIZE="19">{formula_text}</FONT></TD></TR>'
        '</TABLE>'
        '>;\n'
    )
    f.write('        color="#888888";\n')
    f.write('        style="rounded,dashed";\n')
    f.write('        penwidth=1.2;\n')
    f.write('        margin=8;\n')
    f.write('        fontsize=18;\n')

    panel_nodes = sorted(set(levels.keys()))
    for nid in panel_nodes:
        fill, color, penwidth, shape = _node_style(nid, query_node, meta)
        tooltip = _escape_dot(meta[nid].tooltip)
        f.write(
            f'        {panel_prefix}_{nid} [label="", tooltip="{tooltip}", fillcolor="{fill}", '
            f'color="{color}", penwidth={penwidth}, shape={shape}];\n'
        )

    level_to_nodes: Dict[int, List[str]] = defaultdict(list)
    for nid, lv in levels.items():
        level_to_nodes[lv].append(nid)

    level_keys = sorted(level_to_nodes.keys())
    query_level = levels.get(query_node)

    pred: Dict[str, Set[str]] = defaultdict(set)
    succ: Dict[str, Set[str]] = defaultdict(set)
    for s, d in sparse_edges:
        pred[d].add(s)
        succ[s].add(d)

    ordered_levels: Dict[int, List[str]] = {}
    if level_keys:
        ordered_levels[level_keys[0]] = sorted(level_to_nodes[level_keys[0]], key=_stable_node_key)

    # Forward barycentric ordering to reduce edge crossings.
    for i in range(1, len(level_keys)):
        lv = level_keys[i]
        prev_lv = level_keys[i - 1]
        prev_order = ordered_levels[prev_lv]
        prev_pos = {n: j for j, n in enumerate(prev_order)}

        def bary_score(n: str) -> float:
            neigh = [p for p in pred.get(n, set()) if levels.get(p) == prev_lv]
            if not neigh:
                return float(_stable_node_key(n))
            return sum(prev_pos[p] for p in neigh) / len(neigh)

        ordered_levels[lv] = sorted(level_to_nodes[lv], key=lambda n: (bary_score(n), _stable_node_key(n)))

    max_count = max((len(v) for v in ordered_levels.values()), default=1)
    axis_refs: List[str] = []

    for lv in level_keys:
        ordered = list(ordered_levels[lv])
        axis_name = f"{panel_prefix}_axis_{lv}"

        if query_level is not None and lv == query_level and query_node in ordered:
            others = [n for n in ordered if n != query_node]
            left_count = len(others) // 2
            left_nodes = others[:left_count]
            right_nodes = others[left_count:]
            axis_ref = f"{panel_prefix}_{query_node}"
        else:
            left_count = len(ordered) // 2
            if len(ordered) % 2 == 1 and query_level is not None and lv > query_level:
                left_count += 1
            left_nodes = ordered[:left_count]
            right_nodes = ordered[left_count:]
            axis_ref = axis_name
            f.write(
                f'        {axis_name} [shape=point, width=0.02, height=0.02, label="", style=invis, group="axis"];\n'
            )

        # Symmetric side pads keep every level centered and help equalize cluster sizes.
        missing = max_count - len(ordered)
        pad_w_l = 0.20 + 0.28 * missing
        pad_w_r = pad_w_l
        if query_level is not None and lv == query_level:
            # Slightly bias query row to the right so highlighted node appears centered in panel.
            pad_w_l += 2.15
            pad_w_r = max(0.12, pad_w_r - 0.42)
        pad_l = f"{panel_prefix}_pad_l_{lv}"
        pad_r = f"{panel_prefix}_pad_r_{lv}"
        f.write(
            f'        {pad_l} [shape=box, width={pad_w_l:.2f}, height=0.02, fixedsize=true, label="", style=invis];\n'
        )
        f.write(
            f'        {pad_r} [shape=box, width={pad_w_r:.2f}, height=0.02, fixedsize=true, label="", style=invis];\n'
        )

        row_parts: List[str] = [pad_l]
        row_parts.extend(f"{panel_prefix}_{n}" for n in left_nodes)
        row_parts.append(axis_ref)
        row_parts.extend(f"{panel_prefix}_{n}" for n in right_nodes)
        row_parts.append(pad_r)
        f.write(f"        {{ rank=same; {' '.join(row_parts)}; }}\n")
        f.write(f'        {pad_l} -> {axis_ref} [style=invis, weight=120, constraint=true];\n')
        f.write(f'        {axis_ref} -> {pad_r} [style=invis, weight=120, constraint=true];\n')

        axis_refs.append(axis_ref)

    # Tie all per-level axes into a vertical center line.
    for i in range(len(axis_refs) - 1):
        f.write(f'        {axis_refs[i]} -> {axis_refs[i + 1]} [style=invis, weight=200, constraint=true];\n')

    for s, d in sparse_edges:
        f.write(f"        {panel_prefix}_{s} -> {panel_prefix}_{d}\n")
    f.write("    }\n")


def write_single_query_pruning_dot(
    out_dot: str,
    nodes: Sequence[str],
    edges: Sequence[Tuple[str, str]],
    meta: Dict[str, NodeMeta],
    query_node: str,
    anc_set: Set[str],
    desc_set: Set[str],
    total_nodes: int,
) -> None:
    subset_nodes = set(anc_set) | set(desc_set)
    subset_edges = _induced_edges(subset_nodes, edges)
    sparse_edges = _build_sparse_edges(subset_nodes, subset_edges, query_node)
    anc_hint, desc_hint = _pick_prune_hints(query_node, sparse_edges)
    levels = _fill_missing_levels(
        levels=_build_levels(query_node, sparse_edges),
        query_node=query_node,
        anc_set=anc_set,
        desc_set=desc_set,
    )
    levels, sparse_edges = _trim_far_levels(levels, sparse_edges, query_node, max_hops=3)
    anc_hint, desc_hint = _pick_prune_hints(query_node, sparse_edges)
    levels, sparse_edges = _compress_levels(
        levels=levels,
        sparse_edges=sparse_edges,
        query_node=query_node,
        max_nodes_per_level=3,
        mandatory_nodes={query_node, anc_hint, desc_hint},
    )
    # Remove same-level links; they often look like awkward horizontal jumps.
    sparse_edges = [e for e in sparse_edges if levels.get(e[0]) != levels.get(e[1])]
    anc_hint, desc_hint = _pick_prune_hints(query_node, sparse_edges)

    with open(out_dot, "w", encoding="utf-8") as f:
        f.write("digraph g {\n")
        f.write("    rankdir=TB;\n")
        f.write("    ratio=0.75;\n")
        f.write("    nodesep=0.38;\n")
        f.write("    ranksep=0.44;\n")
        f.write("    splines=polyline;\n")
        f.write("    pack=1;\n")
        f.write('    packmode="array_u2";\n')
        f.write('    graph [labeljust=l, labelloc=t, fontsize=24, fontname="Times New Roman"];\n')
        f.write('    node [style="filled,setlinewidth(2)", shape=circle, color=black, fillcolor=white, fontname="Times New Roman", width=0.52, height=0.52, fixedsize=true];\n')
        f.write('    edge [arrowsize=1.05, len=.7, color="#B7B7B7", penwidth=0.95, fontname="Times New Roman"];\n')
        f.write(
            '    label=<'
            f'<FONT POINT-SIZE="28">Single-query pruning on nginx poset (induced subgraph)</FONT><BR/>'
            f'<FONT POINT-SIZE="23">|C|={total_nodes}, query={query_node}, |anc(c)|={len(anc_set)}, |desc(c)|={len(desc_set)}</FONT>'
            '>;\n\n'
        )

        _emit_panel(
            f=f,
            panel_prefix="I",
            panel_title="Case B (infeasible)",
            formula_text="<B><I>g(c)</I> &lt; 0:</B> <I>C</I> ← <I>C</I> ∖ <I>desc(c)</I>",
            query_node=query_node,
            sparse_edges=sparse_edges,
            levels=levels,
            meta=meta,
        )

        _emit_panel(
            f=f,
            panel_prefix="F",
            panel_title="Case A (feasible)",
            formula_text="<B><I>g(c)</I> ≥ 0:</B> <I>C</I> ← <I>C</I> ∖ <I>anc(c)</I>",
            query_node=query_node,
            sparse_edges=sparse_edges,
            levels=levels,
            meta=meta,
        )

        # Keep the two panels side-by-side via packed disconnected components.

        f.write("}\n")


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Plot single-query pruning illustration in fig08 style")
    p.add_argument("--config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--method", default="REQ", help="Performance key in config map")
    p.add_argument("--query-node", default=None, help="Optional query node (e.g., C81)")
    p.add_argument("--out-dot", default="./result/single_query_pruning.dot")
    p.add_argument("--out-svg", default="./result/svg/single_query_pruning.svg")
    p.add_argument("--out-png", default="./result/png/single_query_pruning.png", help="Output PNG path (optional)")
    p.add_argument("--png-dpi", type=int, default=300, help="PNG resolution in DPI")
    return p.parse_args()


def main() -> None:
    args = parse_args()

    os.makedirs(os.path.dirname(os.path.abspath(args.out_dot)), exist_ok=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out_svg)), exist_ok=True)
    if args.out_png:
        os.makedirs(os.path.dirname(os.path.abspath(args.out_png)), exist_ok=True)

    nodes, edges, meta = _build_node_meta(args.config_map, args.method)
    poset = DagPosetSearch(nodes, edges)

    query_node = _pick_query_node(nodes, poset.anc_bits, poset.desc_bits, args.query_node)
    qidx = poset.node_to_idx[query_node]

    full_mask = (1 << len(nodes)) - 1
    anc_set = set(poset._mask_to_names(poset.anc_bits[qidx] & full_mask))
    desc_set = set(poset._mask_to_names(poset.desc_bits[qidx] & full_mask))

    write_single_query_pruning_dot(
        out_dot=args.out_dot,
        nodes=nodes,
        edges=edges,
        meta=meta,
        query_node=query_node,
        anc_set=anc_set,
        desc_set=desc_set,
        total_nodes=len(nodes),
    )

    print(f"Generated DOT: {args.out_dot}")
    print(
        f"Selected query node: {query_node} |anc(c)|={len(anc_set)} |desc(c)|={len(desc_set)} "
        f"induced_nodes={len(anc_set | desc_set)}"
    )
    maybe_render_svg(args.out_dot, args.out_svg, args.out_png if args.out_png else None, args.png_dpi)


if __name__ == "__main__":
    main()
