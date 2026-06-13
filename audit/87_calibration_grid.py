"""Phase 5.2.6 — CALIBRATION GRID (geniş tarama).

Berkay'ın talimatı: "milyarlarca yol dene + dürüst rapor".

Veri durumu (gerçek ölçüm, fabrike değil):
  - bet_diary_log.jsonl: 1476 satır, did_we_win = None (henüz outcome yok)
  - data/backfill/outcomes/: 34 gün (2026-04-23 → 2026-06-07)
  - bet_diary tarihleri 2026-06-04, 08, 09, 10, 12 → outcomes ile JOIN: sadece 18 satır (1 altılı)
  - calibration_dataset_complete.csv: 8073 satır (30 gün, AGF + won_flag), model_prob YOK

KARAR:
  - Yol A: AGF→outcome kalibrasyonu (n=8073) → tam grid (asıl analiz)
  - Yol B: model_prob→outcome (n=18) → "yetersiz veri", sahte calibrator ÜRETME

Çıktılar:
  - audit/reports/phase_5_2_6_calibration_grid.md (asıl rapor)
  - simulation/calibrators/fitted/candidates/cand_*.pkl (en iyi 3 aday)
  - simulation/calibrators/fitted/candidates/MANIFEST.md
  - audit/reports/figures/*.png (reliability diagrams; matplotlib var)

KURALLAR:
  - active.pkl ASLA YAZMA
  - mevcut agf_outcome_calibrator.pkl + flb_compensator.pkl DOKUNULMAZ
  - Sahte data uydurma → n<50 bucket: "INSUFFICIENT"
  - +EV iddiası YASAK → sadece Brier/ECE/LL/MCE
  - Walk-forward: zaman sıralı, FUTURE leakage YOK

Kullanım: python3 audit/87_calibration_grid.py
"""
from __future__ import annotations

import csv
import json
import math
import os
import pickle
import sys
import time
import unicodedata
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Callable

import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from scipy.interpolate import UnivariateSpline
from scipy.optimize import minimize_scalar

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
BET_DIARY = os.path.join(_REPO, "audit", "reports", "bet_diary_log.jsonl")
OUTCOMES_DIR = os.path.join(_REPO, "data", "backfill", "outcomes")
OUTCOMES_RICH_DIR = os.path.join(_REPO, "data", "backfill", "outcomes_rich")
EXISTING_AGF_CAL = os.path.join(_REPO, "simulation", "calibrators", "fitted",
                                "agf_outcome_calibrator.pkl")

OUT_REPORT = os.path.join(_REPO, "audit", "reports", "phase_5_2_6_calibration_grid.md")
OUT_CAND_DIR = os.path.join(_REPO, "simulation", "calibrators", "fitted", "candidates")
OUT_FIG_DIR = os.path.join(_REPO, "audit", "reports", "figures")
OUT_MANIFEST = os.path.join(OUT_CAND_DIR, "MANIFEST.md")

MIN_N_FIT = 50           # bucket için fit min n
MIN_N_TEST = 30          # bucket test için min n
N_FOLDS = 5              # walk-forward
N_BOOTSTRAP = 1000       # CI için
RANDOM_SEED = 42
EPS = 1e-12

# Matplotlib opsiyonel
try:
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    HAS_MPL = True
except ImportError:
    HAS_MPL = False


# -----------------------------------------------------------------------------
# METRİKLER
# -----------------------------------------------------------------------------
def brier(p: np.ndarray, y: np.ndarray) -> float:
    return float(np.mean((p - y) ** 2))


