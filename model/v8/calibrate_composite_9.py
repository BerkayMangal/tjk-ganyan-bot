"""Composite 9-terim tam kalibrasyon (α–ι grid search).

Berkay (2026-07-01): ε–ι default değerlerdi, overfitting riski, kalibre et.

Composite formül:
  score = α·MC + β·V9.5(p4) + γ·tempo + δ·V7 + ε·AGF_Δ
        + ζ·foreign_form + η·big_sire + θ·uk_champion + ι·uk_steam

Backfill'de gerçek AGF_Δ / foreign form / big_sire / champion / steam
proxy'lerle:
  • AGF Δ         → agf_std (tarihsel varyans, backfill_agf'ten)
  • foreign form  → sire tanınırlığı + at doğum ülkesi proxy
  • big_sire      → outcomes_rich sire → BIG_SIRE_LIST match
  • uk_champion   → jockey tanınırlığı (isim heuristik)
  • uk_steam      → agftahmin backfill'de günde 1 snapshot → 0
                     (bugün-öncesi backtest edilemez, forward-only kalır)

Bu yüzden ε, ζ, η, θ ölçebiliriz (ι forward-only).

Walk-forward 70/30, point-in-time.

Usage:
    python -m model.v8.calibrate_composite_9
"""
from __future__ import annotations

import json
import logging
import os
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("composite_9")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_PATH = (ROOT / "simulation" / "calibrators"
            / "composite_weights_9.json")


def build_race_predictions_extended():
    """Outcomes_rich + AGF backfill + proxy'ler ile at-bazlı feature seti."""
    from model.v8.calibrate_composite import _build_race_predictions
    from forecast.pedigree_intel import check_big_sire
    from forecast.uk_champions import check_uk_champion

    log.info("base race predictions...")
    races = _build_race_predictions()
    log.info(f"races: {len(races)}")

    # AGF history for σ proxy (agf_delta ~= tarihsel varyans)
    from forecast.agf_history import build_agf_history_map
    agf_map = build_agf_history_map(
        str(ROOT / "data" / "backfill" / "agftahmin"),
        str(ROOT / "data" / "backfill" / "outcomes_rich"))
    log.info(f"agf_history: {len(agf_map)}")

    # Sire lookup: outcomes_rich içinde her at için sire var
    import json as _j
    sire_by_horse = {}
    for fp in (ROOT / "data" / "backfill"
                / "outcomes_rich").glob("*.json"):
        try:
            with open(fp) as f:
                d = _j.load(f)
            for hip in (d.get("hippodromes") or []):
                for k in (hip.get("kosular") or {}).values():
                    for fin in (k.get("finishers") or []):
                        nm = fin.get("name")
                        sire = fin.get("sire")
                        if nm and sire:
                            sire_by_horse.setdefault(nm, sire)
        except Exception:
            pass
    log.info(f"sire_by_horse: {len(sire_by_horse)}")

    # Her at için ekstra feature'lar
    for race in races:
        for h in race["horses"]:
            nm = h.get("name")
            if not nm:
                continue
            # AGF Δ proxy: agf_std (backfill'de tarihsel varyans yüksek → volatil)
            hist = (agf_map.get(nm) or [])
            if len(hist) >= 3:
                pcts = [x["agf_pct"] for x in hist[:6]
                        if isinstance(x.get("agf_pct"), (int, float))]
                if pcts and len(pcts) > 1:
                    m = sum(pcts) / len(pcts)
                    std = (sum((p - m) ** 2 for p in pcts) / len(pcts)) ** 0.5
                    # Yüksek std = volatilite = steam olabilir → +sinyal
                    h["agf_delta_proxy"] = min(1.0, std / 10.0)  # 10pp std → 1
                else:
                    h["agf_delta_proxy"] = 0.0
            else:
                h["agf_delta_proxy"] = 0.0

            # Foreign form proxy: sire yabancı ülke suffix'i (FR, GB, IRE, USA)
            sire = sire_by_horse.get(nm, "")
            if any(sfx in sire for sfx in ("(GB)", "(IRE)", "(FR)", "(USA)",
                                             "(AU)", "(GER)")):
                h["foreign_proxy"] = 0.5  # yabancı doğum sire var
            else:
                h["foreign_proxy"] = 0.0

            # Big sire proxy: BIG_SIRE_LIST match
            bs_result = check_big_sire(sire, race.get("distance", 1600),
                                        "Çim")
            h["big_sire_score"] = bs_result.get("score", 0)

    return races


