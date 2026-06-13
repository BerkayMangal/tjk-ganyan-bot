"""Beta calibration (Kull 2017) — prod-import-safe class.

Mevcut isotonic agf_outcome_calibrator.pkl'in muadili; Phase 5.2.6 grid'inde
beta global Brier ~%0.6 + ECE -%24 ile marjinal üstün çıktı. Bu class audit/87'deki
prototipin prod-import-safe (sklearn'e sade bağlı, ad-hoc class-path yok) sürümüdür;
pkl bu modülden unpickle edilir → calibration_loader hatasız yükler.

Public API:
    cal = BetaCalibrator().fit(probs, outcomes)
    cal.predict([0.05, 0.20, 0.5])  # → np.ndarray (0-1)
"""
from __future__ import annotations

import numpy as np
from sklearn.linear_model import LogisticRegression

_EPS = 1e-9


class BetaCalibrator:
    """logit(p_cal) = a*log(p) + b*log(1-p) + c (LogisticRegression on [log p, log 1-p])."""

    def __init__(self):
        self.model = LogisticRegression()
        self._fallback = 0.0

    def fit(self, probs, outcomes):
        p = np.clip(np.asarray(probs, dtype=float), _EPS, 1 - _EPS)
        y = np.asarray(outcomes, dtype=int)
        if len(np.unique(y)) < 2:
            self.model = None
            self._fallback = float(np.mean(y)) if len(y) else 0.0
            return self
        X = np.column_stack([np.log(p), np.log(1 - p)])
        self.model.fit(X, y)
        return self

    def predict(self, probs):
        p = np.clip(np.asarray(probs, dtype=float), _EPS, 1 - _EPS)
        if self.model is None:
            return np.full(len(p), self._fallback, dtype=float)
        X = np.column_stack([np.log(p), np.log(1 - p)])
        return self.model.predict_proba(X)[:, 1]