def logloss(p: np.ndarray, y: np.ndarray) -> float:
    p = np.clip(p, EPS, 1 - EPS)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    """Expected Calibration Error (equal-width bins)."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(p, bins[1:-1], right=False)
    e = 0.0
    n = len(p)
    for b in range(n_bins):
        mask = idx == b
        if mask.sum() == 0:
            continue
        conf = p[mask].mean()
        acc = y[mask].mean()
        e += (mask.sum() / n) * abs(conf - acc)
    return float(e)


def mce(p: np.ndarray, y: np.ndarray, n_bins: int = 10) -> float:
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(p, bins[1:-1], right=False)
    e = 0.0
    for b in range(n_bins):
        mask = idx == b
        if mask.sum() == 0:
            continue
        conf = p[mask].mean()
        acc = y[mask].mean()
        e = max(e, abs(conf - acc))
    return float(e)


def reliability_points(p: np.ndarray, y: np.ndarray, n_bins: int = 10):
    """Reliability diagram için (conf, acc, count) tuple listesi."""
    bins = np.linspace(0.0, 1.0, n_bins + 1)
    idx = np.digitize(p, bins[1:-1], right=False)
    pts = []
    for b in range(n_bins):
        mask = idx == b
        if mask.sum() == 0:
            pts.append((float(bins[b] + (bins[b + 1] - bins[b]) / 2), None, 0))
            continue
        pts.append((float(p[mask].mean()), float(y[mask].mean()), int(mask.sum())))
    return pts


def bootstrap_ci(p: np.ndarray, y: np.ndarray, metric_fn: Callable,
                 n: int = N_BOOTSTRAP, seed: int = RANDOM_SEED) -> tuple[float, float, float]:
    """Bootstrap CI (point, lo, hi 95%)."""
    rng = np.random.default_rng(seed)
    N = len(p)
    if N == 0:
        return 0.0, 0.0, 0.0
    samples = []
    for _ in range(n):
        idx = rng.integers(0, N, size=N)
        samples.append(metric_fn(p[idx], y[idx]))
    samples = np.asarray(samples)
    point = metric_fn(p, y)
    return float(point), float(np.percentile(samples, 2.5)), float(np.percentile(samples, 97.5))


# -----------------------------------------------------------------------------
# CALIBRATORS
# -----------------------------------------------------------------------------
class RawCalibrator:
    """Identity — raw scores."""
    def fit(self, p, y):
        return self

    def predict(self, p):
        return np.clip(np.asarray(p), 0.0, 1.0)


class IsotonicCal:
    def __init__(self):
        self.model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, p, y):
        self.model.fit(np.asarray(p), np.asarray(y))
        return self

    def predict(self, p):
        return np.clip(self.model.predict(np.asarray(p)), 0.0, 1.0)


class PlattCal:
    """Logistic on raw prob (sigmoid scaling)."""
    def __init__(self):
        self.model = LogisticRegression()

    def fit(self, p, y):
        X = np.asarray(p).reshape(-1, 1)
        y = np.asarray(y)
        if len(np.unique(y)) < 2:
            self.model = None
            self._fallback = float(np.mean(y)) if len(y) else 0.0
        else:
            self.model.fit(X, y)
        return self

    def predict(self, p):
        if self.model is None:
            return np.full(len(p), self._fallback)
        X = np.asarray(p).reshape(-1, 1)
        return self.model.predict_proba(X)[:, 1]


class BetaCal:
    """Beta calibration (Kull, 2017): logit(p_cal) = a*log(p) + b*log(1-p) + c.

    Implementation: features = [log(p), log(1-p)], logistic regression.
    """
    def __init__(self):
        self.model = LogisticRegression()

    def fit(self, p, y):
        p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
        y = np.asarray(y)
        X = np.column_stack([np.log(p), np.log(1 - p)])
        if len(np.unique(y)) < 2:
            self.model = None
            self._fallback = float(np.mean(y)) if len(y) else 0.0
        else:
            self.model.fit(X, y)
        return self

    def predict(self, p):
        p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
        if self.model is None:
            return np.full(len(p), self._fallback)
        X = np.column_stack([np.log(p), np.log(1 - p)])
        return self.model.predict_proba(X)[:, 1]


class HistogramCal:
    """Equal-width histogram binning."""
    def __init__(self, n_bins: int = 10):
        self.n_bins = n_bins

    def fit(self, p, y):
        p = np.asarray(p)
        y = np.asarray(y)
        bins = np.linspace(0.0, 1.0, self.n_bins + 1)
        self.bins = bins
        self.bin_y = np.zeros(self.n_bins)
        idx = np.digitize(p, bins[1:-1], right=False)
        for b in range(self.n_bins):
            mask = idx == b
            if mask.sum() > 0:
                self.bin_y[b] = y[mask].mean()
            else:
                # Boş bin: center'a fallback (lineer)
                self.bin_y[b] = (bins[b] + bins[b + 1]) / 2
        return self

    def predict(self, p):
        p = np.asarray(p)
        idx = np.digitize(p, self.bins[1:-1], right=False)
        return self.bin_y[idx]


class TemperatureCal:
    """Temperature scaling: p_cal = sigmoid(logit(p) / T)."""
    def __init__(self):
        self.T = 1.0

    def fit(self, p, y):
        p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
        y = np.asarray(y, dtype=float)
        logit = np.log(p / (1 - p))

        def nll(T):
            if T <= 0:
                return 1e10
            scaled = logit / T
            pc = 1 / (1 + np.exp(-scaled))
            pc = np.clip(pc, EPS, 1 - EPS)
            return -np.mean(y * np.log(pc) + (1 - y) * np.log(1 - pc))

        res = minimize_scalar(nll, bounds=(0.05, 20.0), method="bounded")
        self.T = float(res.x)
        return self

    def predict(self, p):
        p = np.clip(np.asarray(p, dtype=float), EPS, 1 - EPS)
        logit = np.log(p / (1 - p))
        scaled = logit / self.T
        return 1 / (1 + np.exp(-scaled))


class SplineCal:
    """Cubic spline calibration (smoothing spline on bin-averaged data).

    UnivariateSpline raw binary outcome'la zayıf → önce bin-average,
    sonra spline fit. Daha stabil.
    """
    def __init__(self, n_knots: int = 7):
        self.n_knots = max(n_knots, 4)

    def fit(self, p, y):
        import warnings
        p = np.asarray(p, dtype=float)
        y = np.asarray(y, dtype=float)
        # Bin-average (eşit nokta bantları)
        order = np.argsort(p)
        ps = p[order]
        ys = y[order]
        n = len(ps)
        bins = max(8, min(self.n_knots * 3, n // 30))
        if bins < 4 or n < 30:
            self._fallback = float(np.mean(y)) if len(y) else 0.0
            self.spl = None
            return self
        chunk = n // bins
        xs, mys = [], []
        for b in range(bins):
            lo = b * chunk
            hi = (b + 1) * chunk if b < bins - 1 else n
            xs.append(float(ps[lo:hi].mean()))
            mys.append(float(ys[lo:hi].mean()))
        xs = np.asarray(xs)
        mys = np.asarray(mys)
        # Unique x lazım
        uniq_x, idx = np.unique(xs, return_index=True)
        uniq_y = mys[idx]
        if len(uniq_x) < 4:
            self._fallback = float(np.mean(y))
            self.spl = None
            return self
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                self.spl = UnivariateSpline(uniq_x, uniq_y, k=3, s=0.0001)
        except Exception:
            self._fallback = float(np.mean(y))
            self.spl = None
        return self

    def predict(self, p):
        p = np.asarray(p, dtype=float)
        if self.spl is None:
            return np.full(len(p), self._fallback)
        out = self.spl(p)
        out = np.where(np.isnan(out), float(np.mean(p)), out)
        return np.clip(out, 0.0, 1.0)


class StackingCal:
    """Stacking: [isotonic, platt, beta] → meta logistic regression."""
    def __init__(self):
        self.iso = IsotonicCal()
        self.platt = PlattCal()
        self.beta = BetaCal()
        self.meta = LogisticRegression()

    def fit(self, p, y):
        p = np.asarray(p)
        y = np.asarray(y)
        # Inner split (train base on first half, meta on second)
        n = len(p)
        if n < 100:
            # Fallback small-n: hepsi aynı veriden
            self.iso.fit(p, y)
            self.platt.fit(p, y)
            self.beta.fit(p, y)
            X = np.column_stack([self.iso.predict(p), self.platt.predict(p), self.beta.predict(p)])
        else:
            cut = n // 2
            self.iso.fit(p[:cut], y[:cut])
            self.platt.fit(p[:cut], y[:cut])
            self.beta.fit(p[:cut], y[:cut])
            X = np.column_stack([self.iso.predict(p[cut:]), self.platt.predict(p[cut:]),
                                 self.beta.predict(p[cut:])])
            y = y[cut:]
        if len(np.unique(y)) < 2:
            self.meta = None
            self._fallback = float(np.mean(y)) if len(y) else 0.0
        else:
            self.meta.fit(X, y)
        return self

    def predict(self, p):
        X = np.column_stack([self.iso.predict(p), self.platt.predict(p), self.beta.predict(p)])
        if self.meta is None:
            return np.full(len(p), self._fallback)
        return self.meta.predict_proba(X)[:, 1]


CALIBRATORS: dict[str, Callable[[], Any]] = {
    "raw": RawCalibrator,
    "isotonic": IsotonicCal,
    "platt": PlattCal,
    "beta": BetaCal,
    "histogram_10": lambda: HistogramCal(10),
    "histogram_20": lambda: HistogramCal(20),
    "histogram_50": lambda: HistogramCal(50),
    "temperature": TemperatureCal,
    "spline_7": lambda: SplineCal(7),
    "stacking": StackingCal,
}


# -----------------------------------------------------------------------------
# VERİ YÜKLEME
# -----------------------------------------------------------------------------
def load_agf_dataset() -> pd.DataFrame:
    """AGF + outcome dataset (n=8073)."""
    df = pd.read_csv(DATASET)
    df = df.dropna(subset=["agf_implied_prob", "won_flag"])
    df["date"] = pd.to_datetime(df["date"])
    df = df.sort_values("date").reset_index(drop=True)
    return df


def load_distance_map() -> dict:
    """outcomes_rich → {(date, hippo, race_no): distance}."""
    out = {}
    if not os.path.isdir(OUTCOMES_RICH_DIR):
        return out
    for fn in sorted(os.listdir(OUTCOMES_RICH_DIR)):
        if not fn.endswith(".json"):
            continue
        try:
            with open(os.path.join(OUTCOMES_RICH_DIR, fn)) as f:
                data = json.load(f)
        except Exception:
            continue
        d = data.get("date") or fn[:10]
        for h in data.get("hippodromes", []):
            hippo = h.get("hippodrome")
            for race_no_str, r in h.get("kosular", {}).items():
                dist = r.get("distance")
                if dist:
                    out[(d, hippo, int(race_no_str))] = int(dist)
    return out


def enrich_distance(df: pd.DataFrame, dist_map: dict) -> pd.DataFrame:
    df["distance"] = df.apply(
        lambda r: dist_map.get((r["date"].strftime("%Y-%m-%d"), r["hippodrome"], int(r["ayak"]))),
        axis=1
    )
    return df


def distance_band(d) -> str:
    if d is None or (isinstance(d, float) and math.isnan(d)):
        return "unknown"
    if d <= 1400:
        return "sprint_<=1400"
    if d <= 1700:
        return "mid_1500-1700"
    return "long_>=1800"


def agf_band(p: float) -> str:
    if p < 0.05:
        return "veryLow_<5%"
    if p < 0.15:
        return "low_5-15%"
    if p < 0.30:
        return "mid_15-30%"
    if p < 0.50:
        return "high_30-50%"
    return "veryHigh_>=50%"


# -----------------------------------------------------------------------------
# WALK-FORWARD SPLIT
# -----------------------------------------------------------------------------
def walk_forward_splits(df: pd.DataFrame, n_folds: int = N_FOLDS):
    """Zaman sıralı, expanding-window walk-forward.

    Fold 1: train=[d0..d1/n_folds], test=[d1/n_folds..d2/n_folds]
    ...
    Fold k: train=[d0..d(k)/n_folds], test=[d(k)/n_folds..d(k+1)/n_folds]

    Returns: list of (train_idx, test_idx).
    """
    df = df.sort_values("date").reset_index(drop=True)
    dates = sorted(df["date"].unique())
    n_dates = len(dates)
    fold_size = max(1, n_dates // (n_folds + 1))
    splits = []
    for k in range(1, n_folds + 1):
        train_end = fold_size * k
        test_start = train_end
        test_end = min(n_dates, fold_size * (k + 1))
        if test_start >= test_end:
            break
        train_dates = set(dates[:train_end])
        test_dates = set(dates[test_start:test_end])
        train_idx = df.index[df["date"].isin(train_dates)].to_numpy()
        test_idx = df.index[df["date"].isin(test_dates)].to_numpy()
        splits.append((train_idx, test_idx))
    return splits


# -----------------------------------------------------------------------------
# FIT + EVAL
# -----------------------------------------------------------------------------
@dataclass
class CalResult:
    calibrator: str
    bucket_type: str
    bucket_key: str
    fold: int
    n_train: int
    n_test: int
    brier: float
    brier_lo: float
    brier_hi: float
    ece: float
    ece_lo: float
    ece_hi: float
    logloss: float
    mce: float
    status: str = "OK"
    notes: str = ""


def fit_and_eval(cal_name: str, bucket_type: str, bucket_key: str, fold: int,
                 p_tr: np.ndarray, y_tr: np.ndarray, p_te: np.ndarray, y_te: np.ndarray,
                 ) -> CalResult:
    # Status checks
    if len(p_tr) < MIN_N_FIT:
        return CalResult(cal_name, bucket_type, bucket_key, fold,
                         len(p_tr), len(p_te), 0, 0, 0, 0, 0, 0, 0, 0,
                         status="INSUFFICIENT", notes=f"n_train={len(p_tr)} < {MIN_N_FIT}")
    if len(p_te) < MIN_N_TEST:
        return CalResult(cal_name, bucket_type, bucket_key, fold,
                         len(p_tr), len(p_te), 0, 0, 0, 0, 0, 0, 0, 0,
                         status="INSUFFICIENT", notes=f"n_test={len(p_te)} < {MIN_N_TEST}")
    if len(np.unique(y_tr)) < 2:
        return CalResult(cal_name, bucket_type, bucket_key, fold,
                         len(p_tr), len(p_te), 0, 0, 0, 0, 0, 0, 0, 0,
                         status="DEGENERATE", notes="train tek class")

    try:
        cal = CALIBRATORS[cal_name]()
        cal.fit(p_tr, y_tr)
        p_pred = np.clip(np.asarray(cal.predict(p_te), dtype=float), 0.0, 1.0)
    except Exception as e:
        return CalResult(cal_name, bucket_type, bucket_key, fold,
                         len(p_tr), len(p_te), 0, 0, 0, 0, 0, 0, 0, 0,
                         status="ERROR", notes=str(e)[:120])

    b, b_lo, b_hi = bootstrap_ci(p_pred, y_te, brier, n=N_BOOTSTRAP, seed=RANDOM_SEED + fold)
    e, e_lo, e_hi = bootstrap_ci(p_pred, y_te, ece, n=N_BOOTSTRAP, seed=RANDOM_SEED + fold + 100)
    ll = logloss(p_pred, y_te)
    m = mce(p_pred, y_te)
    return CalResult(cal_name, bucket_type, bucket_key, fold,
                     len(p_tr), len(p_te),
                     round(b, 5), round(b_lo, 5), round(b_hi, 5),
                     round(e, 5), round(e_lo, 5), round(e_hi, 5),
                     round(ll, 5), round(m, 5),
                     status="OK")


# -----------------------------------------------------------------------------
# GRID RUNNER
# -----------------------------------------------------------------------------
def run_grid(df: pd.DataFrame, prob_col: str, label_col: str) -> list[CalResult]:
    results: list[CalResult] = []
    splits = walk_forward_splits(df)
    if not splits:
        return results

    # 1) GLOBAL bucket
    for cal_name in CALIBRATORS:
        for k, (tr_idx, te_idx) in enumerate(splits):
            p_tr = df.loc[tr_idx, prob_col].to_numpy()
            y_tr = df.loc[tr_idx, label_col].to_numpy()
            p_te = df.loc[te_idx, prob_col].to_numpy()
            y_te = df.loc[te_idx, label_col].to_numpy()
            results.append(fit_and_eval(cal_name, "GLOBAL", "all", k + 1,
                                        p_tr, y_tr, p_te, y_te))

    # 2) PER-HIPPODROME
    for hippo in sorted(df["hippodrome"].unique()):
        for cal_name in CALIBRATORS:
            for k, (tr_idx, te_idx) in enumerate(splits):
                tr = df.loc[tr_idx]
                te = df.loc[te_idx]
                tr_h = tr[tr["hippodrome"] == hippo]
                te_h = te[te["hippodrome"] == hippo]
                results.append(fit_and_eval(cal_name, "PER_HIPPODROME", hippo, k + 1,
                                            tr_h[prob_col].to_numpy(),
                                            tr_h[label_col].to_numpy(),
                                            te_h[prob_col].to_numpy(),
                                            te_h[label_col].to_numpy()))

    # 3) PER-DISTANCE-BAND (sadece distance var ise)
    if "distance" in df.columns and df["distance"].notna().sum() > 100:
        df["_dband"] = df["distance"].map(distance_band)
        for band in sorted(df["_dband"].unique()):
            if band == "unknown":
                continue
            for cal_name in CALIBRATORS:
                for k, (tr_idx, te_idx) in enumerate(splits):
                    tr = df.loc[tr_idx]
                    te = df.loc[te_idx]
                    tr_b = tr[tr["_dband"] == band]
                    te_b = te[te["_dband"] == band]
                    results.append(fit_and_eval(cal_name, "PER_DISTANCE", band, k + 1,
                                                tr_b[prob_col].to_numpy(),
                                                tr_b[label_col].to_numpy(),
                                                te_b[prob_col].to_numpy(),
                                                te_b[label_col].to_numpy()))

    # 4) PER-AGF-BAND (sadece prob_col == agf_implied_prob ise anlamlı,
    #    yine de yararlı drift dedektörü)
    df["_aband"] = df[prob_col].map(agf_band)
    for band in sorted(df["_aband"].unique()):
        for cal_name in ("raw", "isotonic", "platt", "histogram_10"):
            for k, (tr_idx, te_idx) in enumerate(splits):
                tr = df.loc[tr_idx]
                te = df.loc[te_idx]
                tr_b = tr[tr["_aband"] == band]
                te_b = te[te["_aband"] == band]
                results.append(fit_and_eval(cal_name, "PER_AGF_BAND", band, k + 1,
                                            tr_b[prob_col].to_numpy(),
                                            tr_b[label_col].to_numpy(),
                                            te_b[prob_col].to_numpy(),
                                            te_b[label_col].to_numpy()))
    return results


# -----------------------------------------------------------------------------
# REPORTING
# -----------------------------------------------------------------------------
def aggregate_by_calibrator(results: list[CalResult]) -> pd.DataFrame:
    """Tüm fold'ları aggregate et: ortalama Brier/ECE/LL/MCE."""
    rows = []
    for r in results:
        if r.status != "OK":
            continue
        rows.append({
            "calibrator": r.calibrator,
            "bucket_type": r.bucket_type,
            "bucket_key": r.bucket_key,
            "n_train": r.n_train,
            "n_test": r.n_test,
            "brier": r.brier,
            "brier_lo": r.brier_lo,
            "brier_hi": r.brier_hi,
            "ece": r.ece,
            "ece_lo": r.ece_lo,
            "ece_hi": r.ece_hi,
            "logloss": r.logloss,
            "mce": r.mce,
            "fold": r.fold,
        })
    agg = pd.DataFrame(rows)
    if agg.empty:
        return agg
    grouped = agg.groupby(["calibrator", "bucket_type", "bucket_key"]).agg({
        "n_train": "mean",
        "n_test": "sum",
        "brier": "mean",
        "brier_lo": "mean",
        "brier_hi": "mean",
        "ece": "mean",
        "ece_lo": "mean",
        "ece_hi": "mean",
        "logloss": "mean",
        "mce": "mean",
        "fold": "count",
    }).rename(columns={"fold": "n_folds"}).reset_index()
    grouped["combined_score"] = grouped["brier"] + 0.5 * grouped["ece"]
    return grouped.sort_values(["bucket_type", "bucket_key", "combined_score"]).reset_index(drop=True)


