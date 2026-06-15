# Phase 5.8.17 — V3 FULL PAIRED (cutoff=2025-05-24)
_Tarih: 2026-06-15T10:54:13.200918Z_

audit/98 cutoff=2025-01-01 idi → V3 NEW 5 ay daha az training data gördü.
audit/101'de V3 OLD görünür üstün çıkmıştı (Jan-May 2025 V3 OLD eğitim setinde).
Bu rapor doğru paired test: BOTH V3 OLD ve V3 NEW yeniden cutoff=2025-05-24 ile eğitildi.

## Top-K Hit Ratio (test ≥2025-05-24, RANKER ensemble)

### ARAB (test n_races=2,991, train=84,987)

| Metric | V3 NEW (180) | V6 (210) | Δ |
|---|---|---|---|
| top1 | 26.51% | 31.66% | +5.15pp |
| top2 | 45.04% | 52.26% | +7.22pp |
| top3 | 58.41% | 65.96% | +7.56pp |
| top4 | 69.41% | 76.56% | +7.15pp |
| top5 | 78.13% | 83.92% | +5.78pp |

**PROB (best calib: OLD=raw | NEW=raw)**

| Metric | V3 OLD | V3 NEW | Δ |
|---|---|---|---|
| AUC | 0.7433 | 0.8022 | +0.0589 |
| Brier | 0.0818 | 0.0769 | -0.0049 |
| ECE | 0.0104 | 0.0096 | -0.0008 |
| LogLoss | 0.2856 | 0.2644 | -0.0212 |

### ENGLISH (test n_races=3,588, train=94,869)

| Metric | V3 NEW (180) | V6 (210) | Δ |
|---|---|---|---|
| top1 | 28.85% | 35.48% | +6.63pp |
| top2 | 47.05% | 56.58% | +9.53pp |
| top3 | 62.12% | 70.35% | +8.22pp |
| top4 | 73.80% | 79.77% | +5.96pp |
| top5 | 81.97% | 86.62% | +4.65pp |

**PROB (best calib: OLD=raw | NEW=raw)**

| Metric | V3 OLD | V3 NEW | Δ |
|---|---|---|---|
| AUC | 0.7464 | 0.8111 | +0.0647 |
| Brier | 0.0893 | 0.0827 | -0.0066 |
| ECE | 0.0055 | 0.0082 | +0.0028 |
| LogLoss | 0.3050 | 0.2792 | -0.0258 |


## Karar

**✓ V6 (210) ÜSTÜN her metrikte** — swap (trained_v3 yedek + trained_v6_210 → trained_v3) önerilir.
