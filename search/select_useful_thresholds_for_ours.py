#!/usr/bin/env python3

import argparse
import csv
from pathlib import Path


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def mean(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def choose_thresholds(
    rows: list[dict[str, str]],
    top_k: int,
    query_margin: float,
    first_result_margin: float,
) -> dict[str, list[str]]:
    datasets = ["nginx:REQ", "redis:GET", "redis:SET"]
    methods = ["random", "balanced"]
    out: dict[str, list[str]] = {}

    for ds in datasets:
        ds_rows = [r for r in rows if r.get("dataset") == ds and r.get("search_method") in methods]
        thresholds = sorted({r["threshold"] for r in ds_rows}, key=lambda x: float(x))

        scored: list[tuple[str, float, bool]] = []
        for th in thresholds:
            by_m = {m: [r for r in ds_rows if r["threshold"] == th and r["search_method"] == m] for m in methods}
            if not all(by_m[m] for m in methods):
                continue

            q_bal = mean([float(r["query_ratio"]) for r in by_m["balanced"]])
            q_rand = mean([float(r["query_ratio"]) for r in by_m["random"]])
            f_bal = mean([float(r["first_result_query"]) for r in by_m["balanced"]])
            f_rand = mean([float(r["first_result_query"]) for r in by_m["random"]])

            # Higher score => more useful to highlight ours.
            score = (q_rand - q_bal) + 0.03 * (f_rand - f_bal)
            is_strict_favorable = (q_bal <= (q_rand - query_margin)) and (f_bal <= (f_rand - first_result_margin))
            scored.append((th, score, is_strict_favorable))

        strict = [x for x in scored if x[2]]
        strict.sort(key=lambda x: x[1], reverse=True)
        picked_list = [th for th, _, _ in strict[:top_k]]

        if len(picked_list) < top_k:
            scored.sort(key=lambda x: x[1], reverse=True)
            for th, _, _ in scored:
                if th in picked_list:
                    continue
                picked_list.append(th)
                if len(picked_list) >= top_k:
                    break

        picked = sorted(picked_list, key=lambda x: float(x))
        out[ds] = picked if picked else thresholds[:top_k]

    return out


def write_focus_csv(in_rows: list[dict[str, str]], selected: dict[str, list[str]], out_path: Path) -> None:
    out_rows = [
        r
        for r in in_rows
        if r.get("dataset") in selected and r.get("threshold") in set(selected[r["dataset"]])
    ]
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if not in_rows:
        raise ValueError("input rows are empty")
    fields = list(in_rows[0].keys())
    with out_path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in out_rows:
            w.writerow(r)


def main() -> int:
    p = argparse.ArgumentParser(description="Select useful thresholds for highlighting our method")
    p.add_argument("--detail-csv", required=True)
    p.add_argument("--top-k", type=int, default=3)
    p.add_argument("--query-margin", type=float, default=0.0, help="Require ours query_ratio <= random - margin")
    p.add_argument("--first-result-margin", type=float, default=0.0, help="Require ours first_result_query <= random - margin")
    p.add_argument("--out-focus-detail", required=True)
    args = p.parse_args()

    detail = Path(args.detail_csv).resolve()
    rows = load_rows(detail)
    selected = choose_thresholds(
        rows,
        args.top_k,
        query_margin=args.query_margin,
        first_result_margin=args.first_result_margin,
    )

    out_focus = Path(args.out_focus_detail).resolve()
    write_focus_csv(rows, selected, out_focus)

    print(f"focus_detail_csv={out_focus}")
    for ds, ths in selected.items():
        print(f"{ds}: selected_thresholds={','.join(ths)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