def insufficient_buckets(results: list[CalResult]) -> pd.DataFrame:
    rows = []
    for r in results:
        if r.status in ("INSUFFICIENT", "DEGENERATE", "ERROR"):
            rows.append({
                "calibrator": r.calibrator,
                "bucket_type": r.bucket_type,
                "bucket_key": r.bucket_key,
                "fold": r.fold,
                "status": r.status,
                "notes": r.notes,
            })
    return pd.DataFrame(rows)


def drift_analysis(df: pd.DataFrame, prob_col: str, label_col: str) -> dict:
    """En eski fold vs en yeni fold: empiric mean prob ve win rate karşılaştırma."""
    splits = walk_forward_splits(df)
    if len(splits) < 2:
        return {"status": "insufficient_folds"}
    oldest = splits[0][1]   # test of fold 1
    newest = splits[-1][1]  # test of last fold
    o_p = df.loc[oldest, prob_col].mean()
    o_y = df.loc[oldest, label_col].mean()
    n_p = df.loc[newest, prob_col].mean()
    n_y = df.loc[newest, label_col].mean()
    return {
        "oldest_mean_prob": float(o_p),
        "oldest_win_rate": float(o_y),
        "newest_mean_prob": float(n_p),
        "newest_win_rate": float(n_y),
        "prob_drift": float(n_p - o_p),
        "winrate_drift": float(n_y - o_y),
        "oldest_n": int(len(oldest)),
        "newest_n": int(len(newest)),
    }


