"""V7 + Sequence model stacking — meta-learner.

Logistic regression meta. Inputs:
  - V7 model_prob (mevcut ranker)
  - sequence strength (lightweight encoder)
  - glicko rating
  - recency gap (forward signal)
  - recovery comeback risk

Output: refined P(top-N) for each horse.

Bu modül V7'yi REPLACE etmez. Onun yanına ek bir "tashih" katmanı.
Stacking modeli kalibrasyon olarak da çalışır.

API
---
- `StackingMeta(weights=None)` — manuel veya backtest-fit weights
- `predict(features)` → refined probability
- `fit(X, y)` → batch fit (numpy varsa daha hızlı, yoksa pure-python)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional


# Default hand-tuned weights (deterministic, no training required).
# These are reasonable priors and will be replaced by `fit()` once
# backtest data is available.
DEFAULT_WEIGHTS = {
    "intercept": -1.5,
    "v7_mp": 4.0,         # mevcut model güçlü ağırlık
    "strength_norm": 0.8, # sequence model
    "glicko_norm": 0.5,
    "recency_gap": 1.2,   # forward signal — Berkay'ın talebi
    "comeback_risk": -0.6,
    "trend_signal": 1.0,
}


def _sigmoid(x: float) -> float:
    if x >= 0:
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass
class StackingMeta:
    """Logistic stacking meta-learner."""
    weights: dict[str, float] = field(default_factory=lambda: dict(DEFAULT_WEIGHTS))

    def predict(self, features: Mapping) -> float:
        """Tek atın feature dict'inden P(top-N)."""
        w = self.weights
        x = w.get("intercept", 0.0)
        # V7 model_prob (0..1 typical, sometimes 0..100)
        mp = features.get("v7_mp")
        if mp is not None:
            mp = float(mp)
            if mp > 1.5:
                mp /= 100.0
            x += w.get("v7_mp", 0.0) * mp
        # Strength: normalize ~ N(100, 30)
        s = features.get("strength")
        if s is not None:
            sn = (float(s) - 100.0) / 30.0
            x += w.get("strength_norm", 0.0) * sn
        # Glicko: normalize ~ N(1500, 200)
        g = features.get("glicko_rating")
        if g is not None:
            gn = (float(g) - 1500.0) / 200.0
            x += w.get("glicko_norm", 0.0) * gn
        # Recency gap: already normalized -1..1
        rg = features.get("recency_gap")
        if rg is not None:
            x += w.get("recency_gap", 0.0) * float(rg)
        # Comeback risk: 0..1
        cr = features.get("comeback_risk")
        if cr is not None:
            x += w.get("comeback_risk", 0.0) * float(cr)
        # Trend: -1..1
        ts = features.get("trend_signal")
        if ts is not None:
            x += w.get("trend_signal", 0.0) * float(ts)
        return _sigmoid(x)

    def predict_race(self, horses_features: Iterable[Mapping]) -> list[float]:
        """Bir yarış için tüm at olasılıkları (normalize edilmez — caller'ın
        işi, çünkü top-N target değişebilir).
        """
        return [self.predict(f) for f in horses_features]

    def fit(self, X: list[Mapping], y: list[int],
            lr: float = 0.05, n_iter: int = 200) -> "StackingMeta":
        """Pure-Python SGD-style logistic fit. Küçük dataset için yeterli.

        `X`: feature dicts list. `y`: 1 = top-N hit, 0 = miss.
        """
        n = len(X)
        if n == 0 or n != len(y):
            return self
        # SGD
        for _ in range(n_iter):
            for xi, yi in zip(X, y):
                pred = self.predict(xi)
                err = yi - pred
                w = self.weights
                w["intercept"] = w.get("intercept", 0.0) + lr * err
                # Update each feature weight
                features_used = {
                    "v7_mp": float(xi.get("v7_mp") or 0) if xi.get("v7_mp") is not None else 0,
                    "strength_norm": ((float(xi.get("strength") or 100) - 100) / 30
                                      if xi.get("strength") is not None else 0),
                    "glicko_norm": ((float(xi.get("glicko_rating") or 1500) - 1500) / 200
                                    if xi.get("glicko_rating") is not None else 0),
                    "recency_gap": float(xi.get("recency_gap") or 0),
                    "comeback_risk": float(xi.get("comeback_risk") or 0),
                    "trend_signal": float(xi.get("trend_signal") or 0),
                }
                for k, v in features_used.items():
                    w[k] = w.get(k, 0.0) + lr * err * v
        return self

    def to_json(self) -> dict:
        return {"weights": dict(self.weights)}

    @classmethod
    def from_json(cls, data: Mapping) -> "StackingMeta":
        return cls(weights=dict(data.get("weights") or DEFAULT_WEIGHTS))
