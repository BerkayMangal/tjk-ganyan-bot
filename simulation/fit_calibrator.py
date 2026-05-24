"""Phase 5.2.5 PART C — kalibratör fit (AGF_implied → outcome).

⚠ DÜRÜSTLÜK: Tarihsel model_prob YOK (replay OOD, Phase 5.2). Fit edilen GERÇEK kalibratör
= AGF_implied (piyasa) → outcome. Bu PIYASA/FLB kalibrasyonu (Phase 5.4 Benter agf_implied +
5.5 FLB girdisi), MODEL kalibratörü DEĞİL. active.pkl (loader'ın model_prob'a uyguladığı)
BİLEREK yazılmaz — sahte model-kalibratörü üretmiyoruz. Walk-forward (zaman split, look-ahead yok).
"""
from __future__ import annotations

import csv
import math
import os
import pickle

from calibrators.isotonic import IsotonicCalibrator
from calibrators.platt import PlattCalibrator

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
FITTED_DIR = os.path.join(_REPO, "simulation", "calibrators", "fitted")
MIN_N = 200
TRAIN_FRAC = 0.7


def _brier(p, y):
    return sum((pi - yi) ** 2 for pi, yi in zip(p, y)) / len(y)


def _logloss(p, y, eps=1e-12):
    s = 0.0
    for pi, yi in zip(p, y):
        pi = min(1 - eps, max(eps, pi))
        s += -(yi * math.log(pi) + (1 - yi) * math.log(1 - pi))
    return s / len(y)


def _ece(p, y, bins=10):
    """Expected calibration error (reliability gap)."""
    tot = len(y)
    e = 0.0
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        idx = [i for i, pi in enumerate(p) if (lo <= pi < hi) or (b == bins - 1 and pi == hi)]
        if not idx:
            continue
        conf = sum(p[i] for i in idx) / len(idx)
        acc = sum(y[i] for i in idx) / len(idx)
        e += (len(idx) / tot) * abs(conf - acc)
    return e


def _load():
    """[(date, agf_implied, won)] — won_flag ∈ {0,1} olan satırlar."""
    if not os.path.exists(DATASET):
        return []
    out = []
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        try:
            out.append((r["date"], float(r["agf_implied_prob"]), int(wf)))
        except (ValueError, KeyError):
            continue
    return out


def fit() -> dict:
    data = _load()
    if len(data) < MIN_N:
        return {"status": "INSUFFICIENT_DATA", "n": len(data), "min_n": MIN_N}

    data.sort(key=lambda t: t[0])  # zaman sıralı (walk-forward)
    cut = int(len(data) * TRAIN_FRAC)
    tr, va = data[:cut], data[cut:]
    if not va:
        return {"status": "INSUFFICIENT_DATA", "n": len(data), "note": "val boş"}

    Xtr, ytr = [d[1] for d in tr], [d[2] for d in tr]
    Xva, yva = [d[1] for d in va], [d[2] for d in va]

    iso = IsotonicCalibrator().fit(Xtr, ytr)
    platt = PlattCalibrator().fit(Xtr, ytr)
    p_iso = iso.predict(Xva)
    p_platt = platt.predict(Xva)

    def _row(p):
        return {"brier": round(float(_brier(p, yva)), 5),
                "logloss": round(float(_logloss(p, yva)), 5),
                "ece": round(float(_ece(p, yva)), 5)}

    m = {"raw": _row(Xva), "isotonic": _row(p_iso), "platt": _row(p_platt)}
    best = min(("isotonic", "platt"), key=lambda k: m[k]["brier"])
    improved = bool(m[best]["brier"] < m["raw"]["brier"])

    os.makedirs(FITTED_DIR, exist_ok=True)
    model = iso if best == "isotonic" else platt
    # AGF/piyasa kalibratörü — active.pkl DEĞİL (model_prob'a uygulanmaz)
    path = os.path.join(FITTED_DIR, "agf_outcome_calibrator.pkl")
    with open(path, "wb") as f:
        pickle.dump({"kind": "agf_implied->outcome", "method": best, "model": model,
                     "n_train": len(tr), "n_val": len(va)}, f)

    return {
        "status": "OK",
        "n": len(data), "n_train": len(tr), "n_val": len(va),
        "base_rate_val": round(sum(yva) / len(yva), 4),
        "metrics": m, "best_method": best, "improved_over_raw": improved,
        "saved": path,
        "note": "AGF→outcome (piyasa/FLB). active.pkl YAZILMADI (model_prob tarihsel yok).",
    }


if __name__ == "__main__":
    import json
    print(json.dumps(fit(), ensure_ascii=False, indent=2))