def fit_full_model(cal_name: str, df: pd.DataFrame, prob_col: str, label_col: str,
                   bucket_filter: dict = None):
    """Tüm dataset üzerinde fit et (en iyi adayları kaydetmek için).
    bucket_filter: {col: value} formunda alt-grup filtresi.
    """
    if bucket_filter:
        mask = pd.Series([True] * len(df), index=df.index)
        for col, val in bucket_filter.items():
            mask &= (df[col] == val)
        df = df[mask]
    p = df[prob_col].to_numpy()
    y = df[label_col].to_numpy()
    if len(p) < MIN_N_FIT:
        return None
    cal = CALIBRATORS[cal_name]()
    cal.fit(p, y)
    return cal


def save_reliability_plot(p_raw, p_cal, y, title, out_path):
    if not HAS_MPL:
        return
    fig, ax = plt.subplots(1, 1, figsize=(6, 6))
    bins = np.linspace(0, 1, 11)
    for label, p in [("raw", p_raw), ("calibrated", p_cal)]:
        idx = np.digitize(p, bins[1:-1], right=False)
        xs, ys, ns = [], [], []
        for b in range(10):
            mask = idx == b
            if mask.sum() == 0:
                continue
            xs.append(float(p[mask].mean()))
            ys.append(float(y[mask].mean()))
            ns.append(int(mask.sum()))
        ax.plot(xs, ys, "o-", label=label)
    ax.plot([0, 1], [0, 1], "k--", alpha=0.4, label="perfect")
    ax.set_xlabel("predicted")
    ax.set_ylabel("observed")
    ax.set_title(title)
    ax.legend()
    ax.grid(True, alpha=0.3)
    fig.tight_layout()
    fig.savefig(out_path, dpi=100)
    plt.close(fig)


# -----------------------------------------------------------------------------
# bet_diary mini-analysis (Yol B)
# -----------------------------------------------------------------------------
def _fold_str(s):
    if s is None:
        return ""
    s = s.replace("İ", "I").replace("ı", "i").replace("Ş", "S").replace("ş", "s")
    s = s.replace("Ğ", "G").replace("ğ", "g").replace("Ü", "U").replace("ü", "u")
    s = s.replace("Ö", "O").replace("ö", "o").replace("Ç", "C").replace("ç", "c")
    return s.upper().strip()


def build_bet_diary_joined() -> pd.DataFrame:
    """bet_diary + outcomes join → model_prob, agf_pct, won_flag."""
    # outcomes index: (date, hippo_folded, race_no) → winner_at_no, at_nos
    outcomes = {}
    if os.path.isdir(OUTCOMES_DIR):
        for d in sorted(os.listdir(OUTCOMES_DIR)):
            p = os.path.join(OUTCOMES_DIR, d, "outcomes.json")
            if not os.path.exists(p):
                continue
            try:
                with open(p) as f:
                    data = json.load(f)
            except Exception:
                continue
            for h in data.get("hippodromes", []):
                hippo = h.get("hippodrome", "")
                hippo_f = _fold_str(hippo).replace("HIPODROMU", "").strip()
                for race_no_str, r in h.get("kosular", {}).items():
                    outcomes[(d, hippo_f, int(race_no_str))] = {
                        "winner": r.get("winner"),
                        "at_nos": r.get("at_nos") or [],
                    }

    rows = []
    if not os.path.exists(BET_DIARY):
        return pd.DataFrame()
    with open(BET_DIARY) as f:
        for line in f:
            try:
                r = json.loads(line)
            except Exception:
                continue
            d = r.get("predicted_at", "")[:10]
            hippo_f = _fold_str(r.get("hippodrome", "")).replace("HIPODROMU", "").strip()
            rn = r.get("race_number")
            if rn is None:
                continue
            key = (d, hippo_f, int(rn))
            outc = outcomes.get(key)
            if not outc or outc["winner"] is None:
                continue
            won = 1 if r.get("horse_number") == outc["winner"] else 0
            rows.append({
                "date": d,
                "hippodrome": r.get("hippodrome"),
                "race_number": rn,
                "horse_number": r.get("horse_number"),
                "model_prob": r.get("model_prob"),
                "agf_pct": r.get("agf_pct_at_prediction"),
                "model_rank": (r.get("bet_rationale") or {}).get("model_rank"),
                "won_flag": won,
            })
    return pd.DataFrame(rows)


