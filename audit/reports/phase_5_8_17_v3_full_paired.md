# Phase 5.8.17 — V3 FULL PAIRED (cutoff=2025-05-24)
_Tarih: 2026-06-15T10:18:50.699242Z_

audit/98 cutoff=2025-01-01 idi → V3 NEW 5 ay daha az training data gördü.
audit/101'de V3 OLD görünür üstün çıkmıştı (Jan-May 2025 V3 OLD eğitim setinde).
Bu rapor doğru paired test: BOTH V3 OLD ve V3 NEW yeniden cutoff=2025-05-24 ile eğitildi.

## Top-K Hit Ratio (test ≥2025-05-24, RANKER ensemble)

### ARAB (test n_races=2,991, train=84,987)

| Metric | V3 OLD_FULL (177) | V3 NEW_FULL (180) | Δ |
|---|---|---|---|
| top1 | 26.98% | 27.58% | +0.60pp |
| top2 | 45.34% | 45.77% | +0.43pp |
| top3 | 59.28% | 60.51% | +1.24pp |
| top4 | 70.14% | 71.25% | +1.10pp |
| top5 | 78.13% | 79.27% | +1.14pp |

**PROB (best calib: OLD=raw | NEW=raw)**

| Metric | V3 OLD | V3 NEW | Δ |
|---|---|---|---|
| AUC | 0.7246 | 0.7437 | +0.0192 |
| Brier | 0.0826 | 0.0818 | -0.0008 |
| ECE | 0.0106 | 0.0104 | -0.0002 |
| LogLoss | 0.2907 | 0.2854 | -0.0053 |

### ENGLISH (test n_races=3,588, train=94,869)

| Metric | V3 OLD_FULL (177) | V3 NEW_FULL (180) | Δ |
|---|---|---|---|
| top1 | 28.40% | 29.38% | +0.98pp |
| top2 | 49.11% | 49.92% | +0.81pp |
| top3 | 64.52% | 65.55% | +1.03pp |
| top4 | 75.84% | 77.09% | +1.25pp |
| top5 | 83.67% | 84.09% | +0.42pp |

**PROB (best calib: OLD=raw | NEW=raw)**

| Metric | V3 OLD | V3 NEW | Δ |
|---|---|---|---|
| AUC | 0.7348 | 0.7462 | +0.0114 |
| Brier | 0.0901 | 0.0894 | -0.0007 |
| ECE | 0.0083 | 0.0056 | -0.0027 |
| LogLoss | 0.3094 | 0.3052 | -0.0042 |


## Karar

**✓ V3 NEW_FULL (180) ÜSTÜN her metrikte** — swap (trained_v3 yedek + trained_v3_full → trained_v3) önerilir.
