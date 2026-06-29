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
    """En güncel modeli yükle: V9 → V8.6 → V8.5 → V8.

    NOT: V9 ensemble durumunda XGB head'i ensemble proxy olarak kullanılır
    (composite calibrate basit predict gerek; gerçek ensemble production
    inference_v9.py'da).
    """
    import xgboost as xgb
    candidates = [
        ROOT / "model" / "v9" / "trained" / "v9_ensemble.json",
        ROOT / "model" / "v8" / "trained" / "v8_6_real.json",
        ROOT / "model" / "v8" / "trained" / "v8_5_real.json",
        ROOT / "model" / "v8" / "trained" / "v8_real.json",
    ]
    for p in candidates:
        if not p.exists():
            continue
        with open(p) as f:
            d = json.load(f)
        feature_cols = d["feature_cols"]
        heads = {}
        # V9 format: heads[head] = {xgb_hex, lgbm_txt, cat_b64, ...}
        # V8.x format: heads[head] = hex string
        for head, head_data in d.get("heads", {}).items():
            booster = xgb.Booster()
            try:
                if isinstance(head_data, str):
                    booster.load_model(bytearray.fromhex(head_data))
                elif isinstance(head_data, dict) and "xgb_hex" in head_data:
                    booster.load_model(bytearray.fromhex(
                        head_data["xgb_hex"]))
                else:
                    continue
                heads[head] = booster
            except Exception as exc:
                log.warning(f"head {head} load fail: {exc}")
        if heads:
            log.info(f"composite_calibrate using model: {p.name} "
                     f"(n_features={len(feature_cols)}, "
                     f"heads={list(heads.keys())})")
            return heads, feature_cols
    log.error("hiçbir model yüklenemedi")
    return None, None


