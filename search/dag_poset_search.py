#!/usr/bin/env python3

import random
from dataclasses import dataclass
from typing import Dict, List, Optional, Set, Tuple


@dataclass
class SearchTraceStep:
    step: int
    candidate_size_before: int
    centroid: str
    a_count: int
    d_count: int
    queried_value: float
    feasible: bool
    pruned_count: int
    candidate_size_after: int


@dataclass
class SearchResult:
    final_answers: List[str]
    queried_nodes: List[str]
    query_count: int
    trace: List[SearchTraceStep]
    results_raw: List[str]


class DagPosetSearch:
    def __init__(self, nodes: List[str], edges: List[Tuple[str, str]]):
        if not nodes:
            raise ValueError("nodes cannot be empty")

        self.nodes = sorted(set(nodes))
        self.n = len(self.nodes)
        self.node_to_idx = {n: i for i, n in enumerate(self.nodes)}

        self.succ: List[Set[int]] = [set() for _ in range(self.n)]
        self.pred: List[Set[int]] = [set() for _ in range(self.n)]

        for src, dst in edges:
            if src not in self.node_to_idx or dst not in self.node_to_idx:
                continue
            u = self.node_to_idx[src]
            v = self.node_to_idx[dst]
            if u == v:
                continue
            self.succ[u].add(v)
            self.pred[v].add(u)

        self.topo = self._topological_order_or_raise()
        self.desc_bits = self._build_desc_bits()
        self.anc_bits = self._build_anc_bits()

    def _topological_order_or_raise(self) -> List[int]:
        indeg = [len(self.pred[i]) for i in range(self.n)]
        queue = [i for i in range(self.n) if indeg[i] == 0]
        order: List[int] = []
        qi = 0
        while qi < len(queue):
            u = queue[qi]
            qi += 1
            order.append(u)
            for v in sorted(self.succ[u]):
                indeg[v] -= 1
                if indeg[v] == 0:
                    queue.append(v)
        if len(order) != self.n:
            raise ValueError("input graph is not a DAG")
        return order

    def _build_desc_bits(self) -> List[int]:
        bits = [0] * self.n
        for u in reversed(self.topo):
            b = 1 << u
            for v in self.succ[u]:
                b |= bits[v]
            bits[u] = b
        return bits

    def _build_anc_bits(self) -> List[int]:
        bits = [0] * self.n
        for u in self.topo:
            b = 1 << u
            for p in self.pred[u]:
                b |= bits[p]
            bits[u] = b
        return bits

    @staticmethod
    def _popcount(x: int) -> int:
        return bin(x).count("1")

    def _mask_to_names(self, mask: int) -> List[str]:
        out = []
        for i, name in enumerate(self.nodes):
            if mask & (1 << i):
                out.append(name)
        return out

    def _find_centroid(self, candidate_mask: int) -> Tuple[int, int, int]:
        best_idx = -1
        best_score = -1
        best_balance = 10**18
        best_name = ""
        best_a = 0
        best_d = 0

        for i, name in enumerate(self.nodes):
            if not (candidate_mask & (1 << i)):
                continue
            a = self._popcount(self.anc_bits[i] & candidate_mask)
            d = self._popcount(self.desc_bits[i] & candidate_mask)
            score = min(a, d)
            balance = abs(a - d)

            if (
                score > best_score
                or (score == best_score and balance < best_balance)
                or (score == best_score and balance == best_balance and name < best_name)
            ):
                best_idx = i
                best_score = score
                best_balance = balance
                best_name = name
                best_a = a
                best_d = d

        if best_idx < 0:
            raise RuntimeError("no centroid in non-empty candidate set")
        return best_idx, best_a, best_d

    def _find_expected_prune(self, candidate_mask: int, p_feasible: float) -> Tuple[int, int, int]:
        best_idx = -1
        best_expected = -1.0
        best_balance = 10**18
        best_name = ""
        best_a = 0
        best_d = 0

        for i, name in enumerate(self.nodes):
            if not (candidate_mask & (1 << i)):
                continue
            a = self._popcount(self.anc_bits[i] & candidate_mask)
            d = self._popcount(self.desc_bits[i] & candidate_mask)
            expected = p_feasible * a + (1.0 - p_feasible) * d
            balance = abs(a - d)

            if (
                expected > best_expected
                or (abs(expected - best_expected) < 1e-12 and balance < best_balance)
                or (abs(expected - best_expected) < 1e-12 and balance == best_balance and name < best_name)
            ):
                best_idx = i
                best_expected = expected
                best_balance = balance
                best_name = name
                best_a = a
                best_d = d

        if best_idx < 0:
            raise RuntimeError("no candidate in non-empty candidate set")
        return best_idx, best_a, best_d

    def _find_first_candidate(self, candidate_mask: int) -> Tuple[int, int, int]:
        for i, _ in enumerate(self.nodes):
            if candidate_mask & (1 << i):
                a = self._popcount(self.anc_bits[i] & candidate_mask)
                d = self._popcount(self.desc_bits[i] & candidate_mask)
                return i, a, d
        raise RuntimeError("no candidate in non-empty candidate set")

    def _find_worst_split(self, candidate_mask: int) -> Tuple[int, int, int]:
        worst_idx = -1
        worst_score = 10**18
        worst_balance = -1
        worst_name = ""
        worst_a = 0
        worst_d = 0

        for i, name in enumerate(self.nodes):
            if not (candidate_mask & (1 << i)):
                continue
            a = self._popcount(self.anc_bits[i] & candidate_mask)
            d = self._popcount(self.desc_bits[i] & candidate_mask)
            score = min(a, d)
            balance = abs(a - d)

            if (
                score < worst_score
                or (score == worst_score and balance > worst_balance)
                or (score == worst_score and balance == worst_balance and (worst_name == "" or name < worst_name))
            ):
                worst_idx = i
                worst_score = score
                worst_balance = balance
                worst_name = name
                worst_a = a
                worst_d = d

        if worst_idx < 0:
            raise RuntimeError("no candidate in non-empty candidate set")
        return worst_idx, worst_a, worst_d

    def _find_random_candidate(self, candidate_mask: int, rng: random.Random) -> Tuple[int, int, int]:
        candidates = [i for i in range(self.n) if candidate_mask & (1 << i)]
        if not candidates:
            raise RuntimeError("no candidate in non-empty candidate set")
        i = rng.choice(candidates)
        a = self._popcount(self.anc_bits[i] & candidate_mask)
        d = self._popcount(self.desc_bits[i] & candidate_mask)
        return i, a, d

    def run_single_source_search(
        self,
        g_values: Dict[str, float],
        threshold: float,
        source: Optional[str] = None,
        strategy: str = "balanced",
        random_seed: int = 0,
    ) -> SearchResult:
        missing = [n for n in self.nodes if n not in g_values]
        if missing:
            raise ValueError(f"missing g values for nodes: {missing[:5]}")

        queried: Dict[int, float] = {}
        rng = random.Random(random_seed)
        observed_count = 0
        observed_feasible = 0

        def query(i: int) -> float:
            if i not in queried:
                queried[i] = float(g_values[self.nodes[i]])
            return queried[i]

        candidate = (1 << self.n) - 1
        results_mask = 0
        trace: List[SearchTraceStep] = []

        if source is not None:
            if source not in self.node_to_idx:
                raise ValueError(f"source not found: {source}")
            s = self.node_to_idx[source]
            gv = query(s)
            if gv < threshold:
                return SearchResult(
                    final_answers=[],
                    queried_nodes=[self.nodes[s]],
                    query_count=1,
                    trace=[],
                    results_raw=[],
                )

        step = 0
        while candidate:
            step += 1
            before = self._popcount(candidate)
            if strategy == "balanced":
                # Use a smoothed feasible-rate estimate to maximize expected pruning.
                p_feasible = (observed_feasible + 1.0) / (observed_count + 2.0)
                c_idx, a_count, d_count = self._find_expected_prune(candidate, p_feasible)
            elif strategy == "worst":
                c_idx, a_count, d_count = self._find_worst_split(candidate)
            elif strategy == "first":
                c_idx, a_count, d_count = self._find_first_candidate(candidate)
            elif strategy == "random":
                c_idx, a_count, d_count = self._find_random_candidate(candidate, rng)
            else:
                raise ValueError(f"unknown strategy: {strategy}")
            g = query(c_idx)

            if g >= threshold:
                results_mask |= 1 << c_idx
                remove_mask = self.anc_bits[c_idx]
                feasible = True
                observed_feasible += 1
            else:
                remove_mask = self.desc_bits[c_idx]
                feasible = False
            observed_count += 1

            remove_mask &= candidate
            pruned = self._popcount(remove_mask)
            candidate &= ~remove_mask
            after = self._popcount(candidate)

            trace.append(
                SearchTraceStep(
                    step=step,
                    candidate_size_before=before,
                    centroid=self.nodes[c_idx],
                    a_count=a_count,
                    d_count=d_count,
                    queried_value=g,
                    feasible=feasible,
                    pruned_count=pruned,
                    candidate_size_after=after,
                )
            )

        # Final_Ans keeps minimal f-equivalent in Results by removing nodes that can reach others.
        final_mask = results_mask
        for i in range(self.n):
            if not (results_mask & (1 << i)):
                continue
            reach_other = (self.desc_bits[i] & results_mask) & ~(1 << i)
            if reach_other:
                final_mask &= ~(1 << i)

        queried_nodes = [self.nodes[i] for i in sorted(queried.keys(), key=lambda x: self.nodes[x])]
        return SearchResult(
            final_answers=self._mask_to_names(final_mask),
            queried_nodes=queried_nodes,
            query_count=len(queried),
            trace=trace,
            results_raw=self._mask_to_names(results_mask),
        )
