# Phase 5.8.26 — Top-K Stacking Meta-learner (Layer 3)
_Tarih: 2026-06-15T15:29:08.801518Z_

**3 sinyal → LogReg meta → isotonic calibration**
- S1 = V6 ranker softmax (mevcut)
- S2 = Binary classifier P(topk) (audit/110)
- S3 = Plackett-Luce MC simulation (5000 sims/yarış)

## Test set Top-K hit ratio (paired, ≥2025-05-24)

### top3

| Breed | S1 ranker | S2 binary | S3 PL | **STACKED** |
|---|---|---|---|---|
| arab | 60.25% | 54.27% | 59.99% | **60.78%** |
| english | 60.99% | 58.30% | 60.93% | **62.35%** |

**Meta coefs (S1/S2/S3):**

- arab: s1=+12.489, s2=-2.177, s3=+0.016
- english: s1=+13.700, s2=-2.558, s3=-0.038

### top4

| Breed | S1 ranker | S2 binary | S3 PL | **STACKED** |
|---|---|---|---|---|
| arab | 70.76% | 66.01% | 70.46% | **70.82%** |
| english | 72.22% | 68.53% | 72.41% | **73.17%** |

**Meta coefs (S1/S2/S3):**

- arab: s1=+13.317, s2=-2.173, s3=+0.077
- english: s1=+13.595, s2=-1.906, s3=+0.316

## Karar

**En iyi kaynak per target:** top3 = stacked, top4 = stacked
