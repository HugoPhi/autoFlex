#!/usr/bin/env python3

import argparse
import csv
import statistics as st
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

from dag_poset_search import DagPosetSearch
from dag_poset_search_cli import compare_answers_and_reason, reduce_to_minimal_frontier
from validate_all_hypothesis import build_cover_edges, load_config_rows


@dataclass
class SeriesConfig:
    dataset: str
    metric: str
    config_map: Path
    thresholds: List[float]


def parse_float_list(text: str) -> List[float]:
    values: List[float] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(float(token))
    return values


def parse_int_list(text: str) -> List[int]:
    values: List[int] = []
    for token in text.split(","):
        token = token.strip()
        if not token:
            continue
        values.append(int(token))
    return values


def ensure_parent(path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)


def method_specs_from_text(text: str) -> List[Tuple[str, str]]:
    label_map = {
        "balanced": "Balanced (Ours)",
        "random": "Random-candidate",
        "first": "First-candidate",
        "worst": "Worst-split",
    }
    out: List[Tuple[str, str]] = [("exhaustive", "Exhaustive")]
    for token in text.split(","):
        key = token.strip()
        if not key:
            continue
        if key not in label_map:
            raise ValueError(f"Unknown method: {key}")
        out.append((key, label_map[key]))
    return out


def evaluate_series(
    series: SeriesConfig,
    method_specs: Sequence[Tuple[str, str]],
    seeds: Sequence[int],
    source_mode: str,
) -> List[dict]:
    rows = load_config_rows(str(series.config_map), (series.metric,))
    edges = build_cover_edges(rows)
    nodes = [r.config_id for r in rows]
    g_values: Dict[str, float] = {r.config_id: r.metrics[series.metric] for r in rows}

    search = DagPosetSearch(nodes, edges)
    naive = len(nodes)

    if source_mode == "max-g":
        source = max(g_values.items(), key=lambda x: x[1])[0]
    elif source_mode == "none":
        source = None
    else:
        source = source_mode

    out: List[dict] = []

    for threshold in series.thresholds:
        exhaustive_feasible = [n for n in nodes if g_values[n] >= threshold]
        exhaustive_answers = reduce_to_minimal_frontier(search, exhaustive_feasible)

        for seed in seeds:
            for method_key, method_label in method_specs:
                if method_key == "exhaustive":
                    query_count = naive
                    query_ratio = 1.0 if naive else 0.0
                    optimal_count = len(exhaustive_answers)
                    first_result_query = (naive / optimal_count) if (naive and optimal_count) else 0.0
                    first_result_ratio = (first_result_query / naive) if naive else 0.0
                    answer_validation = "exact"
                    validation_note = "Exhaustive reference baseline."
                    final_answers = exhaustive_answers
                else:
                    result = search.run_single_source_search(
                        g_values=g_values,
                        threshold=threshold,
                        source=source,
                        strategy=method_key,
                        random_seed=seed,
                    )
                    query_count = result.query_count
                    query_ratio = query_count / naive if naive else 0.0
                    first_result_query = 0.0
                    optimal_set = set(exhaustive_answers)
                    for step in result.trace:
                        if step.centroid in optimal_set:
                            first_result_query = float(step.step)
                            break
                    first_result_ratio = first_result_query / naive if naive else 0.0
                    answer_validation, validation_note = compare_answers_and_reason(
                        result.final_answers,
                        exhaustive_answers,
                    )
                    final_answers = result.final_answers

                out.append(
                    {
                        "dataset": f"{series.dataset}:{series.metric}",
                        "threshold": f"{threshold:.6f}",
                        "seed": seed,
                        "search_method": method_key,
                        "method_label": method_label,
                        "nodes": naive,
                        "query_count": query_count,
                        "query_ratio": f"{query_ratio:.6f}",
                        "first_result_query": f"{first_result_query:.6f}",
                        "first_result_query_ratio": f"{first_result_ratio:.6f}",
                        "final_answers": "|".join(final_answers),
                        "exhaustive_answers": "|".join(exhaustive_answers),
                        "answer_validation": answer_validation,
                        "validation_note": validation_note,
                    }
                )

    return out


