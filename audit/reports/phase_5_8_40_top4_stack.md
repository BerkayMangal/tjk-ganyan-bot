# Phase 5.8.40 — Top4 DEDICATED stacking (V7 base)
_Run: 2026-06-18T08:54:40.421885Z_

## Setup

- Data: races_v7.csv, train <2025-01-01, meta_train Jan-May 2025, test ≥2025-05-24
- 3 signal: V7 ranker + V7 top4 binary classifier + Plackett-Luce (k=4)
- Meta: LogReg + isotonic calibration

## Test set top4 hit (paired, ≥2025-05-24)

| Breed | n | V7 ranker | top4 binary | PL | **STACK** | Δ vs V7 |
|---|---|---|---|---|---|---|
| arab | 3,016 | 72.81% | 70.39% | 72.35% | **73.31%** | +0.50pp |
| english | 3,664 | 75.52% | 71.62% | 74.78% | **75.16%** | -0.35pp |

## Meta coefs

- arab: v7_ranker=+8.181, top4_binary=+1.223, pl_sim=+0.206
- english: v7_ranker=+9.492, top4_binary=+1.284, pl_sim=+0.292

## Karar

**✗ Stack V7'i geçemiyor** (audit/110 V6 base ile aynı sonuç).
V7 ranker 225 feature ile zaten yarış-context yakaladığı için ek binary signal redundant.
