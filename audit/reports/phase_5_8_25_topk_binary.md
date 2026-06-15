# Phase 5.8.25 — Top-K Binary Classifier (Layer 1)
_Tarih: 2026-06-15T14:33:31.493174Z_

**Hedef**: dedicated P(top3) ve P(top4) binary classifier — V6 ranker'dan üstün olmayı amaçlar.
**Yapı**: XGB + LGBM + CatBoost ensemble, beta+isotonic calibration, ensemble weight grid search.

## Test set Top-K Hit (paired, ≥2025-05-24 test)

### top3

| Breed | V6 ranker | Binary Layer-1 | Δ | AUC | ECE | calib |
|---|---|---|---|---|---|---|
| arab | 60.25% | **54.27%** | -5.99pp | 0.7716 | 0.0119 | beta |
| english | 60.99% | **58.30%** | -2.69pp | 0.7852 | 0.0148 | beta |

### top4

| Breed | V6 ranker | Binary Layer-1 | Δ | AUC | ECE | calib |
|---|---|---|---|---|---|---|
| arab | 70.76% | **66.01%** | -4.74pp | 0.7751 | 0.0095 | beta |
| english | 72.22% | **68.53%** | -3.68pp | 0.7948 | 0.0148 | beta |

## Karar

**~ Karışık** — segment-bazlı stacking ile birleşik daha güçlü olabilir.
