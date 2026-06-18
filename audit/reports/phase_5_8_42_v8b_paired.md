# Phase 5.8.31 — V8b (235) Paired vs V7 (225)
_Tarih: 2026-06-18T09:39:33.065112Z_  ·  _Cutoff: 2025-05-24_

V8b = V7 (225) + 10 rp__ race-pace features (audit/133).

## Test set Top-K hit (paired, ≥2025-05-24)

### ARAB (test n_races=2,991)

| Metric | V7 (225) | V8b (235) | Δ |
|---|---|---|---|
| top1 | 28.25% | 28.05% | -0.20pp |
| top2 | 48.55% | 48.95% | +0.40pp |
| top3 | 62.62% | 63.09% | +0.47pp |
| top4 | 72.58% | 72.72% | +0.13pp |
| top5 | 80.54% | 80.47% | -0.07pp |

**PROB (binary win classifier)**

| Metric | V7 | V8b | Δ |
|---|---|---|---|
| AUC | 0.8022 | 0.8031 | +0.0009 |
| Brier | 0.0768 | 0.0767 | -0.0001 |
| ECE | 0.0088 | 0.0092 | +0.0004 |

### ENGLISH (test n_races=3,588)

| Metric | V7 (225) | V8b (235) | Δ |
|---|---|---|---|
| top1 | 29.29% | 29.10% | -0.20pp |
| top2 | 48.91% | 48.77% | -0.14pp |
| top3 | 62.99% | 63.02% | +0.03pp |
| top4 | 75.00% | 74.33% | -0.67pp |
| top5 | 82.33% | 82.39% | +0.06pp |

**PROB (binary win classifier)**

| Metric | V7 | V8b | Δ |
|---|---|---|---|
| AUC | 0.8101 | 0.8100 | -0.0001 |
| Brier | 0.0827 | 0.0828 | +0.0000 |
| ECE | 0.0083 | 0.0093 | +0.0011 |

## Karar

**~ Kısmi üstünlük** — manuel inceleme + paired forward.
