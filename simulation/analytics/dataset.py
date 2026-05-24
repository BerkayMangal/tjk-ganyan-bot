"""Phase 5.8 — paylaşımlı zenginleştirilmiş analiz dataset'i.

tr_bias_analysis._build_enriched (rich outcome + AGF, ayak↔koşu Jaccard) → satırlar:
{at_no, agf_implied, won, date, hip(normed), age, weight, jockey, name, distance}.
+ jokey-skill (Phase 5.5 H2: residual=won−agf) ve yardımcılar.

ROI proxy = mean(won/agf_implied) − 1 (implied-odds flat bet; ⚠ PROXY — gerçek odds/takeout yok).
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from simulation.tr_bias_analysis import _build_enriched  # noqa: E402

# Bölge grupları (Berkay hipotezi A; kontrol B/C). _norm FOLD'lu (İıÇçĞğÖöŞşÜü→iiccggoossuu).
REGION_A = {"elazig", "sanliurfa", "diyarbakir"}   # küçük pool, hipotez
REGION_B = {"istanbul", "bursa", "ankara"}         # büyük, denetim sıkı
REGION_C = {"adana", "izmir", "kocaeli"}           # orta


def build():
    return _build_enriched()


def region_of(hip_normed: str) -> str:
    h = hip_normed
    if h in REGION_A:
        return "A_small"
    if h in REGION_B:
        return "B_big"
    if h in REGION_C:
        return "C_mid"
    return "other"


def roi_proxy(rows) -> float:
    """mean(won/agf_implied) − 1. >0 underbet(value), <0 overbet. PROXY."""
    vals = [r["won"] / r["agf_implied"] for r in rows if r["agf_implied"] > 0]
    return (sum(vals) / len(vals) - 1.0) if vals else 0.0


def gap(rows) -> float:
    """mean(won) − mean(agf_implied). >0 underbet."""
    if not rows:
        return 0.0
    return sum(r["won"] for r in rows) / len(rows) - sum(r["agf_implied"] for r in rows) / len(rows)


def jockey_skill(rows, min_rides: int = 8) -> dict:
    """{jockey: residual} (won−agf ortalaması, n≥min_rides). Phase 5.5 H2 metriği."""
    by = defaultdict(list)
    for r in rows:
        if r.get("jockey"):
            by[r["jockey"]].append(r["won"] - r["agf_implied"])
    return {j: sum(v) / len(v) for j, v in by.items() if len(v) >= min_rides}


def skill_quartiles(skill: dict):
    """residual'a göre alt/üst çeyrek eşikleri."""
    import numpy as np
    if not skill:
        return (0.0, 0.0)
    vals = sorted(skill.values())
    return (float(np.percentile(vals, 25)), float(np.percentile(vals, 75)))
