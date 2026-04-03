#!/usr/bin/env python3

import argparse
import csv
import json
import os
import re
from statistics import mean
from typing import Dict, Iterable, List, Optional, Sequence, Tuple

Edge = Tuple[str, str]


def check_edge_hypothesis(
	edges: Sequence[Edge],
	performance: Dict[str, float],
	epsilon: float = 0.0,
	epsilon_mode: str = "absolute",
) -> Tuple[List[dict], List[Edge]]:
	"""
	Validate: for every edge A -> B,
	- absolute mode: perf(A) + epsilon >= perf(B)
	- relative mode: perf(A) * (1 + epsilon) >= perf(B)

	Returns:
	  violations: list of dicts for edges that violate the hypothesis
	  missing: edges where either A or B has no performance value
	"""
	violations = []
	missing = []

	for src, dst in edges:
		if src not in performance or dst not in performance:
			missing.append((src, dst))
			continue

		src_perf = performance[src]
		dst_perf = performance[dst]
		required_eps_abs = max(0.0, dst_perf - src_perf)
		if src_perf > 0.0:
			required_eps_rel = max(0.0, (dst_perf - src_perf) / src_perf)
		else:
			required_eps_rel = float("inf") if dst_perf > src_perf else 0.0

		if epsilon_mode == "relative":
			allowed = src_perf * (1.0 + epsilon)
		else:
			allowed = src_perf + epsilon

		if allowed < dst_perf:
			violations.append(
				{
					"src": src,
					"dst": dst,
					"src_perf": src_perf,
					"dst_perf": dst_perf,
					"gap": dst_perf - src_perf,
					"required_epsilon_absolute": required_eps_abs,
					"required_epsilon_relative": required_eps_rel,
				}
			)

	return violations, missing


def parse_edges_from_dot(path: str) -> List[Edge]:
	edges = []
	edge_pattern = re.compile(r"^\s*([A-Za-z0-9_]+)\s*->\s*([A-Za-z0-9_]+)")

	with open(path, "r", encoding="utf-8") as f:
		for line in f:
			m = edge_pattern.match(line)
			if m:
				edges.append((m.group(1), m.group(2)))
	return edges


