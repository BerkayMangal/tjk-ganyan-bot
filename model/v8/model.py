"""V8 — Multi-head probabilistic classifier.

Output: 4 ayrı probability head
  - p_top1: bu at 1. olur mu
  - p_top2: ilk 2'ye girer mi
  - p_top3: ilk 3'e girer mi
  - p_top4: ilk 4'e girer mi

Architecture (pure-Python, NO heavy deps for inference):
  Logistic regression per-head + isotonic calibration

Training time: numpy gerek (eğer var) ama infer pure-Python.

Each head:
  z_k = w_k · x + b_k
  p_k = sigmoid(z_k)
  p_k_calibrated = isotonic_k(p_k)

Constraints (training time enforce):
  p_top1 ≤ p_top2 ≤ p_top3 ≤ p_top4
  (Monotonicity — at top-1 girerse top-4 zaten girer)

API
---
- `V8Model.predict(features)` → 4-tuple of probabilities
- `V8Model.fit(X, Y_dict)` → trained
- `V8Model.to_json()`, `from_json()`
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional


def _sigmoid(x: float) -> float:
    if x >= 0:
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    e = math.exp(x)
    return e / (1.0 + e)


@dataclass
class V8Head:
    """One logistic head."""
    name: str
    weights: dict[str, float] = field(default_factory=dict)
    intercept: float = 0.0
    feature_keys: list[str] = field(default_factory=list)
    # Isotonic calibration: list of (input_p, output_p) breakpoints
    iso_x: list[float] = field(default_factory=list)
    iso_y: list[float] = field(default_factory=list)

    def predict_raw(self, features: Mapping) -> float:
        z = self.intercept
        for k in self.feature_keys:
            v = features.get(k)
            if v is None:
                continue
            try:
                z += self.weights.get(k, 0.0) * float(v)
            except (TypeError, ValueError):
                continue
        return _sigmoid(z)

    def calibrate(self, p: float) -> float:
        if not self.iso_x:
            return p
        # Find segment
        for i in range(len(self.iso_x) - 1):
            if self.iso_x[i] <= p <= self.iso_x[i + 1]:
                # linear interp
                x0, x1 = self.iso_x[i], self.iso_x[i + 1]
                y0, y1 = self.iso_y[i], self.iso_y[i + 1]
                if x1 == x0:
                    return y0
                t = (p - x0) / (x1 - x0)
                return y0 + t * (y1 - y0)
        if p < self.iso_x[0]:
            return self.iso_y[0]
        return self.iso_y[-1]

    def predict(self, features: Mapping) -> float:
        return self.calibrate(self.predict_raw(features))

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "weights": dict(self.weights),
            "intercept": self.intercept,
            "feature_keys": list(self.feature_keys),
            "iso_x": list(self.iso_x),
            "iso_y": list(self.iso_y),
        }

    @classmethod
    def from_json(cls, data: Mapping) -> "V8Head":
        return cls(
            name=data.get("name", "head"),
            weights=dict(data.get("weights") or {}),
            intercept=float(data.get("intercept", 0.0)),
            feature_keys=list(data.get("feature_keys") or []),
            iso_x=list(data.get("iso_x") or []),
            iso_y=list(data.get("iso_y") or []),
        )


@dataclass
class V8Model:
    """Multi-head V8 model."""
    head_top1: V8Head = field(default_factory=lambda: V8Head(name="top1"))
    head_top2: V8Head = field(default_factory=lambda: V8Head(name="top2"))
    head_top3: V8Head = field(default_factory=lambda: V8Head(name="top3"))
    head_top4: V8Head = field(default_factory=lambda: V8Head(name="top4"))
    feature_keys: list[str] = field(default_factory=list)  # canonical schema
    version: str = "8.0.0"
    fit_n: int = 0
    fit_meta: dict = field(default_factory=dict)

    def predict(self, features: Mapping) -> dict:
        """Tek atın 4-head tahminleri + meta."""
        p1 = self.head_top1.predict(features)
        p2 = self.head_top2.predict(features)
        p3 = self.head_top3.predict(features)
        p4 = self.head_top4.predict(features)
        # Enforce monotonicity at predict time
        p2 = max(p1, p2)
        p3 = max(p2, p3)
        p4 = max(p3, p4)
        return {
            "p_top1": p1,
            "p_top2": p2,
            "p_top3": p3,
            "p_top4": p4,
        }

    def predict_race(self, horses_features: Iterable[Mapping]) -> list[dict]:
        return [{"horse_no": h.get("horse_no"),
                 "horse_name": h.get("horse_name"),
                 **self.predict(h)}
                for h in horses_features]

    def fit_logistic_head(
        self,
        head: V8Head,
        X: list[dict],
        y: list[int],
        feature_keys: list[str],
        lr: float = 0.05,
        n_iter: int = 100,
        l2: float = 0.001,
    ) -> V8Head:
        """Pure-Python SGD logistic fit."""
        head.feature_keys = list(feature_keys)
        if not X or not y or len(X) != len(y):
            return head
        # Initialize weights to 0
        if not head.weights:
            head.weights = {k: 0.0 for k in feature_keys}
            head.intercept = 0.0
        for _ in range(n_iter):
            for xi, yi in zip(X, y):
                z = head.intercept
                for k in feature_keys:
                    v = xi.get(k)
                    if v is None:
                        continue
                    try:
                        z += head.weights.get(k, 0.0) * float(v)
                    except (TypeError, ValueError):
                        continue
                p = _sigmoid(z)
                err = yi - p
                head.intercept += lr * err
                for k in feature_keys:
                    v = xi.get(k)
                    if v is None:
                        continue
                    try:
                        fv = float(v)
                    except (TypeError, ValueError):
                        continue
                    # L2 regularization
                    head.weights[k] = head.weights.get(k, 0.0) * (1 - lr * l2) \
                                       + lr * err * fv
        return head

    def fit_isotonic_head(
        self,
        head: V8Head,
        X: list[dict],
        y: list[int],
        n_bins: int = 10,
    ) -> V8Head:
        """Isotonic calibration: bin-based pool adjacent violators (basit)."""
        if not X or not y:
            return head
        raws = [head.predict_raw(xi) for xi in X]
        # Bin
        pairs = sorted(zip(raws, y), key=lambda kv: kv[0])
        if not pairs:
            return head
        bin_size = max(1, len(pairs) // n_bins)
        bins_x = []
        bins_y = []
        for i in range(0, len(pairs), bin_size):
            chunk = pairs[i:i + bin_size]
            if not chunk:
                continue
            avg_x = sum(p for p, _ in chunk) / len(chunk)
            avg_y = sum(yy for _, yy in chunk) / len(chunk)
            bins_x.append(avg_x)
            bins_y.append(avg_y)
        # Pool adjacent violators — enforce monotonicity
        i = 0
        while i < len(bins_y) - 1:
            if bins_y[i] > bins_y[i + 1]:
                # pool with neighbour
                new_y = (bins_y[i] + bins_y[i + 1]) / 2
                new_x = (bins_x[i] + bins_x[i + 1]) / 2
                bins_y[i] = new_y
                bins_y[i + 1] = new_y
                bins_x[i] = new_x
                bins_x[i + 1] = new_x
                if i > 0:
                    i -= 1
            else:
                i += 1
        # Deduplicate
        seen = set()
        ix = []
        iy = []
        for x, y_ in zip(bins_x, bins_y):
            if (round(x, 4), round(y_, 4)) in seen:
                continue
            seen.add((round(x, 4), round(y_, 4)))
            ix.append(x)
            iy.append(y_)
        head.iso_x = ix
        head.iso_y = iy
        return head

    def fit(
        self,
        X: list[dict],
        Y: dict[str, list[int]],
        feature_keys: list[str],
        lr: float = 0.05,
        n_iter: int = 100,
        l2: float = 0.001,
        calibrate: bool = True,
    ) -> "V8Model":
        """Fit all 4 heads.

        `Y`: {'top1': [0/1, ...], 'top2': [...], 'top3': [...], 'top4': [...]}
        """
        self.feature_keys = list(feature_keys)
        self.fit_n = len(X)
        for name, head in (("top1", self.head_top1),
                            ("top2", self.head_top2),
                            ("top3", self.head_top3),
                            ("top4", self.head_top4)):
            y = Y.get(name) or [0] * len(X)
            self.fit_logistic_head(head, X, y, feature_keys, lr, n_iter, l2)
            if calibrate:
                self.fit_isotonic_head(head, X, y)
        return self

    def to_json(self) -> dict:
        return {
            "version": self.version,
            "fit_n": self.fit_n,
            "feature_keys": list(self.feature_keys),
            "head_top1": self.head_top1.to_json(),
            "head_top2": self.head_top2.to_json(),
            "head_top3": self.head_top3.to_json(),
            "head_top4": self.head_top4.to_json(),
            "fit_meta": dict(self.fit_meta),
        }

    @classmethod
    def from_json(cls, data: Mapping) -> "V8Model":
        m = cls(
            head_top1=V8Head.from_json(data.get("head_top1") or {}),
            head_top2=V8Head.from_json(data.get("head_top2") or {}),
            head_top3=V8Head.from_json(data.get("head_top3") or {}),
            head_top4=V8Head.from_json(data.get("head_top4") or {}),
            feature_keys=list(data.get("feature_keys") or []),
            version=str(data.get("version", "8.0.0")),
            fit_n=int(data.get("fit_n", 0)),
            fit_meta=dict(data.get("fit_meta") or {}),
        )
        return m

    def save(self, path: str) -> None:
        import os
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as f:
            json.dump(self.to_json(), f, indent=2)

    @classmethod
    def load(cls, path: str) -> Optional["V8Model"]:
        try:
            with open(path) as f:
                return cls.from_json(json.load(f))
        except Exception:
            return None