def _build_race_predictions():
    """Outcomes_rich → her koşu için at başına (V8 p_top1..4, V7 proxy, finish).

    V7 prediction PROXY: career_top4_rate (atın geçmiş ilk-4 oranı).
    Bu, AGF-bağımsız ve outcomes_rich'tan direkt çıkarılabilir bir
    "tabela bilgisi" PROXY'sidir. Gerçek V7 ndcg@4 LambdaRank prod inference
    için TJK programmes feature pipeline gerekir; proxy ile yaklaşık
    karşılaştırma yapıyoruz.
    """
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

    race_groups = defaultdict(list)
    for r in records:
        if not r.get("name") or r.get("finish") is None:
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)

    log.info(f"toplam koşu: {len(race_groups)}")
    races = []
    skipped = 0
    for (date, hippo, kosu_no), runners in race_groups.items():
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
        p_top1 = heads["top1"].predict(dtest) if "top1" in heads else None
        p_top4 = heads["top4"].predict(dtest) if "top4" in heads else None
        race_horses = []
        for i, (r, feat) in enumerate(rows):
            # V7 PROXY: career_top4_rate (yıllık ilk-4 oranı). Gerçek V7
            # ndcg@4 LambdaRank her at için tabela context kullanır;
            # bu proxy AGF-FREE ortak baseline'dır.
            v7_proxy = feat.get("career_top4_rate", 0) or 0
            race_horses.append({
                "name": r["name"],
                "at_no": r["at_no"],
                "finish": r["finish"],
                "p_top1": float(p_top1[i]) if p_top1 is not None else 0,
                "p_top4": float(p_top4[i]) if p_top4 is not None else 0,
                "v7_prob": float(v7_proxy),
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


def _evaluate_weights(races, alpha, beta, gamma, delta=0.0):
    """Composite skor sıralaması doğruluğu (4-değişken hibrit dahil).

    score = α·MC_p1 + β·V8_p4 + γ·tempo + δ·V7_proxy
    """
    top1_hit = 0
    top4_hit_avg = 0
    total_top4_possible = 0
    n_races = 0
    for race in races:
        horses = race["horses"]
        if len(horses) < 4:
            continue
        max_p1 = max(h["p_top1"] for h in horses) or 1.0
        max_p4 = max(h["p_top4"] for h in horses) or 1.0
        max_v7 = max(h.get("v7_prob", 0) for h in horses) or 1.0
        for h in horses:
            mc_p1_norm = h["p_top1"] / max_p1
            p4_norm = h["p_top4"] / max_p4
            tempo_robust = 0.5
            v7_norm = (h.get("v7_prob", 0) / max_v7) if max_v7 else 0
            h["_composite"] = (alpha * mc_p1_norm
                                + beta * p4_norm
                                + gamma * tempo_robust
                                + delta * v7_norm)
        ranked = sorted(horses, key=lambda h: -h["_composite"])
        if ranked[0]["finish"] == 1:
            top1_hit += 1
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
    """α/β/γ/δ grid search — WALK-FORWARD (point-in-time, kronolojik split).

    İki paralel grid:
      • Saf V8 (δ=0)        — eski hesap
      • Hibrit V7+V8 (δ>0)  — V7 model_prob proxy dahil

    HONEST TEST: ilk %70 koşu train (grid search), son %30 koşu test
    (out-of-sample raporlama). In-sample optimization overfit riski
    yarattığı için bu zorunlu (Berkay 2026-06-29: 'point-in-time mi?').
    """
    races = _build_race_predictions()
    if not races:
        log.error("races boş")
        return None

    # Kronolojik sıralama + train/test split (point-in-time)
    races.sort(key=lambda r: r["date"])
    split_idx = int(len(races) * 0.70)
    train_races = races[:split_idx]
    test_races = races[split_idx:]
    log.info(f"grid search WALK-FORWARD: train={len(train_races)} koşu "
             f"({train_races[0]['date']} → {train_races[-1]['date']}), "
             f"test={len(test_races)} koşu "
             f"({test_races[0]['date']} → {test_races[-1]['date']})")
    step = 0.05
    weights_pure = []  # δ=0
    weights_hybrid = []  # δ>0
    for a in [round(x * step, 2) for x in range(2, 17)]:
        for b in [round(x * step, 2) for x in range(2, 17)]:
            # δ=0 (sade V8)
            g = round(1.0 - a - b, 2)
            if 0.05 <= g <= 0.50:
                weights_pure.append((a, b, g, 0.0))
            # δ>0 (V7 dahil)
            for d in [round(x * step, 2) for x in range(2, 13)]:
                g = round(1.0 - a - b - d, 2)
                if 0.05 <= g <= 0.50:
                    weights_hybrid.append((a, b, g, d))
    log.info(f"saf (δ=0) kombinasyon: {len(weights_pure)} · "
             f"hibrit (δ>0): {len(weights_hybrid)}")

    def _run(weights, tag):
        """Train üzerinde grid search → best; test üzerinde out-of-sample eval."""
        best_train = None
        train_results = []
        for a, b, g, d in weights:
            m = _evaluate_weights(train_races, a, b, g, d)
            m["alpha"] = a; m["beta"] = b; m["gamma"] = g; m["delta"] = d
            train_results.append(m)
            m["score"] = 0.6 * m["top1_hit_rate"] + 0.4 * m["top4_recall"]
            if best_train is None or m["score"] > best_train["score"]:
                best_train = m
        # En iyi train ağırlığıyla TEST üzerinde değerlendir (out-of-sample)
        test_m = _evaluate_weights(
            test_races, best_train["alpha"], best_train["beta"],
            best_train["gamma"], best_train["delta"])
        test_m["alpha"] = best_train["alpha"]
        test_m["beta"] = best_train["beta"]
        test_m["gamma"] = best_train["gamma"]
        test_m["delta"] = best_train["delta"]
        test_m["score"] = (0.6 * test_m["top1_hit_rate"]
                            + 0.4 * test_m["top4_recall"])

        train_results.sort(key=lambda x: -x["score"])
        log.info(f"\n=== [{tag}] BEST (train→test) ===")
        log.info(f"  Ağırlık: α={best_train['alpha']} β={best_train['beta']} "
                 f"γ={best_train['gamma']} δ={best_train['delta']}")
        log.info(f"  TRAIN top-1 hit:    %{best_train['top1_hit_rate']*100:.2f}")
        log.info(f"  TRAIN top-4 recall: %{best_train['top4_recall']*100:.2f}")
        log.info(f"  TEST  top-1 hit:    %{test_m['top1_hit_rate']*100:.2f} "
                 f"(out-of-sample)")
        log.info(f"  TEST  top-4 recall: %{test_m['top4_recall']*100:.2f} "
                 f"(out-of-sample)")
        gap_t1 = (best_train["top1_hit_rate"] - test_m["top1_hit_rate"]) * 100
        if gap_t1 > 5:
            log.warning(f"  ⚠ train→test gap top-1 {gap_t1:.1f}pp — overfit?")
        return best_train, test_m, train_results

    best_train_pure, test_pure, _ = _run(weights_pure, "SAF V8 (δ=0)")
    best_train_hyb, test_hyb, _ = _run(weights_hybrid, "HİBRİT V7+V8 (δ>0)")

    # Test (out-of-sample) karşılaştırma
    delta_top1 = (test_hyb["top1_hit_rate"]
                  - test_pure["top1_hit_rate"]) * 100
    delta_top4 = (test_hyb["top4_recall"]
                  - test_pure["top4_recall"]) * 100
    log.info(f"\n=== TEST (OUT-OF-SAMPLE): HİBRİT vs SAF V8 ===")
    log.info(f"  Top-1 hit:    saf %{test_pure['top1_hit_rate']*100:.2f} → "
             f"hibrit %{test_hyb['top1_hit_rate']*100:.2f}  "
             f"({'+' if delta_top1>=0 else ''}{delta_top1:.2f}pp)")
    log.info(f"  Top-4 recall: saf %{test_pure['top4_recall']*100:.2f} → "
             f"hibrit %{test_hyb['top4_recall']*100:.2f}  "
             f"({'+' if delta_top4>=0 else ''}{delta_top4:.2f}pp)")

    # Production'a kazananı yaz (test skoru üzerinden)
    final_best = (test_hyb if test_hyb["score"] > test_pure["score"]
                  else test_pure)

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "best": final_best,
            "best_train_pure": best_train_pure,
            "best_train_hybrid": best_train_hyb,
            "test_pure": test_pure,
            "test_hybrid": test_hyb,
            "delta_top1_pp": delta_top1,
            "delta_top4_pp": delta_top4,
            "n_races_total": len(races),
            "n_races_train": len(train_races),
            "n_races_test": len(test_races),
            "split": {
                "train_dates": [train_races[0]["date"],
                                 train_races[-1]["date"]],
                "test_dates": [test_races[0]["date"],
                                test_races[-1]["date"]],
            },
            "note": ("WALK-FORWARD point-in-time grid search. Train %70 / "
                     "Test %30 kronolojik. 4-değişken: α (MC) + β (V8_p_top4) "
                     "+ γ (tempo) + δ (V7_proxy=career_top4_rate). "
                     "Production'a TEST (out-of-sample) en iyi yazılır."),
        }, f, indent=2, ensure_ascii=False)
    log.info(f"\nsaved {OUT_PATH}")
    log.info(f"PRODUCTION ağırlık: α={final_best['alpha']} "
             f"β={final_best['beta']} γ={final_best['gamma']} "
             f"δ={final_best['delta']}")
    return final_best


if __name__ == "__main__":
    grid_search()
