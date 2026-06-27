"""Composite formula KALİBRASYON — grid search.

Berkay (2026-06-27): 'hangi degiskeni kac oranin kullanirsak model gecmisi
en mukemmel predict etmis'.

Composite formula:
    score = α × MC(1.olma %) + β × V8(p_top4) + γ × tempo_robust

Şu an: α=0.50, β=0.30, γ=0.20 (elle seçildi).

Bu script geçmiş outcomes_rich üzerinde grid search yapar:
  • α, β, γ ∈ {0.10, 0.20, ..., 0.80}, α+β+γ=1.0
  • Her kombinasyon için composite skor sıralaması üret
  • Metric: top-1 hit rate (1. olduğu kanıtlanan koşularda 1. seçimimiz
    kazanan mı?) + top-4 hit rate
  • En yüksek hit rate veren ağırlık = optimal

Outcomes_rich → her koşu için tüm atlar + finish sıralaması.
Her atın composite_score'unu hesapla (geçmiş feature'lardan), sıralı top-1
seçimi gerçek 1. ile eşleşiyor mu kontrol et.

Usage:
    python -m model.v8.calibrate_composite
    → simulation/calibrators/composite_weights.json
"""
from __future__ import annotations

import json
import logging
import math
import os
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("composite_calib")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUTCOMES_DIR = ROOT / "data" / "backfill" / "outcomes_rich"
OUT_PATH = ROOT / "simulation" / "calibrators" / "composite_weights.json"


def _load_v8_model():
    """V8 real model load (json from train_real.py)."""
    import xgboost as xgb
    p = ROOT / "model" / "v8" / "trained" / "v8_real.json"
    if not p.exists():
        log.error(f"v8_real.json yok: {p} — önce train_real.py çalıştır")
        return None, None
    with open(p) as f:
        d = json.load(f)
    feature_cols = d["feature_cols"]
    heads = {}
    for head, hex_str in d["heads"].items():
        booster = xgb.Booster()
        try:
            booster.load_model(bytearray.fromhex(hex_str))
        except Exception as exc:
            log.warning(f"head {head} load fail: {exc}")
            continue
        heads[head] = booster
    return heads, feature_cols


def _build_race_predictions():
    """Outcomes_rich → her koşu için at başına (V8 p_top1..4, finish)."""
    from model.v8.train_real import (
        _load_all_outcomes, _build_history_map, _build_features_for_horse,
    )
    import numpy as np
    import xgboost as xgb

    heads, feature_cols = _load_v8_model()
    if not heads:
        return []

    records = _load_all_outcomes()
    history_map = _build_history_map(records)

    # group by (date, hippo, kosu_no)
    race_groups = defaultdict(list)
    for r in records:
        if not r.get("name") or r.get("finish") is None:
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)

    log.info(f"toplam koşu: {len(race_groups)}")
    races = []
    skipped = 0
    for (date, hippo, kosu_no), runners in race_groups.items():
        # her at için feature
        rows = []
        for r in runners:
            feat = _build_features_for_horse(
                r["name"], r["date"], history_map,
                n_horses_in_race=len(runners))
            if feat is None:
                continue
            rows.append((r, feat))
        if len(rows) < 4:
            skipped += 1
            continue
        X = np.array([[row[1].get(c, 0) or 0 for c in feature_cols]
                       for row in rows])
        dtest = xgb.DMatrix(X)
        # 4 head predict
        p_top1 = heads["top1"].predict(dtest) if "top1" in heads else None
        p_top4 = heads["top4"].predict(dtest) if "top4" in heads else None
        race_horses = []
        for i, (r, _) in enumerate(rows):
            race_horses.append({
                "name": r["name"],
                "at_no": r["at_no"],
                "finish": r["finish"],
                "p_top1": float(p_top1[i]) if p_top1 is not None else 0,
                "p_top4": float(p_top4[i]) if p_top4 is not None else 0,
            })
        races.append({
            "date": date, "hippo": hippo, "kosu_no": kosu_no,
            "horses": race_horses,
        })
    log.info(f"hazır koşu: {len(races)}  (atlanan: {skipped})")
    return races


def _composite_score(p_top1, p_top4, tempo_robust,
                     mc_p1_norm, p4_norm, alpha, beta, gamma):
    """α × MC(1.) + β × V8(p_top4) + γ × tempo. Normalize."""
    return alpha * mc_p1_norm + beta * p4_norm + gamma * tempo_robust


