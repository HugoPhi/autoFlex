#!/usr/bin/env python3

import argparse
import json
import os
from typing import Dict, List, Sequence, Tuple

from validate_all_hypothesis import build_cover_edges, load_config_rows

Edge = Tuple[str, str]


def analyze_one_series(
    app: str,
    method: str,
    edges: List[Edge],
    perf: Dict[str, float],
) -> dict:
    # Edge direction is B -> A in wording when src=B and dst=A.
    # Abnormal means perf(A) > perf(B), i.e. perf(dst) > perf(src).
    # Metric is (perf(A)-perf(B))/min(perf(A), perf(B)).
    # Under abnormal condition this equals (dst-src)/src when src>0.
    anomalies: List[dict] = []
    missing = 0
    for src, dst in edges:
        if src not in perf or dst not in perf:
            missing += 1
            continue
        b = float(perf[src])
        a = float(perf[dst])
        if a <= b:
            continue
        denom = min(a, b)
        if denom <= 0:
            continue
        ratio = (a - b) / denom
        anomalies.append(
            {
                "src": src,
                "dst": dst,
                "src_perf": b,
                "dst_perf": a,
                "ratio": ratio,
                "delta": a - b,
            }
        )

    if not anomalies:
        return {
            "app": app,
            "method": method,
            "total_edges": len(edges),
            "anomaly_edges": 0,
            "missing": missing,
            "max_ratio": 0.0,
            "max_ratio_percent": 0.0,
            "max_case": None,
        }

    anomalies.sort(key=lambda x: x["ratio"], reverse=True)
    top = anomalies[0]

    return {
        "app": app,
        "method": method,
        "total_edges": len(edges),
        "anomaly_edges": len(anomalies),
        "missing": missing,
        "max_ratio": top["ratio"],
        "max_ratio_percent": top["ratio"] * 100.0,
        "max_case": top,
    }


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description=(
            "Compute max abnormal ratio for B->A anomalies where perf(A)>perf(B): "
            "(perf(A)-perf(B))/min(perf(A),perf(B))."
        )
    )
    p.add_argument("--nginx-config-map", default="./data/nginx_config_map.csv")
    p.add_argument("--redis-config-map", default="./data/redis_config_map.csv")
    p.add_argument("--out-json", default="")
    p.add_argument(
        "--out-csv",
        default="",
        help="Optional CSV path to export all anomaly edges and ratio values",
    )
    return p.parse_args()


def main() -> None:
    args = parse_args()

    app_specs: Sequence[Tuple[str, str, Sequence[str]]] = [
        ("nginx", args.nginx_config_map, ("REQ",)),
        ("redis", args.redis_config_map, ("GET", "SET")),
    ]

    reports: List[dict] = []
    csv_rows: List[dict] = []

    for app, csv_path, methods in app_specs:
        rows = load_config_rows(csv_path, methods)
        if not rows:
            raise SystemExit(f"No rows found in {csv_path}")

        edges = build_cover_edges(rows)
        for method in methods:
            perf = {r.config_id: r.metrics[method] for r in rows}
            rep = analyze_one_series(
                app=app,
                method=method,
                edges=edges,
                perf=perf,
            )
            reports.append(rep)
            if rep.get("max_case") is not None:
                for idx, item in enumerate(
                    sorted(
                        [
                            {
                                "src": e[0],
                                "dst": e[1],
                                "src_perf": float(perf[e[0]]),
                                "dst_perf": float(perf[e[1]]),
                            }
                            for e in edges
                            if e[0] in perf and e[1] in perf and float(perf[e[1]]) > float(perf[e[0]])
                        ],
                        key=lambda x: (x["dst_perf"] - x["src_perf"]) / min(x["dst_perf"], x["src_perf"]),
                        reverse=True,
                    ),
                    start=1,
                ):
                    delta = item["dst_perf"] - item["src_perf"]
                    ratio = delta / min(item["dst_perf"], item["src_perf"])
                    csv_rows.append(
                        {
                            "rank": idx,
                            "app": app,
                            "method": method,
                            "src": item["src"],
                            "dst": item["dst"],
                            "src_perf": item["src_perf"],
                            "dst_perf": item["dst_perf"],
                            "delta": delta,
                            "ratio": ratio,
                            "ratio_percent": ratio * 100.0,
                        }
                    )

    global_max = None
    for r in reports:
        case = r.get("max_case")
        if case is None:
            continue
        key = case["ratio"]
        if global_max is None or key > global_max["ratio"]:
            global_max = {
                "app": r["app"],
                "method": r["method"],
                **case,
            }

    for r in reports:
        if r["max_case"] is None:
            print(f"{r['app']}/{r['method']}: no anomaly edge (perf(dst)>perf(src))")
            continue
        print(
            f"{r['app']}/{r['method']}: anomalies={r['anomaly_edges']}, "
            f"max_ratio={r['max_ratio']:.6f} ({r['max_ratio_percent']:.2f}%), "
            f"edge={r['max_case']['src']}-> {r['max_case']['dst']}, "
            f"src={r['max_case']['src_perf']:.6f}, dst={r['max_case']['dst_perf']:.6f}"
        )

    if global_max is None:
        print("overall: no anomaly edges found")
    else:
        print(
            "overall_max: "
            f"{global_max['app']}/{global_max['method']} "
            f"edge={global_max['src']}->{global_max['dst']}, "
            f"ratio={global_max['ratio']:.6f} ({global_max['ratio'] * 100.0:.2f}%)"
        )

    if args.out_json:
        payload = {
            "formula": "(perf(A)-perf(B))/min(perf(A),perf(B)) for anomaly edge B->A with perf(A)>perf(B)",
            "overall_max": global_max,
            "series": reports,
        }
        out_path = os.path.abspath(args.out_json)
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=True, indent=2)
        print(f"json: {out_path}")

    if args.out_csv:
        import csv

        out_csv = os.path.abspath(args.out_csv)
        os.makedirs(os.path.dirname(out_csv), exist_ok=True)
        fields = [
            "rank",
            "app",
            "method",
            "src",
            "dst",
            "src_perf",
            "dst_perf",
            "delta",
            "ratio",
            "ratio_percent",
        ]
        with open(out_csv, "w", encoding="utf-8", newline="") as f:
            w = csv.DictWriter(f, fieldnames=fields)
            w.writeheader()
            for row in csv_rows:
                w.writerow(
                    {
                        "rank": row["rank"],
                        "app": row["app"],
                        "method": row["method"],
                        "src": row["src"],
                        "dst": row["dst"],
                        "src_perf": f"{row['src_perf']:.6f}",
                        "dst_perf": f"{row['dst_perf']:.6f}",
                        "delta": f"{row['delta']:.6f}",
                        "ratio": f"{row['ratio']:.6f}",
                        "ratio_percent": f"{row['ratio_percent']:.2f}",
                    }
                )
        print(f"csv: {out_csv}")


if __name__ == "__main__":
    main()