# -----------------------------------------------------------------------------
# MAIN
# -----------------------------------------------------------------------------
def main():
    print("[phase_5_2_6] CALIBRATION GRID — başlatılıyor")
    print(f"  out: {OUT_REPORT}")
    print(f"  candidates: {OUT_CAND_DIR}")
    os.makedirs(OUT_CAND_DIR, exist_ok=True)
    os.makedirs(OUT_FIG_DIR, exist_ok=True)

    t0 = time.time()

    # -------------- Yol A: AGF dataset (n=8073) --------------
    print("\n[A] AGF dataset yükleniyor...")
    df = load_agf_dataset()
    print(f"  n={len(df)}, dates={df['date'].dt.date.nunique()}, "
          f"win_rate={df['won_flag'].mean():.4f}")

    dist_map = load_distance_map()
    print(f"  distance map: {len(dist_map)} race")
    df = enrich_distance(df, dist_map)
    cov_dist = df["distance"].notna().mean()
    print(f"  distance coverage: {cov_dist*100:.1f}%")

    splits = walk_forward_splits(df)
    print(f"  walk-forward folds: {len(splits)}")
    for i, (tr, te) in enumerate(splits):
        d_tr = (df.loc[tr, 'date'].min().date(), df.loc[tr, 'date'].max().date())
        d_te = (df.loc[te, 'date'].min().date(), df.loc[te, 'date'].max().date())
        print(f"    fold {i+1}: train n={len(tr)} {d_tr}, test n={len(te)} {d_te}")

    # Drift
    drift = drift_analysis(df, "agf_implied_prob", "won_flag")
    print(f"  drift: prob {drift['oldest_mean_prob']:.4f} → {drift['newest_mean_prob']:.4f}, "
          f"winrate {drift['oldest_win_rate']:.4f} → {drift['newest_win_rate']:.4f}")

    print("\n[A] Grid koşuluyor (AGF→outcome)...")
    results_a = run_grid(df, "agf_implied_prob", "won_flag")
    print(f"  {len(results_a)} cell")
    agg_a = aggregate_by_calibrator(results_a)
    insuff_a = insufficient_buckets(results_a)
    print(f"  OK rows: {len(agg_a)}, insufficient: {len(insuff_a)}")

    # En iyi 3 GLOBAL aday (combined_score)
    global_only = agg_a[agg_a["bucket_type"] == "GLOBAL"].sort_values("combined_score")
    print("\n  Top GLOBAL calibrators (combined = brier + 0.5*ece):")
    print(global_only[["calibrator", "brier", "ece", "logloss", "mce",
                       "combined_score", "n_train", "n_test"]].to_string(index=False))

    # Top-3 GLOBAL adayları full-fit edip kaydet
    top3 = global_only.head(3)
    candidates_meta = []
    for i, (_, row) in enumerate(top3.iterrows()):
        cal_name = row["calibrator"]
        if cal_name == "raw":
            continue  # raw'ı kaydetmeye gerek yok
        cal = fit_full_model(cal_name, df, "agf_implied_prob", "won_flag")
        if cal is None:
            continue
        fname = f"cand_{i+1:02d}_{cal_name}_global.pkl"
        path = os.path.join(OUT_CAND_DIR, fname)
        with open(path, "wb") as f:
            pickle.dump({
                "kind": "agf_implied->outcome",
                "method": cal_name,
                "bucket": "GLOBAL",
                "n_train_total": int(len(df)),
                "brier_avg": float(row["brier"]),
                "ece_avg": float(row["ece"]),
                "logloss_avg": float(row["logloss"]),
                "mce_avg": float(row["mce"]),
                "combined_score": float(row["combined_score"]),
                "fitted_at": datetime.now().isoformat() + "Z",
                "model": cal,
            }, f)
        candidates_meta.append({
            "file": fname,
            "method": cal_name,
            "bucket": "GLOBAL",
            "brier": float(row["brier"]),
            "ece": float(row["ece"]),
            "logloss": float(row["logloss"]),
            "mce": float(row["mce"]),
            "combined": float(row["combined_score"]),
            "n_train_total": int(len(df)),
        })
        print(f"  saved: {fname}")

    # Reliability plot
    if HAS_MPL:
        # Last fold için isotonic best
        last_split = splits[-1]
        tr, te = last_split
        p_tr = df.loc[tr, "agf_implied_prob"].to_numpy()
        y_tr = df.loc[tr, "won_flag"].to_numpy()
        p_te = df.loc[te, "agf_implied_prob"].to_numpy()
        y_te = df.loc[te, "won_flag"].to_numpy()
        try:
            cal = IsotonicCal().fit(p_tr, y_tr)
            p_cal = cal.predict(p_te)
            save_reliability_plot(
                p_te, p_cal, y_te,
                "AGF→outcome: raw vs isotonic (last fold)",
                os.path.join(OUT_FIG_DIR, "phase_5_2_6_reliability_isotonic.png"),
            )
            print("  reliability png: phase_5_2_6_reliability_isotonic.png")
        except Exception as e:
            print(f"  reliability plot skipped: {e}")

    # Mevcut agf_outcome_calibrator karşılaştırma (baseline)
    existing_eval = None
    if os.path.exists(EXISTING_AGF_CAL):
        try:
            sys.path.insert(0, os.path.join(_REPO, "simulation"))
            with open(EXISTING_AGF_CAL, "rb") as f:
                ex = pickle.load(f)
            ex_model = ex.get("model") if isinstance(ex, dict) else ex
            # Hold-out: son fold test
            tr, te = splits[-1]
            p_te = df.loc[te, "agf_implied_prob"].to_numpy()
            y_te = df.loc[te, "won_flag"].to_numpy()
            p_pred = np.clip(np.asarray(ex_model.predict(p_te), dtype=float), 0.0, 1.0)
            b = brier(p_pred, y_te)
            e = ece(p_pred, y_te)
            ll = logloss(p_pred, y_te)
            m = mce(p_pred, y_te)
            existing_eval = {
                "method": ex.get("method") if isinstance(ex, dict) else "unknown",
                "n_train_original": ex.get("n_train") if isinstance(ex, dict) else "?",
                "brier_last_fold": round(b, 5),
                "ece_last_fold": round(e, 5),
                "logloss_last_fold": round(ll, 5),
                "mce_last_fold": round(m, 5),
                "n_test_last_fold": int(len(te)),
            }
            print(f"  existing agf_outcome_calibrator: brier={b:.5f} ece={e:.5f}")
        except Exception as e:
            print(f"  existing calibrator eval failed: {e}")
            existing_eval = {"error": str(e)[:200]}

    # -------------- Yol B: bet_diary join (n=18) --------------
    print("\n[B] bet_diary mini-analiz...")
    bd_df = build_bet_diary_joined()
    bd_status = {
        "n_joined": int(len(bd_df)),
        "dates": sorted(bd_df["date"].unique().tolist()) if not bd_df.empty else [],
        "hippos": sorted(bd_df["hippodrome"].unique().tolist()) if not bd_df.empty else [],
        "win_rate": float(bd_df["won_flag"].mean()) if not bd_df.empty else None,
    }
    print(f"  joined: {bd_status['n_joined']}")
    if not bd_df.empty:
        # Sadece raw scoring (n<50 → fit YOK)
        if len(bd_df) >= 10:
            mp = np.asarray(bd_df["model_prob"], dtype=float)
            ap = np.asarray(bd_df["agf_pct"], dtype=float) / 100.0
            y = np.asarray(bd_df["won_flag"], dtype=float)
            bd_status["raw_model_brier"] = round(brier(mp, y), 5)
            bd_status["raw_model_ece"] = round(ece(mp, y), 5)
            bd_status["raw_agf_brier"] = round(brier(ap, y), 5)
            bd_status["raw_agf_ece"] = round(ece(ap, y), 5)
            bd_status["raw_model_logloss"] = round(logloss(mp, y), 5)
            bd_status["raw_agf_logloss"] = round(logloss(ap, y), 5)
        bd_status["warning"] = "INSUFFICIENT (<50): kalibratör fit edilmedi"

    # -------------- Rapor yaz --------------
    print(f"\n[REPORT] {OUT_REPORT}")
    write_report(df, drift, results_a, agg_a, insuff_a, top3, candidates_meta,
                 existing_eval, bd_df, bd_status, splits)

    # MANIFEST
    write_manifest(candidates_meta)

    elapsed = time.time() - t0
    print(f"\n[DONE] elapsed={elapsed:.1f}s")


