"""V8 — Yeni nesil forward-looking forecasting model.

Berkay (2026-06-27): "artik yepyeni bir modelimiz var, top4 vs hepsini
unut, onu ayri cok gelistirecegiz".

V8 ≠ V7'nin extension. V8 **temelden farklı** bir model:

V7 (eski):
  - Pure ranker (ndcg@4 LambdaRank)
  - 225 feature, hep descriptive
  - Single output: relative softmax score (mp)
  - AGF-tarafgir (calibrated probability YOK)

V8 (yeni):
  - Multi-head probabilistic classifier (top-1/2/3/4 ayrı)
  - V7 (225) + forecast (32) + race-relative + interaction = ~280 feature
  - Calibrated outputs (isotonic regression per-head)
  - AGF FEATURE olarak var ama dominant değil (down-weighted)
  - Forward-looking ağırlıklı: trajectory, glicko, sequence, pace
  - Uncertainty-aware: Glicko RD'sini explicit uses

Mimari:
  Layer 1: V7 features (225) + AGF (16) → frozen
  Layer 2: Forward features (forecast/)  → core innovation
  Layer 3: Race-relative aggregation
  Layer 4: Multi-head logistic with isotonic calibration

Modüller:
  feature_builder.py  : V7 + forecast feature birleştirici
  dataset.py          : Training set builder (walk-forward safe)
  model.py            : Multi-head logistic architecture (pure-Python)
  calibration.py      : Isotonic regression per-head
  train.py            : Training loop + walk-forward CV
  inference.py        : Production inference pipeline
  backtest.py         : Walk-forward backtest harness
  metrics.py          : Top-K accuracy, Brier, log-loss, calibration

Felsefe:
  - NO heavy deps (numpy/scipy/torch SADECE training time, infer pure-Py)
  - Tüm modüller deterministic
  - Walk-forward training (no look-ahead bias)
  - Honest backtesting (Brier + log-loss + ECE)
"""
__version__ = "8.0.0"