def _evaluate_weights(races, alpha, beta, gamma):
    """Bu ağırlıklarla composite skor sıralamasının doğruluğu."""
    top1_hit = 0
    top4_hit_avg = 0  # ortalama top-4'te kaç tanesini yakaladık
    total_top4_possible = 0
    n_races = 0
    for race in races:
        horses = race["horses"]
        if len(horses) < 4:
            continue
        # normalize MC_p1 (proxy: p_top1 — MC için gerçek 10K sim çok pahalı)
        max_p1 = max(h["p_top1"] for h in horses) or 1.0
        max_p4 = max(h["p_top4"] for h in horses) or 1.0
        # tempo_robust proxy → bu data'da hesaplamak için tempo sim gerek
        # basitleştir: her at için tempo_robust = 1.0 (sabit) → grid search
        # sadece α (mc) + β (v8) üzerinde anlamlı
        for h in horses:
            mc_p1_norm = h["p_top1"] / max_p1
            p4_norm = h["p_top4"] / max_p4
            tempo_robust = 0.5  # neutral proxy
            h["_composite"] = (alpha * mc_p1_norm
                                + beta * p4_norm
                                + gamma * tempo_robust)
        ranked = sorted(horses, key=lambda h: -h["_composite"])
        # Top-1 hit?
        if ranked[0]["finish"] == 1:
            top1_hit += 1
        # Top-4 hit avg (composite top-4 içinde gerçek top-4 olanların sayısı)
        composite_top4 = {h["name"] for h in ranked[:4]}
        actual_top4 = {h["name"] for h in horses if h["finish"] <= 4}
        overlap = len(composite_top4 & actual_top4)
        top4_hit_avg += overlap
        total_top4_possible += min(4, len(actual_top4))
        n_races += 1
    return {
        "n_races": n_races,
        "top1_hit_rate": top1_hit / n_races if n_races else 0,
        "top4_avg_overlap": top4_hit_avg / n_races if n_races else 0,
        "top4_recall": (top4_hit_avg / total_top4_possible
                        if total_top4_possible else 0),
    }


def grid_search():
    """α, β, γ ∈ {0.1..0.8 step 0.1}, α+β+γ=1."""
    races = _build_race_predictions()
    if not races:
        log.error("races boş")
        return None

    log.info(f"grid search üzerinde {len(races)} koşu")
    grid = []
    # alpha, beta, gamma — toplamı 1
    step = 0.05
    weights = []
    for a in [round(x * step, 2) for x in range(2, 17)]:  # 0.10..0.80
        for b in [round(x * step, 2) for x in range(2, 17)]:
            g = round(1.0 - a - b, 2)
            if 0.05 <= g <= 0.50:
                weights.append((a, b, g))
    log.info(f"toplam kombinasyon: {len(weights)}")

    best = None
    results = []
    for a, b, g in weights:
        m = _evaluate_weights(races, a, b, g)
        m["alpha"] = a
        m["beta"] = b
        m["gamma"] = g
        results.append(m)
        # En iyi: top1 hit + top4 recall ağırlıklı
        m["score"] = 0.6 * m["top1_hit_rate"] + 0.4 * m["top4_recall"]
        if best is None or m["score"] > best["score"]:
            best = m

    results.sort(key=lambda x: -x["score"])
    log.info(f"\nEN İYİ AĞIRLIKLAR:")
    log.info(f"  α (MC 1.olma)    = {best['alpha']}")
    log.info(f"  β (V8 p_top4)    = {best['beta']}")
    log.info(f"  γ (tempo robust) = {best['gamma']}")
    log.info(f"  → Top-1 hit:     %{best['top1_hit_rate'] * 100:.2f}")
    log.info(f"  → Top-4 overlap: {best['top4_avg_overlap']:.2f}/4")
    log.info(f"  → Top-4 recall:  %{best['top4_recall'] * 100:.2f}")

    # En iyi 5
    log.info(f"\nİlk 5 sonuç (ağırlıklı skor):")
    for r in results[:5]:
        log.info(f"  α={r['alpha']} β={r['beta']} γ={r['gamma']}  "
                 f"top1={r['top1_hit_rate'] * 100:.1f}%  "
                 f"top4_recall={r['top4_recall'] * 100:.1f}%  "
                 f"score={r['score']:.4f}")

    # En kötü (referans)
    log.info(f"\nEn kötü 3:")
    for r in results[-3:]:
        log.info(f"  α={r['alpha']} β={r['beta']} γ={r['gamma']}  "
                 f"top1={r['top1_hit_rate'] * 100:.1f}%  "
                 f"top4_recall={r['top4_recall'] * 100:.1f}%")

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "best": best,
            "all_results": results,
            "n_races": len(races),
            "note": ("Grid search outcomes_rich üzerinde. α/β/γ ∈ "
                     "[0.10, 0.80], α+β+γ=1, γ ≥ 0.05. Hedef: top-1 "
                     "hit + top-4 recall ağırlıklı."),
        }, f, indent=2, ensure_ascii=False)
    log.info(f"\nsaved {OUT_PATH}")
    return best


if __name__ == "__main__":
    grid_search()
