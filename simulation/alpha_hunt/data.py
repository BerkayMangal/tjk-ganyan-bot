"""Phase 5.8.0 — paylaşımlı veri + istatistik yardımcıları (read-only).

races(): per-koşu (ayak) bitiş sırası (S) + agf + won + feat (age/weight/jockey/sire/distance).
horse_rows(): düz at-satırları. flb_mult/value calibrator'dan. Stats: bootstrap/wilson/bonferroni/cohen_d.
"""
from __future__ import annotations

import csv
import math
import os
import pickle
import random
import sys
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from simulation.tr_bias_analysis import _load_rich, _norm, DATASET  # noqa: E402

_FLB = os.path.join(_REPO, "simulation", "calibrators", "fitted", "flb_compensator.pkl")
_fc = None


def _flb():
    global _fc
    if _fc is None:
        try:
            _fc = pickle.load(open(_FLB, "rb"))
        except Exception:
            _fc = False
    return _fc


def flb_mult(agf_pct):
    fc = _flb()
    if not fc or not agf_pct:
        return 1.0
    try:
        return float(fc.multiplier(agf_pct))
    except Exception:
        return 1.0


def races():
    """[{date,hip,altili,ayak,distance, horses:[{at_no,agf,agf_implied,won,S,age,weight,jockey,sire,flb,value}]}]"""
    rich = _load_rich()
    legs = defaultdict(dict)
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        legs[(r["date"], r["hippodrome"], r["altili_no"], r["ayak"])][int(r["at_no"])] = {
            "agf": float(r["agf_pct"]), "agf_implied": float(r["agf_implied_prob"]), "won": int(wf)}
    out = []
    for (date, hip, altili, ayak), atmap in legs.items():
        kosular = rich.get((date, _norm(hip)))
        feat = {}
        dist = None
        if kosular:
            at_set = set(atmap)
            best, best_s = None, 0.0
            for info in kosular.values():
                inter = len(at_set & info["at_set"]); union = len(at_set | info["at_set"])
                s = inter / union if union else 0
                if s > best_s:
                    best, best_s = info, s
            if best and best_s >= 0.5:
                feat = best["by_at"]; dist = best.get("distance")
        horses = []
        for at_no, d in atmap.items():
            f = feat.get(at_no, {})
            horses.append({"at_no": at_no, "agf": d["agf"], "agf_implied": d["agf_implied"],
                           "won": d["won"], "S": f.get("S"), "age": f.get("age"),
                           "weight": f.get("weight"), "jockey": f.get("jockey"),
                           "sire": f.get("sire"), "flb": round(flb_mult(d["agf"]), 4),
                           "value": round(flb_mult(d["agf"]), 4)})
        out.append({"date": date, "hip": _norm(hip), "altili": altili, "ayak": ayak,
                    "distance": dist, "horses": horses})
    return out


def horse_rows():
    rows = []
    for r in races():
        for h in r["horses"]:
            rows.append({**h, "date": r["date"], "hip": r["hip"], "ayak": r["ayak"],
                         "altili": r["altili"], "distance": r["distance"]})
    return rows


# ---- stats ----
def wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n; d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def bootstrap_ci(vals, stat=lambda v: sum(v) / len(v), nb=1000, seed=7):
    if not vals:
        return (0.0, 0.0)
    rng = random.Random(seed); n = len(vals); out = []
    for _ in range(nb):
        s = [vals[rng.randrange(n)] for _ in range(n)]
        out.append(stat(s))
    out.sort()
    return (round(out[int(0.025 * nb)], 4), round(out[int(0.975 * nb)], 4))


def cohen_d(a, b):
    import statistics as st
    if len(a) < 2 or len(b) < 2:
        return 0.0
    na, nb = len(a), len(b)
    va, vb = st.variance(a), st.variance(b)
    sp = math.sqrt(((na - 1) * va + (nb - 1) * vb) / (na + nb - 2)) if (na + nb - 2) > 0 else 0
    return round((st.mean(a) - st.mean(b)) / sp, 3) if sp > 0 else 0.0


def bonferroni(alpha, n_tests):
    return alpha / max(1, n_tests)
