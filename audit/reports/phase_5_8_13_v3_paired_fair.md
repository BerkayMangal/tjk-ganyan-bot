# Phase 5.8.13 — V3 LIVE PAIRED FAIR Retrain (aynı cutoff, fair karşılaştırma)
_Tarih: 2026-06-15T09:16:57.795520Z_  ·  _Cutoff: 2025-01-01_

## Özet

audit/97'de bug vardı: V3 OLD model train_meta.json'da split_date=2025-05-24, ama audit/97 onu 2025-01-01 cutoff'la test etti → Jan-May 2025 V3 OLD eğitim setinde → ezberlenmiş veri ile test (fake +%3 AUC). Bu script V3 OLD'u YENİDEN aynı cutoff (2025-01-01) ile fit ediyor → dürüst paired test.

### ARAB (train n=73,866, test n=42,000)

**RANKER (ensemble, ≥2025-01-01 test)**

| Metric | V3 OLD_R (177) | V3 NEW (180) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6209 | 0.6267 | +0.0058 |
| ndcg@3 | 0.7264 | 0.7313 | +0.0049 |
| top1_acc | 26.80% | 27.75% | +0.94pp |
| top3_acc | 61.32% | 62.60% | +1.28pp |

**PROB (win classifier)**

| Metric | V3 OLD_R | V3 NEW (180) | Δ |
|---|---|---|---|
| AUC | 0.7141 | 0.7314 | +0.0173 |
| Brier | 0.0833 | 0.0825 | -0.0008 |
| ECE | 0.0093 | 0.0096 | +0.0003 |
| LogLoss | 0.2940 | 0.2892 | -0.0047 |

### ENGLISH (train n=82,789, test n=45,573)

**RANKER (ensemble, ≥2025-01-01 test)**

| Metric | V3 OLD_R (177) | V3 NEW (180) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6490 | 0.6527 | +0.0037 |
| ndcg@3 | 0.7517 | 0.7555 | +0.0039 |
| top1_acc | 29.03% | 29.43% | +0.40pp |
| top3_acc | 64.87% | 65.95% | +1.08pp |

**PROB (win classifier)**

| Metric | V3 OLD_R | V3 NEW (180) | Δ |
|---|---|---|---|
| AUC | 0.7257 | 0.7402 | +0.0145 |
| Brier | 0.0903 | 0.0896 | -0.0007 |
| ECE | 0.0046 | 0.0064 | +0.0018 |
| LogLoss | 0.3111 | 0.3066 | -0.0044 |

## Karar

**✓ V3 NEW (180) v3 OLD'tan ÜSTÜN/EŞDEĞER** — swap (trained_v3 yedek + trained_v3_180 → trained_v3) önerilir.
