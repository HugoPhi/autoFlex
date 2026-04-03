#!/usr/bin/env python3

import argparse
import csv
import os
from typing import Dict, List, Optional, Sequence, Tuple

from dag_poset_search import DagPosetSearch
from validate_all_hypothesis import build_cover_edges, load_config_rows


def parse_threshold_list(text: str) -> List[float]:
    text = text.strip()
    if text.startswith("[") and text.endswith("]"):
        text = text[1:-1]

    values = []
    for x in text.split(","):
        x = x.strip()
        if not x:
            continue
        values.append(float(x))
    return values


def ensure_parent(path: str) -> None:
    parent = os.path.dirname(os.path.abspath(path))
    if parent:
        os.makedirs(parent, exist_ok=True)


def reduce_to_minimal_frontier(search: DagPosetSearch, feasible_nodes: Sequence[str]) -> List[str]:
    feasible_mask = 0
    for n in feasible_nodes:
        idx = search.node_to_idx.get(n)
        if idx is not None:
            feasible_mask |= 1 << idx

    minimal_mask = feasible_mask
    for i in range(search.n):
        if not (feasible_mask & (1 << i)):
            continue
        reach_other = (search.desc_bits[i] & feasible_mask) & ~(1 << i)
        if reach_other:
            minimal_mask &= ~(1 << i)

    out = []
    for i, name in enumerate(search.nodes):
        if minimal_mask & (1 << i):
            out.append(name)
    return out


def compare_answers_and_reason(search_answers: Sequence[str], exhaustive_answers: Sequence[str]) -> Tuple[str, str]:
    s = set(search_answers)
    e = set(exhaustive_answers)

    if s == e:
        return "exact", "Search frontier exactly matches exhaustive frontier."
    if s.issubset(e):
        return (
            "subset_sound",
            "Search answers are a feasible subset of exhaustive frontier; conservative under pruning.",
        )
    if e.issubset(s):
        return (
            "superset_reasonable",
            "Search includes feasible nodes dominated by exhaustive frontier leaves; still feasible but not minimal.",
        )
    if not s and not e:
        return "exact", "Both methods found no feasible frontier nodes."
    return (
        "overlap_partial",
        "Search and exhaustive frontiers partially overlap; search still returns feasible representatives.",
    )


