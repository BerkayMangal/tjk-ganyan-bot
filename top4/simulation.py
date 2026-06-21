"""Plackett-Luce / Monte-Carlo race simulation.

Given per-horse utility scores (e.g., calibrated p_win or mp), sample full
ordered finishes and derive empirical P(top-k) and candidate-set coverage.

This module is intentionally dependency-free (no numpy required) so it
runs in production. For audit/offline we expose `simulate_race` with a
configurable iteration count; production uses `n_iter=2000` by default,
backtest can crank to 50k.
"""
from __future__ import annotations

import random
from dataclasses import dataclass
from typing import Iterable, Mapping


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
    source: str = "p_win_cal", seed: int = 42,
) -> dict:
    """Probability that the simulated top-4 is a subset of `candidate_set`.
    Also returns expected number of top-4 finishers within the set.

    FIX (audit 2026-06-21): the previous implementation read from
    simulate_race().most_frequent_top4_sets, which is truncated to the
    top-10 most-frequent sets. For a 2000-iter run with 50+ unique
    top-4 sets, that means ~75% of the iterations were silently
    dropped from the coverage estimate. We now run the Plackett-Luce
    sampler inline and count subset membership on EVERY iteration.

    Backwards-compatible keys (`*_approx`) are kept so existing
    callers continue to work.
    """
    rows = list(rows)
    if not rows:
        return {"p_full_coverage": 0.0, "p_full_coverage_approx": 0.0,
                "expected_hits": 0.0, "expected_hits_approx": 0.0,
                "n_iter": 0}
    util = _utilities(rows, source)
    horses = list(util.keys())
    if not horses:
        return {"p_full_coverage": 0.0, "p_full_coverage_approx": 0.0,
                "expected_hits": 0.0, "expected_hits_approx": 0.0,
                "n_iter": 0}
    rng = random.Random(seed)
    full_count = 0
    total_hits = 0
    eligible_iters = 0
    for _ in range(n_iter):
        remaining = dict(util)
        order: list[int] = []
        for _pos in range(min(4, len(horses))):
            total_w = sum(remaining.values())
            if total_w <= 0:
                break
            r = rng.random() * total_w
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
        if len(order) >= min(4, len(horses)):
            eligible_iters += 1
            top4 = set(order[:4])
            contained = len(top4 & candidate_set)
            total_hits += contained
            if contained == min(4, len(horses)):
                full_count += 1
    n_eff = eligible_iters or n_iter
    p_full = full_count / n_eff
    exp_hits = total_hits / n_eff
    return {
        "p_full_coverage": p_full,
        "p_full_coverage_approx": p_full,
        "expected_hits": exp_hits,
        "expected_hits_approx": exp_hits,
        "n_iter": n_eff,
    }
