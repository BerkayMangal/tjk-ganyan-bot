"""Phase 5.6 L3 — Benter-style combined probability: p = w1·proxy_model + w2·calib_agf.

⚠⚠ KRİTİK CAVEAT: gerçek model_prob YOK (Phase 5.2 FALLBACK). w1 girdisi = V5.1 proxy_score
(AGF-türevli) → calib_agf ile COLLINEAR → w1/w2 ayrıştırılamaz (logistic kararsız). Bu
"Benter-style", GERÇEK Benter DEĞİL. Gerçek model_prob (Phase 5.4 forward) gelince RE-FIT şart.
Şu an combined_prob ≈ kalibre_agf (w2 domine). Walk-forward (Phase 5.5/5.8 disiplini).
"""
from __future__ import annotations

import csv
import os

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
_PKL = os.path.join(_REPO, "simulation", "calibrators", "fitted", "agf_outcome_calibrator.pkl")
_model = None
_calib = None
_diag = {}


def _calib_agf(agf_implied):
    global _calib
    if _calib is None:
        import pickle
        try:
            _calib = pickle.load(open(_PKL, "rb")).get("model")
        except Exception:
            _calib = False
    if not _calib or agf_implied is None:
        return agf_implied or 0.0
    try:
        return float(_calib.predict([agf_implied])[0])
    except Exception:
        return agf_implied or 0.0


def _load_xy():
    rows = []
    if not os.path.exists(DATASET):   # PROD guard (5.7.0): dataset yok → boş (combined_prob calib'e düşer)
        return rows
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        try:
            ai = float(r["agf_implied_prob"])
            rows.append((r["date"], ai, _calib_agf(ai), int(wf)))
        except (ValueError, KeyError):
            continue
    return rows


def fit(train_frac=0.67):
    """Logistic(proxy_score≈agf, calib_agf → won), walk-forward. Diagnostics + collinearity."""
    global _model, _diag
    import numpy as np
    from sklearn.linear_model import LogisticRegression
    rows = sorted(_load_xy(), key=lambda t: t[0])
    cut = int(len(rows) * train_frac)
    tr, te = rows[:cut], rows[cut:]
    # proxy_model = agf_implied (FALLBACK), feature2 = calib_agf
    Xtr = np.array([[r[1], r[2]] for r in tr]); ytr = np.array([r[3] for r in tr])
    Xte = np.array([[r[1], r[2]] for r in te]); yte = np.array([r[3] for r in te])
    m = LogisticRegression(max_iter=1000).fit(Xtr, ytr)
    _model = m
    pte = m.predict_proba(Xte)[:, 1]
    brier_te = float(np.mean((pte - yte) ** 2))
    brier_agf = float(np.mean((Xte[:, 0] - yte) ** 2))
    brier_calib = float(np.mean((Xte[:, 1] - yte) ** 2))
    corr = float(np.corrcoef(Xtr[:, 0], Xtr[:, 1])[0, 1])
    _diag = {"w_proxy_model": round(float(m.coef_[0][0]), 3),
             "w_calib_agf": round(float(m.coef_[0][1]), 3),
             "intercept": round(float(m.intercept_[0]), 3),
             "collinearity_corr(proxy,calib)": round(corr, 4),
             "brier_OOS_combined": round(brier_te, 5),
             "brier_OOS_raw_agf": round(brier_agf, 5),
             "brier_OOS_calib_agf": round(brier_calib, 5),
             "n_train": len(tr), "n_test": len(te)}
    return _diag


def combined_prob(proxy_model, agf_implied) -> float:
    """p_final. Model yoksa fit et. proxy_model genelde ≈ agf (fallback)."""
    global _model
    if _model is None:
        fit()
    if not _model:
        return _calib_agf(agf_implied)
    try:
        return round(float(_model.predict_proba([[proxy_model, _calib_agf(agf_implied)]])[0][1]), 4)
    except Exception:
        return _calib_agf(agf_implied)


if __name__ == "__main__":
    import json
    print(json.dumps(fit(), ensure_ascii=False, indent=1))
