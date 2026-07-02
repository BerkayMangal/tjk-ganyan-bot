"""V11 isotonic kalibrasyon — p_top4 → gerçek top-4 hit oranı.

Berkay (2026-07-02): 'devam edelim v11 kalibrasyon vs vs vs'.

V11 top-4 AUC 0.7844 iyi rank ordering ama probability calibration eksik.
Model %40 diyor ama gerçekte %30 top-4 hit oluyor → isotonic function fit.

Pipeline:
  1) Backfill outcomes yükle (370 gün)
  2) Walk-forward split: son %20 test
  3) Test set üzerinde V11 predict_race_v9 çalıştır
  4) (p_top4_pred, actual_top4) tuple listesi topla
  5) IsotonicRegression fit
  6) Save calibrator + save metrics (Brier, ECE, gap)

Sonuç: fitted/v11_top4_calibrator.pkl
İnference'ta apply: calibrated_p_top4 = calibrator.transform(p_top4)

Usage:
    python -m model.v11.fit_calibration [--sample 0.2]
"""
from __future__ import annotations

import json
import logging
import pickle
import sys
from collections import defaultdict
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v11_calib")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

OUT_PATH = (ROOT / "simulation" / "calibrators" / "fitted"
             / "v11_top4_calibrator.pkl")
METRICS_PATH = (ROOT / "audit" / "reports"
                 / "v11_calibration_metrics.json")


def collect_predictions(sample_pct: float = 0.2) -> tuple:
    """V11 bundle ile test set (son %20) üzerinde inference."""
    from model.v8.train_real import _load_all_outcomes
    from model.v9.inference_v9 import predict_race_v9

    records = _load_all_outcomes()
    # Race gruplama
    race_groups = defaultdict(list)
    for r in records:
        if r.get("finish") is None or not r.get("name"):
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)

    ordered = sorted(race_groups.keys(), key=lambda k: (k[0], k[2]))
    split = int(len(ordered) * (1.0 - sample_pct))
    test_keys = ordered[split:]
    log.info(f"toplam koşu: {len(ordered)}, test: {len(test_keys)}")

    preds_all = []
    outcomes_all = []
    n_races = 0
    for (date, hippo, kosu) in test_keys:
        runners = race_groups[(date, hippo, kosu)]
        if len(runners) < 4:
            continue
        # V11 input
        horses = []
        for r in runners:
            horses.append({
                "horse_no": r.get("at_no"),
                "horse_name": r.get("name"),
                "age": r.get("age"), "weight": r.get("weight"),
                "jockey_name": r.get("jockey"),
                "sire": r.get("sire"),
                "distance": r.get("distance") or 1600,
                "track_type": "Çim",
                "hippodrome": hippo,
            })
        preds = predict_race_v9(horses, ref_date=date)
        if not preds:
            continue
        # Match at_no → prediction
        pred_by = {p.get("horse_no"): p for p in preds}
        for r in runners:
            p = pred_by.get(r.get("at_no"))
            if not p or p.get("p_top4") is None:
                continue
            preds_all.append(float(p["p_top4"]))
            outcomes_all.append(1 if r.get("finish", 99) <= 4 else 0)
        n_races += 1
        if n_races % 50 == 0:
            log.info(f"  processed {n_races}/{len(test_keys)} races, "
                     f"n_pairs: {len(preds_all)}")

    log.info(f"total pairs: {len(preds_all)}, "
             f"positive: {sum(outcomes_all)} ({100 * sum(outcomes_all) / len(outcomes_all):.1f}%)")
    return preds_all, outcomes_all


def fit_isotonic(preds, outcomes) -> dict:
    """Isotonic regression fit + metrics."""
    import numpy as np
    from sklearn.isotonic import IsotonicRegression
    from sklearn.metrics import brier_score_loss

    preds = np.array(preds)
    outcomes = np.array(outcomes)

    # Uncalibrated metrics
    brier_raw = brier_score_loss(outcomes, preds)

    # Fit
    calib = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
    calib.fit(preds, outcomes)

    # Calibrated metrics
    preds_cal = calib.transform(preds)
    brier_cal = brier_score_loss(outcomes, preds_cal)

    # ECE (Expected Calibration Error) — binned
    def ece(pred, out, n_bins=10):
        bins = np.linspace(0, 1, n_bins + 1)
        e = 0.0
        for i in range(n_bins):
            mask = (pred >= bins[i]) & (pred < bins[i + 1])
            if not mask.any():
                continue
            e += mask.sum() / len(pred) * abs(
                pred[mask].mean() - out[mask].mean())
        return e

    ece_raw = ece(preds, outcomes)
    ece_cal = ece(preds_cal, outcomes)

    # Gap (avg predicted - avg actual)
    gap_raw = float(preds.mean() - outcomes.mean())
    gap_cal = float(preds_cal.mean() - outcomes.mean())

    return {
        "calibrator": calib,
        "n_samples": len(preds),
        "positive_rate": float(outcomes.mean()),
        "brier_raw": float(brier_raw),
        "brier_calibrated": float(brier_cal),
        "brier_improvement": float(brier_raw - brier_cal),
        "ece_raw": float(ece_raw),
        "ece_calibrated": float(ece_cal),
        "ece_improvement_pct": (100 * (ece_raw - ece_cal) / ece_raw
                                 if ece_raw > 0 else 0),
        "gap_raw": gap_raw,
        "gap_calibrated": gap_cal,
    }


def main():
    log.info("Collecting V11 predictions on test set...")
    preds, outcomes = collect_predictions(sample_pct=0.20)
    if not preds:
        log.error("No predictions collected — model bundle or data problem")
        return
    log.info("Fitting isotonic regression...")
    res = fit_isotonic(preds, outcomes)
    log.info(f"n={res['n_samples']}, "
             f"Brier: {res['brier_raw']:.4f} → {res['brier_calibrated']:.4f}, "
             f"ECE: {res['ece_raw']:.4f} → {res['ece_calibrated']:.4f}, "
             f"gap: {res['gap_raw']:+.4f} → {res['gap_calibrated']:+.4f}")

    # Save calibrator
    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(OUT_PATH, "wb") as f:
        pickle.dump(res["calibrator"], f)
    log.info(f"Calibrator saved: {OUT_PATH}")

    # Save metrics report
    METRICS_PATH.parent.mkdir(parents=True, exist_ok=True)
    metrics = {k: v for k, v in res.items() if k != "calibrator"}
    with open(METRICS_PATH, "w") as f:
        json.dump(metrics, f, indent=2, ensure_ascii=False)
    log.info(f"Metrics saved: {METRICS_PATH}")

    print("\n=== V11 CALIBRATION SUMMARY ===")
    print(f"  n samples:      {res['n_samples']:,}")
    print(f"  positive rate:  {res['positive_rate']*100:.1f}%")
    print(f"  Brier: {res['brier_raw']:.4f} → {res['brier_calibrated']:.4f} "
          f"(Δ {res['brier_improvement']:+.4f})")
    print(f"  ECE:   {res['ece_raw']:.4f} → {res['ece_calibrated']:.4f} "
          f"({res['ece_improvement_pct']:+.1f}%)")
    print(f"  Gap:   {res['gap_raw']:+.4f} → {res['gap_calibrated']:+.4f}")


if __name__ == "__main__":
    main()
