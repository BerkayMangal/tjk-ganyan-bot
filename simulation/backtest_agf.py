"""Phase 5.2.5 PART D — AGF backtest (outcome var artık).

⚠ Model-prob stratejileri (V5.1/V7/smart_genis) tarihsel koşturulamaz (model_prob yok,
Phase 5.2 teyit). AMA outcome VAR → AGF-bazlı GERÇEK backtest:
- per-leg top-N coverage (DAR vs GENİŞ genişlik kararı = Phase 5.3 girdisi)
- altılı 6/6 hit (coverage width)
- reliability: AGF% bin → gerçek winrate (raw vs isotonic-calibrated)
calibrated etkisi: isotonic MONOTON → top-N seçimi değişmez (sıralama aynı). Değeri
value/EV'de (Phase 5.4 Benter, 5.5 FLB), kapsama-bazlı seçimde değil.
"""
from __future__ import annotations

import csv
import os
import pickle
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
PKL = os.path.join(_REPO, "simulation", "calibrators", "fitted", "agf_outcome_calibrator.pkl")


def _load_legs():
    """{(date,hip,altili,ayak): [(at_no, agf_pct, agf_implied, won)]} — won_flag dolu."""
    legs = defaultdict(list)
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        legs[(r["date"], r["hippodrome"], r["altili_no"], r["ayak"])].append(
            (int(r["at_no"]), float(r["agf_pct"]), float(r["agf_implied_prob"]), int(wf)))
    return legs


def coverage_by_topn(legs, max_n=6):
    """top-N AGF atı kazananı kapsıyor mu (per-leg)."""
    cov = {}
    for n in range(1, max_n + 1):
        hit = tot = 0
        for horses in legs.values():
            if not any(h[3] for h in horses):  # kazanan etiketli değilse atla
                continue
            top = sorted(horses, key=lambda h: -h[1])[:n]
            hit += int(any(h[3] for h in top))
            tot += 1
        cov[n] = round(hit / tot, 4) if tot else 0.0
    return cov


def altili_hit_by_width(legs, max_n=4):
    """Her altılı: tüm 6 ayakta top-N seç → 6/6 tutar mı (gerçek kazananlar)."""
    by_altili = defaultdict(dict)  # (date,hip,altili) → {ayak: horses}
    for (d, h, a, ay), horses in legs.items():
        by_altili[(d, h, a)][ay] = horses
    res = {}
    for n in range(1, max_n + 1):
        full = wins = 0
        for ayaklar in by_altili.values():
            if len(ayaklar) < 6:  # tam 6 ayaklı altılı
                continue
            full += 1
            ok = True
            for horses in ayaklar.values():
                top = sorted(horses, key=lambda h: -h[1])[:n]
                if not any(h[3] for h in top):
                    ok = False
                    break
            wins += int(ok)
        res[n] = {"altili_count": full, "hit_6_6": wins,
                  "hit_rate": round(wins / full, 4) if full else 0.0}
    return res


def reliability_bins(legs, bins=10):
    """AGF_implied bin → gerçek winrate (raw) + isotonic-calibrated tahmin."""
    model = None
    if os.path.exists(PKL):
        with open(PKL, "rb") as f:
            model = pickle.load(f)["model"]
    obs = [(h[2], h[3]) for horses in legs.values() for h in horses]  # (agf_implied, won)
    out = []
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        sub = [o for o in obs if (lo <= o[0] < hi) or (b == bins - 1 and o[0] == hi)]
        if not sub:
            continue
        avg_agf = sum(o[0] for o in sub) / len(sub)
        winrate = sum(o[1] for o in sub) / len(sub)
        row = {"bin": f"{lo:.1f}-{hi:.1f}", "n": len(sub),
               "avg_agf_implied": round(avg_agf, 4), "actual_winrate": round(winrate, 4)}
        if model is not None:
            row["calibrated"] = round(float(model.predict([avg_agf])[0]), 4)
        out.append(row)
    return out


def run() -> dict:
    legs = _load_legs()
    return {
        "n_legs": len(legs),
        "coverage_by_topn": coverage_by_topn(legs),
        "altili_hit_by_width": altili_hit_by_width(legs),
        "reliability_bins": reliability_bins(legs),
        "note": "AGF-bazlı (outcome gerçek). Model-strateji backtest forward bekliyor (model_prob yok). "
                "Monoton kalibrasyon top-N seçimi değiştirmez.",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(run(), ensure_ascii=False, indent=2))