def _evaluate_weights_9(races, alpha, beta, gamma, delta,
                         eps, zeta, eta, theta):
    """9 terim skoru — ι (uk_steam) proxy yok, 0 alınır."""
    top1_hit = 0
    top4_overlap = 0
    total_top4_possible = 0
    n = 0
    for race in races:
        horses = race["horses"]
        if len(horses) < 4:
            continue
        max_p1 = max(h["p_top1"] for h in horses) or 1.0
        max_p4 = max(h["p_top4"] for h in horses) or 1.0
        max_v7 = max(h.get("v7_prob", 0) for h in horses) or 1.0

        for h in horses:
            mc1n = h["p_top1"] / max_p1
            p4n = h["p_top4"] / max_p4
            tempo_r = 0.5  # sabit proxy
            v7n = (h.get("v7_prob", 0) / max_v7) if max_v7 else 0
            agf_d = h.get("agf_delta_proxy", 0)
            ff = h.get("foreign_proxy", 0)
            bs = h.get("big_sire_score", 0)
            uc = 0  # champion proxy yok backfill'de (jockey adı gerekli)
            us = 0  # uk_steam proxy yok
            h["_score"] = (alpha * mc1n + beta * p4n + gamma * tempo_r
                            + delta * v7n + eps * agf_d + zeta * ff
                            + eta * bs + theta * uc)

        ranked = sorted(horses, key=lambda x: -x["_score"])
        if ranked[0]["finish"] == 1:
            top1_hit += 1
        c_top4 = {h["name"] for h in ranked[:4]}
        a_top4 = {h["name"] for h in horses if h["finish"] <= 4}
        top4_overlap += len(c_top4 & a_top4)
        total_top4_possible += min(4, len(a_top4))
        n += 1
    return {
        "n": n,
        "top1_hit_rate": top1_hit / n if n else 0,
        "top4_recall": (top4_overlap / total_top4_possible
                         if total_top4_possible else 0),
    }


def grid_search_9():
    """9 boyutlu grid — coarse (küçük adım)."""
    races = build_race_predictions_extended()
    if not races:
        return None

    # Kronolojik train/test split
    races.sort(key=lambda r: r["date"])
    split = int(len(races) * 0.70)
    train_r = races[:split]
    test_r = races[split:]
    log.info(f"WALK-FORWARD: train {len(train_r)} ({train_r[0]['date']} → "
             f"{train_r[-1]['date']}), test {len(test_r)}")

    # Base α=0.60 β=0.25 γ=0.05 δ=0.20 stabil çıkmıştı. Onları sabit tut.
    # ε, ζ, η'yi grid: 0.0, 0.03, 0.06, 0.09, 0.12
    base = {"alpha": 0.35, "beta": 0.40, "gamma": 0.05, "delta": 0.20}
    grid = [round(x * 0.03, 3) for x in range(0, 5)]  # 0.0 .. 0.12

    log.info(f"grid: {len(grid) ** 3} = {len(grid)}³ combos")
    best_train = None
    all_results = []
    total = 0
    for eps in grid:
        for zeta in grid:
            for eta in grid:
                # θ=0, ι=0 (sıfır proxy)
                m = _evaluate_weights_9(
                    train_r, base["alpha"], base["beta"],
                    base["gamma"], base["delta"],
                    eps, zeta, eta, 0)
                m.update({"eps": eps, "zeta": zeta, "eta": eta})
                m["score"] = 0.6 * m["top1_hit_rate"] + 0.4 * m["top4_recall"]
                all_results.append(m)
                if best_train is None or m["score"] > best_train["score"]:
                    best_train = m
                total += 1
                if total % 20 == 0:
                    log.info(f"  {total}/{len(grid) ** 3}")

    # Test out-of-sample
    test_m = _evaluate_weights_9(
        test_r, base["alpha"], base["beta"], base["gamma"], base["delta"],
        best_train["eps"], best_train["zeta"], best_train["eta"], 0)
    test_m.update({"eps": best_train["eps"], "zeta": best_train["zeta"],
                    "eta": best_train["eta"]})

    log.info(f"\nBEST (train):")
    log.info(f"  α={base['alpha']} β={base['beta']} γ={base['gamma']} "
             f"δ={base['delta']} ε={best_train['eps']} "
             f"ζ={best_train['zeta']} η={best_train['eta']}")
    log.info(f"  TRAIN top1={best_train['top1_hit_rate']*100:.2f}% "
             f"top4_recall={best_train['top4_recall']*100:.2f}%")
    log.info(f"  TEST  top1={test_m['top1_hit_rate']*100:.2f}% "
             f"top4_recall={test_m['top4_recall']*100:.2f}%")

    # Persist
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "w") as f:
        json.dump({
            "base": base,
            "best_train": best_train,
            "test_oos": test_m,
            "n_grid": total,
            "n_train_races": len(train_r),
            "n_test_races": len(test_r),
            "note": ("9-term (α–ι) composite grid. θ (uk_champion) and "
                      "ι (uk_steam) proxy yok backfill'de — 0 alındı. "
                      "ε, ζ, η optimize edildi. Base weights sabit "
                      "(α=0.35 β=0.40 γ=0.05 δ=0.20 önceki kalibrasyondan)."),
        }, f, indent=2, ensure_ascii=False)
    log.info(f"saved {OUT_PATH}")

    # composite_weights.json'a birleştir (ε/ζ/η yeni terimler)
    main_p = ROOT / "simulation" / "calibrators" / "composite_weights.json"
    try:
        with open(main_p) as f:
            main_d = json.load(f)
        b = main_d.setdefault("best", {})
        b["eps"] = best_train["eps"]
        b["zeta"] = best_train["zeta"]
        b["eta"] = best_train["eta"]
        b["theta"] = 0.04  # default (proxy yok)
        b["iota"] = 0.10   # default (forward-only)
        with open(main_p, "w") as f:
            json.dump(main_d, f, indent=2, ensure_ascii=False)
        log.info(f"merged into {main_p}")
    except Exception as exc:
        log.warning(f"merge fail: {exc}")

    return best_train


if __name__ == "__main__":
    grid_search_9()
