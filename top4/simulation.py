"""Plackett-Luce / Monte-Carlo race simulation.

Given per-horse utility scores (e.g., calibrated p_win or mp), sample full
ordered finishes and derive empirical P(top-k) and candidate-set coverage.

This module is intentionally dependency-free (no numpy required) so it
runs in production. For audit/offline we expose `simulate_race` with a
configurable iteration count; production uses `n_iter=2000` by default,
backtest can crank to 50k.
"""
from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


@dataclass
class SimResult:
    n_iter: int
    p_win: dict[int, float]
    p_top2: dict[int, float]
    p_top3: dict[int, float]
    p_top4: dict[int, float]
    most_frequent_top4_sets: list[tuple[frozenset[int], int]]
    method: str


def _utilities(rows: list[Mapping], source: str) -> dict[int, float]:
    util: dict[int, float] = {}
    for r in rows:
        h = int(r["horse_no"])
        if source == "p_win_cal" and r.get("p_win_cal") is not None:
            val = max(1e-6, float(r["p_win_cal"]))
        elif source == "mp":
            val = max(1e-6, float(r.get("mp", 0.0)))
            if val <= 0:
                val = 1e-6
        else:
            val = max(1e-6, float(r.get("mp", 0.0)))
        util[h] = val
    return util


def simulate_race(
    rows: Iterable[Mapping],
    n_iter: int = 2000,
    seed: int = 42,
    source: str = "p_win_cal",
) -> SimResult:
    rows = list(rows)
    if not rows:
        return SimResult(0, {}, {}, {}, {}, [], "empty")

    util = _utilities(rows, source)
    horses = list(util.keys())
    if not horses:
        return SimResult(0, {}, {}, {}, {}, [], "empty")

    rng = random.Random(seed)
    count_top: dict[int, dict[int, int]] = {k: {h: 0 for h in horses} for k in (1, 2, 3, 4)}
    set_counts: dict[frozenset[int], int] = {}

    for _ in range(n_iter):
        # Plackett-Luce: sequentially sample without replacement, weights = util
        remaining = dict(util)
        order: list[int] = []
        for _pos in range(min(4, len(horses))):
            total = sum(remaining.values())
            if total <= 0:
                break
            r = rng.random() * total
            acc = 0.0
            pick = None
            for h, w in remaining.items():
                acc += w
                if r <= acc:
                    pick = h
                    break
            if pick is None:
                pick = next(iter(remaining))
            order.append(pick)
            del remaining[pick]
        for pos, h in enumerate(order, start=1):
            for k in (1, 2, 3, 4):
                if pos <= k:
                    count_top[k][h] += 1
        if len(order) >= 4:
            key = frozenset(order[:4])
            set_counts[key] = set_counts.get(key, 0) + 1

    def _norm(c: dict[int, int]) -> dict[int, float]:
        return {h: v / n_iter for h, v in c.items()}

    top_sets = sorted(set_counts.items(), key=lambda kv: kv[1], reverse=True)[:10]

    return SimResult(
        n_iter=n_iter,
        p_win=_norm(count_top[1]),
        p_top2=_norm(count_top[2]),
        p_top3=_norm(count_top[3]),
        p_top4=_norm(count_top[4]),
        most_frequent_top4_sets=top_sets,
        method=f"plackett_luce({source})",
    )


def set_coverage_probability(
    rows: Iterable[Mapping], candidate_set: set[int], n_iter: int = 2000,
    source: str = "p_win_cal",
) -> dict:
    """Probability that the simulated top-4 is a subset of `candidate_set`.
    Also returns expected number of top-4 finishers within the set."""
    sim = simulate_race(rows, n_iter=n_iter, source=source)
    if sim.n_iter == 0:
        return {"p_full_coverage": 0.0, "expected_hits": 0.0, "n_iter": 0}
    # we lost full ordering, recompute from set frequency table
    full = 0
    expected = 0.0
    for s, cnt in sim.most_frequent_top4_sets:
        contained = len(s & candidate_set)
        if contained == 4:
            full += cnt
        expected += contained * cnt
    # adjust expected to be averaged over n_iter (set table is truncated to top-10)
    return {
        "p_full_coverage_approx": full / sim.n_iter,
        "expected_hits_approx": expected / sim.n_iter,
        "n_iter": sim.n_iter,
        "warning": "expected_hits is approximate (top-10 sets only)",
    }
