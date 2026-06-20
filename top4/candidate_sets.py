"""Candidate-set construction and coverage evaluation.

For Top-4 betting, the actionable question is not "which one horse" but
"how many horses must I include to capture the top-4 with high probability,
and at what cost?"

This module proposes candidate sets of varying size and reports expected
coverage given calibrated probabilities. The simulation-based coverage
estimate lives in `top4.simulation`. Here we expose simple, fast
constructors and offline evaluators.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


@dataclass
class CandidateSet:
    size: int
    horse_nos: list[int]
    method: str
    expected_top4_coverage: Optional[float] = None
    note: str = ""


def _rank_by(rows: list[Mapping], key: str) -> list[Mapping]:
    return sorted(rows, key=lambda r: r.get(key, 0.0) or 0.0, reverse=True)


def build_set_by_mp(rows: Iterable[Mapping], size: int) -> CandidateSet:
    rows = list(rows)
    picked = _rank_by(rows, "mp")[:size]
    return CandidateSet(
        size=size,
        horse_nos=[int(r["horse_no"]) for r in picked],
        method="rank_mp",
    )


def build_set_by_p_top4(rows: Iterable[Mapping], size: int) -> CandidateSet:
    """Rank by p_top4_cal if present, else fall back to mp."""
    rows = list(rows)
    if any(r.get("p_top4_cal") is not None for r in rows):
        picked = _rank_by(rows, "p_top4_cal")[:size]
        method = "rank_p_top4_cal"
    else:
        picked = _rank_by(rows, "mp")[:size]
        method = "rank_mp_fallback"
    return CandidateSet(
        size=size,
        horse_nos=[int(r["horse_no"]) for r in picked],
        method=method,
    )


def build_set_blended(rows: Iterable[Mapping], size: int, w_model: float = 0.65) -> CandidateSet:
    """Blend p_top4_cal (or mp) with AGF prior. Requires `agf` in rows."""
    rows = list(rows)
    enriched: list[tuple[float, Mapping]] = []
    for r in rows:
        p = r.get("p_top4_cal")
        if p is None:
            p = r.get("mp", 0.0)
        agf_prior = (r.get("agf", 0.0) or 0.0) / 100.0
        score = w_model * (p or 0.0) + (1.0 - w_model) * agf_prior
        enriched.append((score, r))
    enriched.sort(key=lambda kv: kv[0], reverse=True)
    picked = [r for _s, r in enriched[:size]]
    return CandidateSet(
        size=size,
        horse_nos=[int(r["horse_no"]) for r in picked],
        method=f"blend_model_agf_w{w_model:.2f}",
    )


def coverage_required_for_target(
    rows: Iterable[Mapping],
    target: float = 0.80,
    max_size: int = 12,
    method: str = "p_top4",
) -> int:
    """Greedily extend a candidate set until estimated expected number of
    top-4 finishers contained reaches `target * 4`. Uses sum of p_top4_cal
    as an additive approximation (true coverage requires simulation).
    """
    rows = list(rows)
    if not rows:
        return 0
    if method == "p_top4":
        scored = _rank_by(rows, "p_top4_cal")
    else:
        scored = _rank_by(rows, "mp")
    target_mass = 4.0 * target
    mass = 0.0
    for n, r in enumerate(scored, start=1):
        p = r.get("p_top4_cal")
        if p is None:
            # cannot estimate -> fall back to assume 4/field
            p = 4.0 / max(1, len(rows))
        mass += p
        if mass >= target_mass:
            return n
        if n >= max_size:
            return n
    return min(len(rows), max_size)


def coverage_from_observed(set_horses: set[int], observed_top4: set[int]) -> dict:
    """Offline backtest helper: report how many of the actual top-4 were
    inside the proposed set."""
    hit = len(set_horses & observed_top4)
    return {
        "set_size": len(set_horses),
        "hit": hit,
        "captured_full": hit == 4,
        "captured_at_least_3": hit >= 3,
        "captured_at_least_2": hit >= 2,
        "captured_at_least_1": hit >= 1,
    }
