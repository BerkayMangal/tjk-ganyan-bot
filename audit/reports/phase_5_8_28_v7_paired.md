# Phase 5.8.28 — V7 (225) Paired vs V6 (210)
_Tarih: 2026-06-15T15:41:04.134919Z_  ·  _Cutoff: 2025-05-24_

V7 = V6 (210) + 15 race-relative (rr__) feature (audit/114).

## Test set Top-K hit (paired, ≥2025-05-24)

### ARAB (test n_races=2,991)

| Metric | V6 (210) | V7 (225) | Δ |
|---|---|---|---|
| top1 | 26.51% | 28.25% | +1.74pp |
| top2 | 45.74% | 48.55% | +2.81pp |
| top3 | 59.85% | 62.62% | +2.77pp |
| top4 | 70.51% | 72.58% | +2.07pp |
| top5 | 78.20% | 80.54% | +2.34pp |

**PROB (binary win classifier)**

| Metric | V6 | V7 | Δ |
|---|---|---|---|
| AUC | 0.8022 | 0.8022 | +0.0001 |
| Brier | 0.0769 | 0.0768 | -0.0001 |
| ECE | 0.0096 | 0.0088 | -0.0008 |

### ENGLISH (test n_races=3,588)

| Metric | V6 (210) | V7 (225) | Δ |
|---|---|---|---|
| top1 | 26.95% | 29.29% | +2.34pp |
| top2 | 46.46% | 48.91% | +2.45pp |
| top3 | 60.23% | 62.99% | +2.76pp |
| top4 | 71.63% | 75.00% | +3.37pp |
| top5 | 80.57% | 82.33% | +1.76pp |

**PROB (binary win classifier)**

| Metric | V6 | V7 | Δ |
|---|---|---|---|
| AUC | 0.8111 | 0.8101 | -0.0010 |
| Brier | 0.0827 | 0.0827 | -0.0000 |
| ECE | 0.0082 | 0.0083 | +0.0001 |

## Karar

**✓ V7 ÜSTÜN** her segmentte top3 ve top4 — V6 SHADOW yerine V7 SHADOW önerilir.
