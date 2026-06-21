"""AGF benchmark and lift measurement.

AGF (public consensus) is the standard against which any model claim must
be measured in Turkish pari-mutuel. This module produces honest
side-by-side metrics:
  - AGF-only top1/top4 hit rates
  - Model-only top1/top4 hit rates
  - Blended top1/top4 hit rates
  - Lift by race-class / breed / hippodrome / field-size / AGF-entropy

Language safety: do NOT label any rumor/drift as "insider". Use
`sharp_money_candidate`, `live_market_move`, `agf_drift_signal`.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping


SAFE_TERMS = {
    "insider": "sharp_money_candidate",
    "insider_signal": "agf_drift_signal",
    "smart_money": "sharp_money_candidate",
    "live_move": "live_market_move",
}


def safe_label(term: str) -> str:
    return SAFE_TERMS.get(term.lower(), term)


@dataclass
class BenchmarkRow:
    n_races: int = 0
    agf_top1_top4_hit: float = 0.0
    agf_top4_set_hit: float = 0.0
    model_top1_top4_hit: float = 0.0
    model_top4_set_hit: float = 0.0
    blended_top1_top4_hit: float = 0.0
    blended_top4_set_hit: float = 0.0
    lift_model_over_agf: float = 0.0
    note: str = ""


def benchmark(
    races: Iterable[Mapping],
) -> dict[str, BenchmarkRow]:
    """Each race dict must have:
      - rows: list of horse dicts (horse_no, mp, agf, model_rank)
      - observed_top4: set/list of horse_nos
      - segment: optional dict of segment labels
    Returns dict keyed by 'overall' + each segment label.
    """
    buckets: dict[str, list[Mapping]] = {"overall": []}
    for race in races:
        buckets["overall"].append(race)
        seg = race.get("segment", {}) or {}
        for k, v in seg.items():
            key = f"{k}={v}"
            buckets.setdefault(key, []).append(race)

    out: dict[str, BenchmarkRow] = {}
    for label, race_list in buckets.items():
        out[label] = _bench_bucket(race_list)
    return out


def _bench_bucket(races: list[Mapping]) -> BenchmarkRow:
    if not races:
        return BenchmarkRow(note="no races")
    agf_top1_in_top4 = 0
    model_top1_in_top4 = 0
    agf_set_hit = 0
    model_set_hit = 0
    blended_top1_in_top4 = 0
    blended_set_hit = 0
    processed = 0

    for race in races:
        rows = race.get("rows", [])
        observed = set(int(h) for h in race.get("observed_top4", []))
        if not rows or not observed:
            continue
        processed += 1
        agf_sorted = sorted(rows, key=lambda r: r.get("agf", 0.0) or 0.0, reverse=True)
        model_sorted = sorted(rows, key=lambda r: r.get("mp", 0.0) or 0.0, reverse=True)
        # blend rank: avg position
        def blend_score(r):
            a = (r.get("agf", 0.0) or 0.0) / 100.0
            m = r.get("mp", 0.0) or 0.0
            return 0.55 * m + 0.45 * a
        blended_sorted = sorted(rows, key=blend_score, reverse=True)

        agf_top1 = int(agf_sorted[0]["horse_no"])
        model_top1 = int(model_sorted[0]["horse_no"])
        blend_top1 = int(blended_sorted[0]["horse_no"])

        if agf_top1 in observed:
            agf_top1_in_top4 += 1
        if model_top1 in observed:
            model_top1_in_top4 += 1
        if blend_top1 in observed:
            blended_top1_in_top4 += 1

        agf_set = set(int(r["horse_no"]) for r in agf_sorted[:4])
        model_set = set(int(r["horse_no"]) for r in model_sorted[:4])
        blend_set = set(int(r["horse_no"]) for r in blended_sorted[:4])
        if agf_set == observed:
            agf_set_hit += 1
        if model_set == observed:
            model_set_hit += 1
        if blend_set == observed:
            blended_set_hit += 1

    # FIX (audit 2026-06-21): denominator was `len(races)` which counted
    # skipped races (empty rows / empty observed) as failures. Use the
    # actual processed count instead.
    n_eff = processed or 1
    return BenchmarkRow(
        n_races=processed,
        agf_top1_top4_hit=agf_top1_in_top4 / n_eff,
        agf_top4_set_hit=agf_set_hit / n_eff,
        model_top1_top4_hit=model_top1_in_top4 / n_eff,
        model_top4_set_hit=model_set_hit / n_eff,
        blended_top1_top4_hit=blended_top1_in_top4 / n_eff,
        blended_top4_set_hit=blended_set_hit / n_eff,
        lift_model_over_agf=(model_top1_in_top4 - agf_top1_in_top4) / n_eff,
        note=(f"skipped {len(races) - processed} empty race(s)"
              if processed < len(races) else ""),
    )
