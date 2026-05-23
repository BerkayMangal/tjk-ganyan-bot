"""Platt scaling kalibratörü (logistic, parametrik).

Phase 5.2 nüvesi. Küçük n'de (50-200) isotonic'e göre daha stabil.
"""
from __future__ import annotations

from typing import Sequence


class PlattCalibrator:
    def __init__(self):
        self._model = None

    def fit(self, raw_probs: Sequence[float], outcomes: Sequence[int]) -> "PlattCalibrator":
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        X = np.asarray(list(raw_probs), dtype=float).reshape(-1, 1)
        y = np.asarray(list(outcomes), dtype=int)
        self._model = LogisticRegression()
        self._model.fit(X, y)
        return self

    def predict(self, raw_probs: Sequence[float]) -> list:
        import numpy as np
        if self._model is None:
            raise RuntimeError("fit() önce çağrılmalı")
        X = np.asarray(list(raw_probs), dtype=float).reshape(-1, 1)
        return list(self._model.predict_proba(X)[:, 1])