def write_summary_csv(path: str, rows: List[dict]) -> None:
    ensure_parent(path)
    fields = [
        "search_method",
        "method_label",
        "dataset",
        "threshold",
        "source",
        "nodes",
        "edges",
        "query_count",
        "query_ratio",
        "first_feasible_query",
        "first_feasible_query_ratio",
        "final_answers",
        "exhaustive_answers",
        "answer_validation",
        "validation_note",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def write_trace_csv(path: str, rows: List[dict]) -> None:
    ensure_parent(path)
    fields = [
        "search_method",
        "method_label",
        "dataset",
        "threshold",
        "step",
        "candidate_size_before",
        "centroid",
        "a_count",
        "d_count",
        "queried_value",
        "feasible",
        "pruned_count",
        "candidate_size_after",
    ]
    with open(path, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def run_series(
    dataset: str,
    method: str,
    config_map_path: str,
    threshold: float,
    source_mode: str,
    method_specs: Sequence[Tuple[str, str]],
    random_seed: int,
) -> Tuple[List[dict], List[dict]]:
    rows = load_config_rows(config_map_path, (method,))
    edges = build_cover_edges(rows)
    nodes = [r.config_id for r in rows]

    search = DagPosetSearch(nodes, edges)

    summary_rows: List[dict] = []
    trace_rows: List[dict] = []

    g_values: Dict[str, float] = {r.config_id: r.metrics[method] for r in rows}

    if source_mode == "max-g":
        source = max(g_values.items(), key=lambda x: x[1])[0]
    elif source_mode == "none":
        source = None
    else:
        source = source_mode

    exhaustive_feasible = [n for n in nodes if g_values[n] >= threshold]
    exhaustive_answers = reduce_to_minimal_frontier(search, exhaustive_feasible)

    naive = len(nodes)
    summary_rows.append(
        {
            "search_method": "exhaustive",
            "method_label": "Exhaustive",
            "dataset": f"{dataset}:{method}",
            "threshold": f"{threshold:.6f}",
            "source": source or "",
            "nodes": len(nodes),
            "edges": len(edges),
            "query_count": naive,
            "query_ratio": f"{1.0:.6f}",
            "first_feasible_query": 1 if exhaustive_feasible else 0,
            "first_feasible_query_ratio": f"{(1.0 / naive) if naive else 0.0:.6f}",
            "final_answers": "|".join(exhaustive_answers),
            "exhaustive_answers": "|".join(exhaustive_answers),
            "answer_validation": "exact",
            "validation_note": "Exhaustive reference baseline.",
        }
    )

    for method_key, method_label in method_specs:
        result = search.run_single_source_search(
            g_values=g_values,
            threshold=threshold,
            source=source,
            strategy=method_key,
            random_seed=random_seed,
        )
        ratio = 0.0 if naive == 0 else result.query_count / naive
        first_feasible_query = 0
        for step in result.trace:
            if step.feasible:
                first_feasible_query = step.step
                break
        first_feasible_query_ratio = 0.0 if naive == 0 else first_feasible_query / naive
        answer_validation, validation_note = compare_answers_and_reason(
            result.final_answers,
            exhaustive_answers,
        )

        summary_rows.append(
            {
                "search_method": method_key,
                "method_label": method_label,
                "dataset": f"{dataset}:{method}",
                "threshold": f"{threshold:.6f}",
                "source": source or "",
                "nodes": len(nodes),
                "edges": len(edges),
                "query_count": result.query_count,
                "query_ratio": f"{ratio:.6f}",
                "first_feasible_query": first_feasible_query,
                "first_feasible_query_ratio": f"{first_feasible_query_ratio:.6f}",
                "final_answers": "|".join(result.final_answers),
                "exhaustive_answers": "|".join(exhaustive_answers),
                "answer_validation": answer_validation,
                "validation_note": validation_note,
            }
        )

        for step in result.trace:
            trace_rows.append(
                {
                    "search_method": method_key,
                    "method_label": method_label,
                    "dataset": f"{dataset}:{method}",
                    "threshold": f"{threshold:.6f}",
                    "step": step.step,
                    "candidate_size_before": step.candidate_size_before,
                    "centroid": step.centroid,
                    "a_count": step.a_count,
                    "d_count": step.d_count,
                    "queried_value": f"{step.queried_value:.6f}",
                    "feasible": int(step.feasible),
                    "pruned_count": step.pruned_count,
                    "candidate_size_after": step.candidate_size_after,
                }
            )

    return summary_rows, trace_rows


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="Run topological balanced probe DAG search experiments")
    p.add_argument("--nginx-config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--redis-config-map", default="./data/redis_config_map.csv")
    p.add_argument(
        "--threshold-list",
        default="",
        help=(
            "Ordered thresholds for [nginx REQ, redis GET, redis SET]. "
            "Example: '[3000,2000]' means run nginx:REQ=3000 and redis:GET=2000; "
            "redis:SET is skipped."
        ),
    )
    p.add_argument(
        "--source-mode",
        default="max-g",
        help="max-g | none | explicit node id",
    )
    p.add_argument(
        "--search-methods",
        default="balanced,random",
        help="Comma-separated methods among: balanced,random,first,worst",
    )
    p.add_argument("--random-seed", type=int, default=0)
    p.add_argument("--out-summary", default="./result/dag_search_summary.csv")
    p.add_argument("--out-trace", default="./result/dag_search_trace.csv")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    threshold_list = parse_threshold_list(args.threshold_list)
    if not threshold_list:
        raise SystemExit("--threshold-list is empty. Provide at least one threshold.")

    method_label_map: Dict[str, str] = {
        "balanced": "Balanced (Ours)",
        "first": "First-candidate",
        "random": "Random-candidate",
        "worst": "Worst-split",
    }
    method_specs: List[Tuple[str, str]] = []
    for token in args.search_methods.split(","):
        key = token.strip()
        if not key:
            continue
        if key not in method_label_map:
            raise SystemExit(f"Unknown search method: {key}")
        method_specs.append((key, method_label_map[key]))
    if not method_specs:
        raise SystemExit("No search methods selected. Use --search-methods.")

    all_summary: List[dict] = []
    all_trace: List[dict] = []

    ordered_series: List[Tuple[str, str, str]] = [
        ("nginx", "REQ", args.nginx_config_map),
        ("redis", "GET", args.redis_config_map),
        ("redis", "SET", args.redis_config_map),
    ]

    for i, (dataset, method, cfg_path) in enumerate(ordered_series):
        if i >= len(threshold_list):
            continue
        threshold = threshold_list[i]
        s, t = run_series(
            dataset=dataset,
            method=method,
            config_map_path=cfg_path,
            threshold=threshold,
            source_mode=args.source_mode,
            method_specs=method_specs,
            random_seed=args.random_seed,
        )
        all_summary.extend(s)
        all_trace.extend(t)

    if not all_summary:
        raise SystemExit("No series executed. Check --threshold-list input.")

    write_summary_csv(args.out_summary, all_summary)
    write_trace_csv(args.out_trace, all_trace)

    print(f"summary_csv={os.path.abspath(args.out_summary)}")
    print(f"trace_csv={os.path.abspath(args.out_trace)}")
    print(f"runs={len(all_summary)}, trace_rows={len(all_trace)}")


if __name__ == "__main__":
    main()
