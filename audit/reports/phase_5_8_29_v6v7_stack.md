# Phase 5.8.29 — V6+V7 Stacking Meta-learner
_Tarih: 2026-06-15T19:57:57.147771Z_

**3 sinyal**: V6 ranker (210) + V7 ranker (225) + Plackett-Luce (V7-based)

## Top-K Hit per Source (test ≥2025-05-24)

### top3

| Breed | V6 | V7 | PL | **STACK** |
|---|---|---|---|---|
| arab | 60.25% | 63.00% | 62.60% | **61.87%** |
| english | 60.99% | 63.73% | 63.98% | **63.33%** |

**Meta coefs (V6/V7/PL):**

- arab: v6=+6.072, v7=+4.206, pl=+0.143
- english: v6=+6.222, v7=+4.731, pl=+0.039

### top4

| Breed | V6 | V7 | PL | **STACK** |
|---|---|---|---|---|
| arab | 70.76% | 72.81% | 72.38% | **72.31%** |
| english | 72.22% | 75.52% | 75.11% | **74.34%** |

**Meta coefs (V6/V7/PL):**

- arab: v6=+6.500, v7=+4.212, pl=+0.164
- english: v6=+6.559, v7=+5.056, pl=+0.303

