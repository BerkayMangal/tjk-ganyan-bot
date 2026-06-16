# Phase 5.8.31 — V7.5 (235) Paired vs V7 (225)
_Tarih: 2026-06-16T07:46:51.625383Z_  ·  _Cutoff: 2025-05-24_

V7.5 = V7 (225) + 10 ix2__ second-order interactions (audit/121).

## Test set Top-K hit (paired, ≥2025-05-24)

### ARAB (test n_races=2,991)

| Metric | V7 (225) | V7.5 (235) | Δ |
|---|---|---|---|
| top1 | 28.25% | 28.69% | +0.43pp |
| top2 | 48.55% | 48.18% | -0.37pp |
| top3 | 62.62% | 62.65% | +0.03pp |
| top4 | 72.58% | 72.68% | +0.10pp |
| top5 | 80.54% | 80.47% | -0.07pp |

**PROB (binary win classifier)**

| Metric | V7 | V7.5 | Δ |
|---|---|---|---|
| AUC | 0.8022 | 0.8031 | +0.0009 |
| Brier | 0.0768 | 0.0768 | +0.0000 |
| ECE | 0.0088 | 0.0084 | -0.0004 |

### ENGLISH (test n_races=3,588)

| Metric | V7 (225) | V7.5 (235) | Δ |
|---|---|---|---|
| top1 | 29.29% | 29.07% | -0.22pp |
| top2 | 48.91% | 48.49% | -0.42pp |
| top3 | 62.99% | 63.18% | +0.20pp |
| top4 | 75.00% | 74.47% | -0.53pp |
| top5 | 82.33% | 82.25% | -0.08pp |

**PROB (binary win classifier)**

| Metric | V7 | V7.5 | Δ |
|---|---|---|---|
| AUC | 0.8101 | 0.8107 | +0.0006 |
| Brier | 0.0827 | 0.0826 | -0.0001 |
| ECE | 0.0083 | 0.0093 | +0.0010 |

## Karar

**~ Kısmi üstünlük** — manuel inceleme + paired forward.