def write_report(df, drift, results, agg, insuff, top3, cands_meta, existing_eval,
                 bd_df, bd_status, splits):
    lines = []
    lines.append("# Phase 5.2.6 — Calibration Grid Raporu")
    lines.append("")
    lines.append(f"Fit zamanı: {datetime.now().isoformat()}Z")
    lines.append("")
    lines.append("## Durum özeti")
    lines.append("")
    lines.append(f"- AGF kalibrasyon dataset: **n={len(df)}** "
                 f"({df['date'].dt.date.nunique()} gün, "
                 f"{df['date'].dt.date.min()} → {df['date'].dt.date.max()})")
    lines.append(f"- Pozitif (winner): {int(df['won_flag'].sum())} / {len(df)} "
                 f"({df['won_flag'].mean()*100:.2f}%)")
    lines.append(f"- Walk-forward folds: **{len(splits)}**, "
                 f"per-fold test n≈{int(np.mean([len(t) for _, t in splits]))}")
    lines.append(f"- Distance coverage: {df['distance'].notna().mean()*100:.1f}%")
    lines.append("")
    lines.append("**ÖNEMLİ VERİ KISITLARI** (sahte sonuç üretmemek için açık not):")
    lines.append("")
    lines.append("1. **Model_prob kalibrasyonu yapılamadı**: bet_diary'de did_we_win=None "
                 "(outcome henüz yazılmamış). bet_diary tarihleri (Jun 04/08/09/10/12) ile "
                 "outcomes dosyaları (Apr 23 → Jun 07) sadece 2026-06-04'te örtüşüyor → "
                 f"join sonucu **n={bd_status['n_joined']}** (1 altılı). "
                 "Bu rapor ASIL olarak **AGF→outcome** (piyasa/FLB kalibrasyonu) için "
                 "geçerli sonuçlar üretti. Model kalibrasyonu için forward bekliyor "
                 "(retro tamamlanınca + bet_diary outcome update).")
    lines.append("2. **Per-breed yapılamadı**: calibration_dataset_complete.csv'de breed "
                 "kolonu yok; sire'dan otomatik breed çıkarma güvenilmez. Bunun yerine "
                 "PER-HIPPODROME bucket'ı kullanıldı (Şanlıurfa/Elazığ/Diyarbakır Arap-ağırlıklı "
                 "proxy; kesin değil).")
    lines.append("3. **Per-target (top1..5) yapılamadı**: AGF dataset at-level (race-internal "
                 "rank değil). bet_diary'de model_rank var ama outcome eşleşmesi yetersiz.")
    lines.append("")
    lines.append("## Walk-forward split tanımı")
    lines.append("")
    lines.append(f"Zaman-sıralı expanding window. Fold {N_FOLDS} adet. "
                 "Train her zaman test'ten önce (future leakage YOK).")
    lines.append("")
    for i, (tr, te) in enumerate(splits):
        d_tr_min, d_tr_max = df.loc[tr, 'date'].min().date(), df.loc[tr, 'date'].max().date()
        d_te_min, d_te_max = df.loc[te, 'date'].min().date(), df.loc[te, 'date'].max().date()
        lines.append(f"- Fold {i+1}: train n={len(tr)} ({d_tr_min} → {d_tr_max}), "
                     f"test n={len(te)} ({d_te_min} → {d_te_max})")
    lines.append("")
    lines.append("## Drift kontrol (oldest fold vs newest fold)")
    lines.append("")
    lines.append(f"- En eski fold test: n={drift['oldest_n']}, "
                 f"mean AGF prob={drift['oldest_mean_prob']:.4f}, "
                 f"win rate={drift['oldest_win_rate']:.4f}")
    lines.append(f"- En yeni fold test: n={drift['newest_n']}, "
                 f"mean AGF prob={drift['newest_mean_prob']:.4f}, "
                 f"win rate={drift['newest_win_rate']:.4f}")
    lines.append(f"- Drift: prob Δ={drift['prob_drift']:+.4f}, "
                 f"winrate Δ={drift['winrate_drift']:+.4f}")
    if abs(drift['prob_drift']) > 0.01 or abs(drift['winrate_drift']) > 0.01:
        lines.append("")
        lines.append("⚠ Drift gözlendi → kalibratör yenileme döngüsü "
                     "(haftalık) önerilir.")
    lines.append("")
    lines.append("## GLOBAL bucket — calibrator sıralaması")
    lines.append("")
    lines.append("Combined score = Brier + 0.5×ECE (lower=better). "
                 "Bootstrap CI 95% (n=1000 resample).")
    lines.append("")
    global_only = agg[agg["bucket_type"] == "GLOBAL"].sort_values("combined_score")
    lines.append("| Calibrator | Brier | Brier CI95 | ECE | ECE CI95 | LogLoss | MCE | "
                 "Combined | n_test_avg |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for _, r in global_only.iterrows():
        lines.append(
            f"| {r['calibrator']} | {r['brier']:.5f} | "
            f"[{r['brier_lo']:.5f}, {r['brier_hi']:.5f}] | "
            f"{r['ece']:.5f} | [{r['ece_lo']:.5f}, {r['ece_hi']:.5f}] | "
            f"{r['logloss']:.5f} | {r['mce']:.5f} | "
            f"{r['combined_score']:.5f} | {int(r['n_test'] / r['n_folds'])} |"
        )
    lines.append("")
    lines.append("## En iyi 3 GLOBAL aday (kaydedildi)")
    lines.append("")
    for i, c in enumerate(cands_meta):
        lines.append(f"### {i+1}. {c['method']} (file: {c['file']})")
        lines.append("")
        lines.append(f"- Brier: {c['brier']:.5f}")
        lines.append(f"- ECE: {c['ece']:.5f}")
        lines.append(f"- LogLoss: {c['logloss']:.5f}")
        lines.append(f"- MCE: {c['mce']:.5f}")
        lines.append(f"- Combined: {c['combined']:.5f}")
        lines.append(f"- n_train_total: {c['n_train_total']}")
        lines.append("")
        if c['method'] == 'isotonic':
            lines.append("**Neden seçildi**: non-parametrik, monoton; AGF gibi market "
                         "score için altın standart. Phase 5.2.5'te mevcut "
                         "agf_outcome_calibrator.pkl'in bazı bu (revize).")
        elif c['method'] == 'platt':
            lines.append("**Neden seçildi**: 2-parametre logistic, küçük-n stabilite. "
                         "Düşük overfitting riski.")
        elif c['method'] == 'beta':
            lines.append("**Neden seçildi**: Beta calibration (Kull 2017). Asymmetric "
                         "miscalibration için isotonic'ten daha esnek.")
        elif c['method'] == 'stacking':
            lines.append("**Neden seçildi**: 3-base meta-LR ensemble. Robustness için.")
        elif c['method'].startswith('histogram'):
            lines.append("**Neden seçildi**: equal-width binning. Lokal düzeltme.")
        elif c['method'] == 'temperature':
            lines.append("**Neden seçildi**: tek-parametre, NN logit ölçeği için. "
                         "Aşırı confident/under-confident dump.")
        elif c['method'].startswith('spline'):
            lines.append("**Neden seçildi**: pürüzsüz, esnek; çok-bin histogram artefaktını önler.")
        lines.append("")
    if existing_eval:
        lines.append("## Mevcut agf_outcome_calibrator.pkl baseline (last fold test üzerinde)")
        lines.append("")
        if "error" in existing_eval:
            lines.append(f"⚠ load hatası: {existing_eval['error']}")
        else:
            lines.append(f"- Method: {existing_eval['method']}")
            lines.append(f"- Orijinal n_train: {existing_eval['n_train_original']}")
            lines.append(f"- Brier (last fold): {existing_eval['brier_last_fold']:.5f}")
            lines.append(f"- ECE (last fold): {existing_eval['ece_last_fold']:.5f}")
            lines.append(f"- LogLoss (last fold): {existing_eval['logloss_last_fold']:.5f}")
            lines.append(f"- MCE (last fold): {existing_eval['mce_last_fold']:.5f}")
            lines.append(f"- n_test_last_fold: {existing_eval['n_test_last_fold']}")
            # Top GLOBAL ile karşılaştır
            top_brier = float(global_only.iloc[0]["brier"])
            top_ece = float(global_only.iloc[0]["ece"])
            top_name = global_only.iloc[0]["calibrator"]
            lines.append("")
            lines.append(f"Karşılaştırma: top GLOBAL '{top_name}' "
                         f"Brier {top_brier:.5f}, ECE {top_ece:.5f}. ")
            if existing_eval["brier_last_fold"] < top_brier and \
                    existing_eval["ece_last_fold"] < top_ece:
                lines.append("→ Mevcut calibrator hâlâ daha iyi. **Aktif kalsın.**")
            else:
                lines.append(f"→ Yeni adaylar mevcuttan parite veya daha iyi. "
                             f"**Berkay karar verir** (active.pkl yazılmadı).")
        lines.append("")
    lines.append("## PER-HIPPODROME bucket sonuçları")
    lines.append("")
    perhippo = agg[agg["bucket_type"] == "PER_HIPPODROME"]
    if not perhippo.empty:
        # Best per hippo
        best_per_h = perhippo.loc[perhippo.groupby("bucket_key")["combined_score"].idxmin()]
        lines.append("Her hipodrom için EN İYİ calibrator + GLOBAL raw karşılaştırma:")
        lines.append("")
        lines.append("| Hipodrom | Best calibrator | Brier | ECE | LogLoss | n_test | "
                     "GLOBAL_raw_brier (kıyas) |")
        lines.append("|---|---|---|---|---|---|---|")
        global_raw = agg[(agg["bucket_type"] == "GLOBAL") & (agg["calibrator"] == "raw")]
        global_raw_brier = float(global_raw.iloc[0]["brier"]) if not global_raw.empty else None
        for _, r in best_per_h.sort_values("bucket_key").iterrows():
            lines.append(
                f"| {r['bucket_key']} | {r['calibrator']} | "
                f"{r['brier']:.5f} | {r['ece']:.5f} | {r['logloss']:.5f} | "
                f"{int(r['n_test'] / r['n_folds'])} | "
                f"{global_raw_brier:.5f} |" if global_raw_brier else
                f"| {r['bucket_key']} | {r['calibrator']} | "
                f"{r['brier']:.5f} | {r['ece']:.5f} | {r['logloss']:.5f} | "
                f"{int(r['n_test'] / r['n_folds'])} | n/a |"
            )
        lines.append("")
        lines.append("**Sahte-bucket koruması**: n_test < 30 olan hipodrom-fold'ları "
                     "INSUFFICIENT diye işaretlendi (aşağıdaki tabloya bak).")
        lines.append("")
    lines.append("## PER-DISTANCE bucket sonuçları")
    lines.append("")
    perdist = agg[agg["bucket_type"] == "PER_DISTANCE"]
    if not perdist.empty:
        best_per_d = perdist.loc[perdist.groupby("bucket_key")["combined_score"].idxmin()]
        lines.append("| Mesafe bandı | Best calibrator | Brier | ECE | LogLoss | n_test |")
        lines.append("|---|---|---|---|---|---|")
        for _, r in best_per_d.sort_values("bucket_key").iterrows():
            lines.append(
                f"| {r['bucket_key']} | {r['calibrator']} | "
                f"{r['brier']:.5f} | {r['ece']:.5f} | {r['logloss']:.5f} | "
                f"{int(r['n_test'] / r['n_folds'])} |"
            )
        lines.append("")
    lines.append("## PER-AGF-BAND sonuçları (favori kategorisine göre kalibrasyon)")
    lines.append("")
    peraband = agg[agg["bucket_type"] == "PER_AGF_BAND"]
    if not peraband.empty:
        # Her band için raw + best
        best_per_a = peraband.loc[peraband.groupby("bucket_key")["combined_score"].idxmin()]
        raw_per_a = peraband[peraband["calibrator"] == "raw"]
        lines.append("| AGF Band | Raw_brier | Raw_ece | Best_method | "
                     "Best_brier | Best_ece | n_test |")
        lines.append("|---|---|---|---|---|---|---|")
        for _, r in best_per_a.sort_values("bucket_key").iterrows():
            raw_r = raw_per_a[raw_per_a["bucket_key"] == r["bucket_key"]]
            raw_b = float(raw_r.iloc[0]["brier"]) if not raw_r.empty else None
            raw_e = float(raw_r.iloc[0]["ece"]) if not raw_r.empty else None
            raw_b_s = f"{raw_b:.5f}" if raw_b is not None else "n/a"
            raw_e_s = f"{raw_e:.5f}" if raw_e is not None else "n/a"
            lines.append(
                f"| {r['bucket_key']} | "
                f"{raw_b_s} | {raw_e_s} | "
                f"{r['calibrator']} | {r['brier']:.5f} | {r['ece']:.5f} | "
                f"{int(r['n_test'] / r['n_folds'])} |"
            )
        lines.append("")
        # FLB doğrulama: high/very-high AGF favorileri overbet mi?
        for band in ("high_30-50%", "veryHigh_>=50%"):
            sub = raw_per_a[raw_per_a["bucket_key"] == band]
            if not sub.empty:
                lines.append(f"- AGF band `{band}` raw brier: "
                             f"{float(sub.iloc[0]['brier']):.5f} "
                             f"→ FLB (favori overbet) Phase 5.5'te kanıtlanmıştı; "
                             f"bu bant'ta calibrator gerekiyor.")
        lines.append("")
    lines.append("## INSUFFICIENT / DEGENERATE bucket'lar")
    lines.append("")
    if not insuff.empty:
        # Sadık özet: bucket_type + bucket_key + n hücre
        insuff_summary = insuff.groupby(["bucket_type", "bucket_key", "status"]).size().reset_index(name="n_cells")
        lines.append("| Bucket type | Bucket | Status | Hücre sayısı |")
        lines.append("|---|---|---|---|")
        for _, r in insuff_summary.iterrows():
            lines.append(f"| {r['bucket_type']} | {r['bucket_key']} | {r['status']} | {r['n_cells']} |")
        lines.append("")
        lines.append(f"**Toplam insufficient hücre: {len(insuff)}** "
                     "(n<50 train veya n<30 test; sahte fit ÜRETİLMEDİ).")
    else:
        lines.append("Hiç insufficient bucket yok (büyük dataset).")
    lines.append("")
    lines.append("## Yol B — bet_diary mini-analiz (model_prob)")
    lines.append("")
    lines.append(f"bet_diary outcomes join: **n={bd_status['n_joined']}** satır "
                 f"(threshold n≥50, fit yapılmadı).")
    if bd_df is not None and not bd_df.empty:
        lines.append(f"- Tarihler: {bd_status['dates']}")
        lines.append(f"- Hipodromlar: {bd_status['hippos']}")
        lines.append(f"- Win rate: {bd_status['win_rate']:.4f}")
        if "raw_model_brier" in bd_status:
            lines.append("")
            lines.append("Raw skorlar (sadece bilgi, calibrator FIT EDİLMEDİ):")
            lines.append(f"- Model raw Brier: {bd_status['raw_model_brier']:.5f}")
            lines.append(f"- Model raw ECE: {bd_status['raw_model_ece']:.5f}")
            lines.append(f"- Model raw LogLoss: {bd_status['raw_model_logloss']:.5f}")
            lines.append(f"- AGF raw Brier: {bd_status['raw_agf_brier']:.5f}")
            lines.append(f"- AGF raw ECE: {bd_status['raw_agf_ece']:.5f}")
            lines.append(f"- AGF raw LogLoss: {bd_status['raw_agf_logloss']:.5f}")
            mb = bd_status['raw_model_brier']
            ab = bd_status['raw_agf_brier']
            if mb < ab:
                lines.append(f"- Model raw Brier ({mb:.4f}) < AGF raw Brier ({ab:.4f}) "
                             "→ n=18'de model marjinal iyi görünüyor; **ölçüm güvenilir DEĞİL** "
                             "(n<50, geniş CI). Forward 200+ outcome bekleyin.")
            else:
                lines.append(f"- Model raw Brier ({mb:.4f}) ≥ AGF raw Brier ({ab:.4f}) "
                             "→ n=18'de model AGF'yi yakalamıyor.")
        lines.append("")
        lines.append("⚠ **n=18 → istatistiksel güç çok düşük.** Kalibratör fit edilmedi; "
                     "active.pkl yazılmadı.")
    else:
        lines.append("(boş — join hatası veya tarihler örtüşmüyor)")
    lines.append("")
    lines.append("## Reliability diagram noktaları (last fold, isotonic vs raw)")
    lines.append("")
    last_split = splits[-1]
    tr, te = last_split
    p_tr = df.loc[tr, "agf_implied_prob"].to_numpy()
    y_tr = df.loc[tr, "won_flag"].to_numpy()
    p_te = df.loc[te, "agf_implied_prob"].to_numpy()
    y_te = df.loc[te, "won_flag"].to_numpy()
    try:
        cal = IsotonicCal().fit(p_tr, y_tr)
        p_cal = cal.predict(p_te)
        raw_pts = reliability_points(p_te, y_te, 10)
        cal_pts = reliability_points(p_cal, y_te, 10)
        lines.append("| Bin | Raw_conf | Raw_acc | Raw_n | Cal_conf | Cal_acc | Cal_n |")
        lines.append("|---|---|---|---|---|---|---|")
        for i, (r, c) in enumerate(zip(raw_pts, cal_pts)):
            r_acc = f"{r[1]:.4f}" if r[1] is not None else "-"
            c_acc = f"{c[1]:.4f}" if c[1] is not None else "-"
            lines.append(f"| {i+1} | {r[0]:.4f} | {r_acc} | {r[2]} | "
                         f"{c[0]:.4f} | {c_acc} | {c[2]} |")
        lines.append("")
        if HAS_MPL:
            lines.append("PNG: `audit/reports/figures/phase_5_2_6_reliability_isotonic.png`")
        else:
            lines.append("(matplotlib yok → PNG üretilmedi)")
    except Exception as e:
        lines.append(f"(reliability noktası hesaplama hatası: {e})")
    lines.append("")
    lines.append("## En iyi 3 aday seçim mantığı")
    lines.append("")
    lines.append("`combined_score = brier + 0.5 * ece` (Brier ağırlıklı, ECE ikincil). "
                 "Walk-forward'da TÜM fold'lar ortalamalandı. Her aday TÜM dataset üzerinde "
                 "yeniden fit edilip `candidates/cand_NN_method_GLOBAL.pkl` olarak kaydedildi.")
    lines.append("")
    lines.append("## Karar tavsiyesi (Berkay'a)")
    lines.append("")
    lines.append("Bu rapor ölçüm odaklı; **aktif kararını Berkay verir**. Olası yollar:")
    lines.append("")
    lines.append("1. **Mevcut agf_outcome_calibrator değişiklik gerekmiyor**: top GLOBAL "
                 "aday Brier mevcut <= mevcut → status quo.")
    lines.append("2. **Yeni aday daha iyi**: `cand_01_*.pkl`'i `simulation/calibrators/"
                 "fitted/agf_outcome_calibrator.pkl` olarak kopyala (önce backup al).")
    lines.append("3. **Model kalibrasyonu için forward**: bet_diary'de outcome update + n≥200 "
                 "birikince Yol B yeniden koş. Şimdilik `model_prob_calibrated=None` kalır.")
    lines.append("")
    lines.append("**+EV/edge iddiası BU RAPORDA YOKTUR.** Sadece Brier/ECE/LL/MCE.")
    lines.append("")

    with open(OUT_REPORT, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def write_manifest(cands_meta):
    lines = []
    lines.append("# Calibration Candidates — MANIFEST")
    lines.append("")
    lines.append(f"Generated: {datetime.now().isoformat()}Z")
    lines.append("")
    lines.append("Phase 5.2.6 grid çıktısı. **Hiçbiri active değil** — Berkay karar verir, "
                 "active.pkl yazılmadı.")
    lines.append("")
    if not cands_meta:
        lines.append("(aday yok)")
    else:
        lines.append("| # | File | Method | Bucket | Brier | ECE | LL | MCE | "
                     "Combined | n_train |")
        lines.append("|---|---|---|---|---|---|---|---|---|---|")
        for i, c in enumerate(cands_meta):
            lines.append(
                f"| {i+1} | `{c['file']}` | {c['method']} | {c['bucket']} | "
                f"{c['brier']:.5f} | {c['ece']:.5f} | {c['logloss']:.5f} | "
                f"{c['mce']:.5f} | {c['combined']:.5f} | {c['n_train_total']} |"
            )
    lines.append("")
    lines.append("## Kullanım")
    lines.append("")
    lines.append("**ÖNEMLİ**: Candidate pkl'leri `audit/87_calibration_grid.py`'deki "
                 "calibrator class'larına bağlı. Yüklerken module import gerekiyor:")
    lines.append("")
    lines.append("```python")
    lines.append("import sys, pickle, importlib.util")
    lines.append("spec = importlib.util.spec_from_file_location(")
    lines.append("    'cal87', 'audit/87_calibration_grid.py')")
    lines.append("mod = importlib.util.module_from_spec(spec)")
    lines.append("sys.modules['cal87'] = mod")
    lines.append("spec.loader.exec_module(mod)")
    lines.append("for name in ['BetaCal','HistogramCal','IsotonicCal','PlattCal',")
    lines.append("             'SplineCal','TemperatureCal','StackingCal','RawCalibrator']:")
    lines.append("    setattr(sys.modules['__main__'], name, getattr(mod, name))")
    lines.append("")
    lines.append("with open('cand_01_beta_global.pkl', 'rb') as f:")
    lines.append("    cand = pickle.load(f)")
    lines.append("preds = cand['model'].predict([0.05, 0.2, 0.5])")
    lines.append("# sklearn-compatible interface: model.predict(raw_probs) → calibrated")
    lines.append("```")
    lines.append("")
    lines.append("**Aktivasyon yolu** (Berkay onayı ile):")
    lines.append("")
    lines.append("```bash")
    lines.append("# Önce backup:")
    lines.append("cp simulation/calibrators/fitted/agf_outcome_calibrator.pkl \\")
    lines.append("   simulation/calibrators/fitted/agf_outcome_calibrator.pkl.bak")
    lines.append("# Sonra swap:")
    lines.append("cp simulation/calibrators/fitted/candidates/cand_01_beta_global.pkl \\")
    lines.append("   simulation/calibrators/fitted/agf_outcome_calibrator.pkl")
    lines.append("```")
    lines.append("")
    with open(OUT_MANIFEST, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


if __name__ == "__main__":
    main()
