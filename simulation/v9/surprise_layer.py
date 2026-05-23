"""Phase 5.6 L2 — surprise layer: P(favori kaybeder) per ayak.

AGF dağılımının normalize Shannon entropy'si → favori-kayıp olasılığı. Mapping VERİ-FİT
(isotonic: entropy↑ → fav_loses↑), magic number yok. Düşük entropy (tek-favori netlik) →
düşük surprise; yüksek entropy (kaos) → yüksek surprise. Lazy-fit (complete.csv), cache.
"""
from __future__ import annotations

import csv
import math
import os
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
_iso = None
_base_rate = 0.76  # fallback (fit edilince güncellenir)


def norm_entropy(agf_list) -> float:
    """Normalize Shannon entropy [0,1]. agf_list: agf_implied (veya agf_pct)."""
    vals = [a for a in agf_list if a and a > 0]
    if len(vals) < 2:
        return 0.0
    s = sum(vals)
    p = [v / s for v in vals]
    h = -sum(pi * math.log(pi) for pi in p if pi > 0)
    return h / math.log(len(p))  # [0,1]


def _fit():
    global _iso, _base_rate
    if _iso is not None:
        return _iso
    legs = defaultdict(list)
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        legs[(r["date"], r["hippodrome"], r["altili_no"], r["ayak"])].append(
            (float(r["agf_implied_prob"]), int(wf)))
    X, y = [], []
    for horses in legs.values():
        if len(horses) < 2:
            continue
        ent = norm_entropy([h[0] for h in horses])
        fav_idx = max(range(len(horses)), key=lambda i: horses[i][0])
        fav_lost = 0 if horses[fav_idx][1] == 1 else 1
        X.append(ent)
        y.append(fav_lost)
    if not X:
        _iso = False
        return _iso
    _base_rate = sum(y) / len(y)
    try:
        from sklearn.isotonic import IsotonicRegression
        m = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        m.fit(X, y)
        _iso = m
    except Exception:
        _iso = False
    return _iso


def surprise_for_leg(agf_list) -> float:
    """P(favori kaybeder) ∈ [0,1]."""
    ent = norm_entropy(agf_list)
    m = _fit()
    if not m:
        return _base_rate
    try:
        return round(float(m.predict([ent])[0]), 4)
    except Exception:
        return _base_rate


def compute_surprise_prob(race: dict) -> dict:
    """{ayak: P(favori kaybeder)} — race.legs üzerinden."""
    out = {}
    for leg in race.get("legs", []) or []:
        ayak = leg.get("ayak")
        agf = [h.get("agf_pct", 0) for h in (leg.get("horses") or [])]
        out[ayak] = surprise_for_leg(agf)
    return out


if __name__ == "__main__":
    _fit()
    print(f"base fav-loss rate: {_base_rate:.3f}")
    for ent_demo in [0.3, 0.6, 0.9]:
        m = _fit()
        p = float(m.predict([ent_demo])[0]) if m else _base_rate
        print(f"  norm_entropy={ent_demo} → P(fav loses)={p:.3f}")