def write_detail_csv(path: Path, rows: Sequence[dict]) -> None:
    ensure_parent(path)
    fields = [
        "dataset",
        "threshold",
        "seed",
        "search_method",
        "method_label",
        "nodes",
        "query_count",
        "query_ratio",
        "first_result_query",
        "first_result_query_ratio",
        "final_answers",
        "exhaustive_answers",
        "answer_validation",
        "validation_note",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def aggregate_rows(rows: Sequence[dict]) -> List[dict]:
    grouped: Dict[Tuple[str, str, str], List[dict]] = {}
    for r in rows:
        key = (r["dataset"], r["search_method"], r["method_label"])
        grouped.setdefault(key, []).append(r)

    out: List[dict] = []
    for (dataset, search_method, method_label), items in sorted(grouped.items()):
        n = len(items)
        query_count_vals = [float(x["query_count"]) for x in items]
        query_ratio_vals = [float(x["query_ratio"]) for x in items]
        first_result_vals = [float(x["first_result_query"]) for x in items]
        first_result_ratio_vals = [float(x["first_result_query_ratio"]) for x in items]

        mean_query_count = sum(query_count_vals) / n
        mean_query_ratio = sum(query_ratio_vals) / n
        mean_first_result = sum(first_result_vals) / n
        mean_first_result_ratio = sum(first_result_ratio_vals) / n
        std_query_count = st.pstdev(query_count_vals) if n > 1 else 0.0
        std_query_ratio = st.pstdev(query_ratio_vals) if n > 1 else 0.0
        std_first_result = st.pstdev(first_result_vals) if n > 1 else 0.0
        std_first_result_ratio = st.pstdev(first_result_ratio_vals) if n > 1 else 0.0
        out.append(
            {
                "dataset": dataset,
                "search_method": search_method,
                "method_label": method_label,
                "n_trials": n,
                "mean_query_count": f"{mean_query_count:.6f}",
                "std_query_count": f"{std_query_count:.6f}",
                "mean_query_ratio": f"{mean_query_ratio:.6f}",
                "std_query_ratio": f"{std_query_ratio:.6f}",
                "mean_first_result_query": f"{mean_first_result:.6f}",
                "std_first_result_query": f"{std_first_result:.6f}",
                "mean_first_result_query_ratio": f"{mean_first_result_ratio:.6f}",
                "std_first_result_query_ratio": f"{std_first_result_ratio:.6f}",
            }
        )
    return out


def write_agg_csv(path: Path, rows: Sequence[dict]) -> None:
    ensure_parent(path)
    fields = [
        "dataset",
        "search_method",
        "method_label",
        "n_trials",
        "mean_query_count",
        "std_query_count",
        "mean_query_ratio",
        "std_query_ratio",
        "mean_first_result_query",
        "std_first_result_query",
        "mean_first_result_query_ratio",
        "std_first_result_query_ratio",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            w.writerow(r)


def main() -> int:
    p = argparse.ArgumentParser(description="Evaluate search baselines across multiple thresholds and seeds")
    p.add_argument("--nginx-config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--redis-config-map", default="./data/redis_config_map.csv")
    p.add_argument("--req-thresholds", default="39000,42000,45000,48000,51000")
    p.add_argument("--get-thresholds", default="250000,280000,302000,324000,346000")
    p.add_argument("--set-thresholds", default="112000,126000,140200,154000,168000")
    p.add_argument("--seeds", default="0,1,2,3,4")
    p.add_argument("--source-mode", default="max-g")
    p.add_argument("--search-methods", default="balanced,random")
    p.add_argument("--out-detail", required=True)
    p.add_argument("--out-agg", required=True)
    args = p.parse_args()

    req_thresholds = parse_float_list(args.req_thresholds)
    get_thresholds = parse_float_list(args.get_thresholds)
    set_thresholds = parse_float_list(args.set_thresholds)
    seeds = parse_int_list(args.seeds)
    methods = method_specs_from_text(args.search_methods)

    if not (req_thresholds and get_thresholds and set_thresholds and seeds):
        raise ValueError("Threshold lists and seeds must be non-empty")

    series_list = [
        SeriesConfig("nginx", "REQ", Path(args.nginx_config_map).resolve(), req_thresholds),
        SeriesConfig("redis", "GET", Path(args.redis_config_map).resolve(), get_thresholds),
        SeriesConfig("redis", "SET", Path(args.redis_config_map).resolve(), set_thresholds),
    ]

    detail_rows: List[dict] = []
    for s in series_list:
        detail_rows.extend(evaluate_series(s, methods, seeds, args.source_mode))

    agg_rows = aggregate_rows(detail_rows)

    out_detail = Path(args.out_detail).resolve()
    out_agg = Path(args.out_agg).resolve()
    write_detail_csv(out_detail, detail_rows)
    write_agg_csv(out_agg, agg_rows)

    print(f"detail_csv={out_detail}")
    print(f"agg_csv={out_agg}")
    print(f"rows_detail={len(detail_rows)}, rows_agg={len(agg_rows)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
