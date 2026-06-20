"""Race-level uncertainty / no-bet gate.

Produces one of: HIGH, MEDIUM, LOW, CHAOS, NO_BET.

Inputs:
  - field_size
  - calibrated probabilities (list of p_top4_cal)
  - AGF distribution (entropy proxy)
  - model top1-top2 gap (mp_1 - mp_2)
  - required set size for target coverage
  - segment notes (e.g., very rare race class)
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

LEVEL_HIGH = "HIGH"
LEVEL_MEDIUM = "MEDIUM"
LEVEL_LOW = "LOW"
LEVEL_CHAOS = "CHAOS"
LEVEL_NO_BET = "NO_BET"


@dataclass
class UncertaintyReport:
    level: str
    reasons: list[str]
    required_set_size: int
    field_size: int
    entropy: Optional[float]
    top_gap: Optional[float]


def _entropy(probs: Iterable[float]) -> Optional[float]:
    probs = [p for p in probs if p is not None and p > 0]
    if not probs:
        return None
    s = sum(probs)
    if s <= 0:
        return None
    norm = [p / s for p in probs]
    return -sum(p * math.log(p) for p in norm if p > 0)


def evaluate(
    rows: Iterable[Mapping],
    required_set_size: int,
) -> UncertaintyReport:
    rows = list(rows)
    n = len(rows)
    reasons: list[str] = []

    mp_sorted = sorted((r.get("mp", 0.0) for r in rows), reverse=True)
    top_gap = (mp_sorted[0] - mp_sorted[1]) if len(mp_sorted) >= 2 else None

    agf_values = [r.get("agf") for r in rows if r.get("agf") is not None]
    ent = _entropy(agf_values) if agf_values else None

    # Decide
    if n <= 0:
        return UncertaintyReport(LEVEL_NO_BET, ["empty race"], 0, n, None, None)

    if n >= 14 and required_set_size >= max(8, int(0.6 * n)):
        reasons.append(f"need {required_set_size}/{n} horses for coverage")
        return UncertaintyReport(LEVEL_NO_BET, reasons, required_set_size, n, ent, top_gap)

    if n >= 16:
        reasons.append(f"large field ({n})")
        level = LEVEL_CHAOS
    elif required_set_size >= 9:
        reasons.append(f"required set {required_set_size} >= 9")
        level = LEVEL_CHAOS
    elif required_set_size <= 4 and top_gap is not None and top_gap >= 0.05:
        reasons.append(f"compact set ({required_set_size}) + strong top gap {top_gap:.3f}")
        level = LEVEL_HIGH
    elif required_set_size <= 5:
        level = LEVEL_MEDIUM
    elif required_set_size <= 7:
        level = LEVEL_LOW
    else:
        level = LEVEL_CHAOS

    # Downgrade if entropy is extremely flat (public has no opinion)
    if ent is not None and ent > math.log(max(2, n)) - 0.1:
        reasons.append(f"flat AGF (entropy {ent:.2f})")
        if level == LEVEL_HIGH:
            level = LEVEL_MEDIUM
        elif level == LEVEL_MEDIUM:
            level = LEVEL_LOW

    return UncertaintyReport(level, reasons, required_set_size, n, ent, top_gap)
