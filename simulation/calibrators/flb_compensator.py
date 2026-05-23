"""Phase 5.5 — FLB (Favorite-Longshot Bias) compensator.

TR pazarı bulgusu (Phase 5.3 PART D): favori ≥30% AĞIR overbet, longshot 0-5% underbet
(klasik FLB'nin tersi — "favori-overbet" formu). multiplier(agf) = calib_winrate(agf)/agf
piyasa-bias'ını düzeltir (longshot bonus, favori ceza). Magic number YOK — multiplier
veri-türevli kalibratörden, clamp bucket-corr extremlerinden.

⚠ multiplier `agf` indexli. Backtest'te score≈agf (koherent). Prod'da score=model_prob
(value-tilt; double-count riski) → SHADOW + forward validation (bkz scoring_flow_map A.4).
"""
from __future__ import annotations

from typing import Sequence


class FLBCompensator:
    def __init__(self):
        self._calib = None          # winrate(agf_implied) → 0-1
        self._method = None
        self._clamp = (0.5, 2.0)    # fit'te bucket-corr extremlerinden türetilir

    # ---- fit (CV ile smoothing seçimi) ----
    def fit(self, agf_pcts: Sequence[float], won_flags: Sequence[int],
            n_folds: int = 5, seed: int = 7) -> "FLBCompensator":
        import numpy as np
        x = np.asarray([a / 100.0 for a in agf_pcts], dtype=float)  # agf_implied 0-1
        y = np.asarray(list(won_flags), dtype=int)

        cands = {"raw_bucket": _BucketCalib, "isotonic": _IsoCalib, "platt": _PlattCalib}
        rng = np.random.RandomState(seed)
        idx = rng.permutation(len(x))
        folds = np.array_split(idx, n_folds)
        cv = {}
        for name, cls in cands.items():
            briers = []
            for k in range(n_folds):
                val = folds[k]
                tr = np.concatenate([folds[j] for j in range(n_folds) if j != k])
                m = cls().fit(x[tr], y[tr])
                p = np.asarray(m.predict(x[val]))
                briers.append(float(np.mean((p - y[val]) ** 2)))
            cv[name] = float(np.mean(briers))
        self._method = min(cv, key=cv.get)
        self._cv_brier = cv
        self._calib = cands[self._method]().fit(x, y)

        # clamp = gözlenen bucket-corr extremleri (veri-türevli, magic değil)
        self._clamp = self._bucket_corr_range(x, y)
        return self

    @staticmethod
    def _bucket_corr_range(x, y):
        import numpy as np
        edges = [0, .05, .10, .15, .20, .25, .30, .40, .50, 1.01]
        corrs = []
        for lo, hi in zip(edges, edges[1:]):
            mask = (x >= lo) & (x < hi)
            n = int(mask.sum())
            if n < 30:
                continue
            avg_agf = float(x[mask].mean())
            act = float(y[mask].mean())
            if avg_agf > 0:
                corrs.append(act / avg_agf)
        if not corrs:
            return (0.5, 2.0)
        return (round(min(corrs), 3), round(max(corrs), 3))

    # ---- uygulama ----
    def winrate(self, agf_pct: float) -> float:
        if self._calib is None or agf_pct is None or agf_pct <= 0:
            return 0.0
        return float(self._calib.predict([agf_pct / 100.0])[0])

    def multiplier(self, agf_pct: float) -> float:
        """raw → multiplier = clamp(winrate(agf)/agf, corr_min, corr_max)."""
        if self._calib is None or agf_pct is None or agf_pct <= 0:
            return 1.0
        ai = agf_pct / 100.0
        wr = self.winrate(agf_pct)
        m = wr / ai if ai > 0 else 1.0
        lo, hi = self._clamp
        return float(min(hi, max(lo, m)))

    def compensate(self, raw_value: float, agf_pct: float) -> float:
        if raw_value is None:
            return raw_value
        return float(raw_value) * self.multiplier(agf_pct)


# ---- smoothing adayları (uniform fit/predict arayüzü, agf_implied 0-1) ----
class _IsoCalib:
    def fit(self, x, y):
        from sklearn.isotonic import IsotonicRegression
        self.m = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)
        self.m.fit(list(x), list(y))
        return self

    def predict(self, x):
        return list(self.m.predict(list(x)))


class _PlattCalib:
    def fit(self, x, y):
        import numpy as np
        from sklearn.linear_model import LogisticRegression
        self.m = LogisticRegression()
        self.m.fit(np.asarray(x).reshape(-1, 1), list(y))
        return self

    def predict(self, x):
        import numpy as np
        return list(self.m.predict_proba(np.asarray(x).reshape(-1, 1))[:, 1])


class _BucketCalib:
    _EDGES = [0, .05, .10, .15, .20, .25, .30, .40, .50, 1.01]

    def fit(self, x, y):
        import numpy as np
        x = np.asarray(x); y = np.asarray(y)
        self.rates = {}
        self.global_rate = float(y.mean()) if len(y) else 0.0
        for i, (lo, hi) in enumerate(zip(self._EDGES, self._EDGES[1:])):
            mask = (x >= lo) & (x < hi)
            self.rates[i] = float(y[mask].mean()) if mask.sum() else self.global_rate
        return self

    def _bucket(self, v):
        for i, (lo, hi) in enumerate(zip(self._EDGES, self._EDGES[1:])):
            if lo <= v < hi:
                return i
        return len(self._EDGES) - 2

    def predict(self, x):
        return [self.rates.get(self._bucket(v), self.global_rate) for v in x]