def parse_edges_from_csv(path: str) -> List[Edge]:
	edges = []
	with open(path, "r", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		if reader.fieldnames and "src" in reader.fieldnames and "dst" in reader.fieldnames:
			for row in reader:
				edges.append((row["src"].strip(), row["dst"].strip()))
			return edges

	with open(path, "r", encoding="utf-8") as f:
		reader = csv.reader(f)
		for row in reader:
			if len(row) < 2:
				continue
			edges.append((row[0].strip(), row[1].strip()))
	return edges


def parse_edges_from_json(path: str) -> List[Edge]:
	with open(path, "r", encoding="utf-8") as f:
		payload = json.load(f)

	if isinstance(payload, dict) and "edges" in payload:
		payload = payload["edges"]

	edges = []
	if isinstance(payload, list):
		for item in payload:
			if isinstance(item, dict) and "src" in item and "dst" in item:
				edges.append((str(item["src"]), str(item["dst"])))
			elif isinstance(item, (list, tuple)) and len(item) >= 2:
				edges.append((str(item[0]), str(item[1])))
	return edges


def parse_edges(path: str) -> List[Edge]:
	ext = os.path.splitext(path)[1].lower()
	if ext == ".dot":
		return parse_edges_from_dot(path)
	if ext == ".csv":
		return parse_edges_from_csv(path)
	if ext == ".json":
		return parse_edges_from_json(path)
	raise ValueError(f"Unsupported edge file type: {ext}")


def parse_perf_from_json(path: str) -> Dict[str, float]:
	with open(path, "r", encoding="utf-8") as f:
		payload = json.load(f)

	if isinstance(payload, dict) and "performance" in payload and isinstance(payload["performance"], dict):
		payload = payload["performance"]

	if not isinstance(payload, dict):
		raise ValueError("Performance JSON must be an object mapping node->value")

	return {str(k): float(v) for k, v in payload.items()}


def _pick_column(fieldnames: Iterable[str], candidates: Sequence[str]) -> str:
	lowered = {name.lower(): name for name in fieldnames}
	for c in candidates:
		if c.lower() in lowered:
			return lowered[c.lower()]
	return ""


def parse_perf_from_csv(path: str) -> Dict[str, float]:
	with open(path, "r", encoding="utf-8") as f:
		reader = csv.DictReader(f)
		if not reader.fieldnames:
			raise ValueError("Performance CSV needs a header")

		node_col = _pick_column(reader.fieldnames, ("node", "id", "config", "taskid", "name"))
		value_col = _pick_column(reader.fieldnames, ("perf", "performance", "value", "throughput"))

		if not node_col or not value_col:
			raise ValueError(
				"Performance CSV must contain node/id/config column and perf/performance/value column"
			)

		perf = {}
		for row in reader:
			node = row[node_col].strip()
			if not node:
				continue
			perf[node] = float(row[value_col])
	return perf


def parse_performance(path: str) -> Dict[str, float]:
	ext = os.path.splitext(path)[1].lower()
	if ext == ".json":
		return parse_perf_from_json(path)
	if ext == ".csv":
		return parse_perf_from_csv(path)
	raise ValueError(f"Unsupported performance file type: {ext}")


def parse_args() -> argparse.Namespace:
	parser = argparse.ArgumentParser(
		description=(
			"Validate hypothesis on edges A->B with configurable epsilon mode and report outputs"
		)
	)
	parser.add_argument("--edges", required=True, help="Edge file: .dot/.csv/.json")
	parser.add_argument("--perf", required=True, help="Performance file: .csv/.json")
	parser.add_argument("--epsilon", type=float, default=0.0, help="Non-negative tolerance")
	parser.add_argument(
		"--epsilon-mode",
		choices=("absolute", "relative"),
		default="absolute",
		help="absolute: src+eps>=dst, relative: src*(1+eps)>=dst",
	)
	parser.add_argument(
		"--missing-policy",
		choices=("warn", "fail", "ignore"),
		default="warn",
		help="How to handle edges with missing performance values",
	)
	parser.add_argument(
		"--keep-duplicates",
		action="store_true",
		help="Keep duplicate edges; default behavior deduplicates edges",
	)
	parser.add_argument(
		"--top-k",
		type=int,
		default=20,
		help="How many missing/violating edges to print",
	)
	parser.add_argument("--out-json", default="", help="Optional path to write a JSON summary report")
	parser.add_argument(
		"--out-violations-csv",
		default="",
		help="Optional path to write violating edges as CSV",
	)
	parser.add_argument(
		"--out-missing-csv",
		default="",
		help="Optional path to write missing-performance edges as CSV",
	)
	return parser.parse_args()


def _ensure_parent_dir(path: str) -> None:
	if not path:
		return
	parent = os.path.dirname(os.path.abspath(path))
	if parent:
		os.makedirs(parent, exist_ok=True)


def write_violations_csv(path: str, violations: List[dict]) -> None:
	if not path:
		return
	_ensure_parent_dir(path)
	fields = [
		"src",
		"dst",
		"src_perf",
		"dst_perf",
		"gap",
		"required_epsilon_absolute",
		"required_epsilon_relative",
	]
	with open(path, "w", encoding="utf-8", newline="") as f:
		writer = csv.DictWriter(f, fieldnames=fields)
		writer.writeheader()
		for row in violations:
			writer.writerow({k: row.get(k, "") for k in fields})


def write_missing_csv(path: str, missing: List[Edge]) -> None:
	if not path:
		return
	_ensure_parent_dir(path)
	with open(path, "w", encoding="utf-8", newline="") as f:
		writer = csv.writer(f)
		writer.writerow(["src", "dst"])
		writer.writerows(missing)


def write_json_summary(
	path: str,
	*,
	total_edges: int,
	unique_edges: int,
	performance_entries: int,
	epsilon: float,
	epsilon_mode: str,
	missing_policy: str,
	violations: List[dict],
	missing: List[Edge],
	max_gap: float,
	mean_gap: Optional[float],
) -> None:
	if not path:
		return
	_ensure_parent_dir(path)
	payload = {
		"total_edges_input": total_edges,
		"unique_edges": unique_edges,
		"performance_entries": performance_entries,
		"epsilon": epsilon,
		"epsilon_mode": epsilon_mode,
		"missing_policy": missing_policy,
		"missing_count": len(missing),
		"violation_count": len(violations),
		"max_gap": max_gap,
		"mean_gap": mean_gap,
		"missing": [{"src": s, "dst": d} for s, d in missing],
		"violations": violations,
	}
	with open(path, "w", encoding="utf-8") as f:
		json.dump(payload, f, ensure_ascii=True, indent=2)


def main() -> None:
	args = parse_args()
	if args.epsilon < 0:
		raise SystemExit("--epsilon must be non-negative")
	if args.top_k <= 0:
		raise SystemExit("--top-k must be positive")

	edges_raw = parse_edges(args.edges)
	if args.keep_duplicates:
		edges = edges_raw
	else:
		# Preserve first-seen order while removing duplicates.
		edges = list(dict.fromkeys(edges_raw))

	perf = parse_performance(args.perf)
	violations, missing = check_edge_hypothesis(
		edges,
		perf,
		epsilon=args.epsilon,
		epsilon_mode=args.epsilon_mode,
	)
	violations_sorted = sorted(violations, key=lambda x: x["gap"], reverse=True)
	gaps = [v["gap"] for v in violations_sorted]
	max_gap = max(gaps) if gaps else 0.0
	mean_gap = mean(gaps) if gaps else None

	write_violations_csv(args.out_violations_csv, violations_sorted)
	write_missing_csv(args.out_missing_csv, missing)
	write_json_summary(
		args.out_json,
		total_edges=len(edges_raw),
		unique_edges=len(edges),
		performance_entries=len(perf),
		epsilon=args.epsilon,
		epsilon_mode=args.epsilon_mode,
		missing_policy=args.missing_policy,
		violations=violations_sorted,
		missing=missing,
		max_gap=max_gap,
		mean_gap=mean_gap,
	)

	print(f"Total edges input: {len(edges_raw)}")
	print(f"Unique edges used: {len(edges)}")
	print(f"Performance entries: {len(perf)}")
	print(f"Epsilon mode: {args.epsilon_mode}")
	print(f"Epsilon value: {args.epsilon}")
	print(f"Missing policy: {args.missing_policy}")
	print(f"Missing perf edges: {len(missing)}")
	print(f"Violations: {len(violations_sorted)}")
	if violations_sorted:
		print(f"Max gap: {max_gap:.6f}")
		if mean_gap is not None:
			print(f"Mean gap: {mean_gap:.6f}")

	if args.out_json:
		print(f"JSON summary written: {args.out_json}")
	if args.out_violations_csv:
		print(f"Violations CSV written: {args.out_violations_csv}")
	if args.out_missing_csv:
		print(f"Missing CSV written: {args.out_missing_csv}")

	if missing and args.missing_policy != "ignore":
		print(f"\nEdges missing performance values (top {args.top_k}):")
		for src, dst in missing[: args.top_k]:
			print(f"  {src} -> {dst}")

	if violations_sorted:
		print(f"\nViolating edges by gap descending (top {args.top_k}):")
		for v in violations_sorted[: args.top_k]:
			print(
				f"  {v['src']} -> {v['dst']}: "
				f"src={v['src_perf']:.6f}, dst={v['dst_perf']:.6f}, gap={v['gap']:.6f}, "
				f"need_abs_eps={v['required_epsilon_absolute']:.6f}, "
				f"need_rel_eps={v['required_epsilon_relative']:.6f}"
			)
		raise SystemExit(2)

	if missing and args.missing_policy == "fail":
		print("\nMissing performance values are treated as failure by --missing-policy=fail")
		raise SystemExit(3)

	print("\nHypothesis holds for all edges with available performance values.")


if __name__ == "__main__":
	main()
