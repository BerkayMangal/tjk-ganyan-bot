"""Isotonic regression kalibratörü (non-parametrik, monoton).

Phase 5.2 nüvesi. n≥~200'de tercih edilir (parametrik olmayan, daha esnek).
"""
from __future__ import annotations

from typing import Sequence


class IsotonicCalibrator:
    def __init__(self):
        self._model = None

    def fit(self, raw_probs: Sequence[float], outcomes: Sequence[int]) -> "IsotonicCalibrator":
        from sklearn.isotonic import IsotonicRegression
        self._model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self._model.fit(list(raw_probs), list(outcomes))
        return self

    def predict(self, raw_probs: Sequence[float]) -> list:
        if self._model is None:
            raise RuntimeError("fit() önce çağrılmalı")
        return list(self._model.predict(list(raw_probs)))
