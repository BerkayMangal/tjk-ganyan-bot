# Phase 5.8.12 — V3 LIVE Retrain (177 → 180 feature)
_Tarih: 2026-06-15T09:10:24.776917Z_

## Özet

### ARAB (test n=42,000)

**RANKER (ensemble, ≥2025 test)**

| Metric | V3 OLD | V3 NEW (180) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6618 | 0.6267 | -0.0352 |
| ndcg@3 | 0.7578 | 0.7313 | -0.0265 |
| top1_acc | 31.93% | 27.75% | -4.18pp |
| top3_acc | 66.64% | 62.60% | -4.04pp |

**PROB (win classifier)**

| Metric | V3 OLD | V3 NEW (180) | Δ |
|---|---|---|---|
| AUC | 0.7634 | 0.7314 | -0.0320 |
| Brier | 0.0792 | 0.0825 | +0.0034 |
| ECE | 0.0090 | 0.0096 | +0.0006 |
| LogLoss | 0.2776 | 0.2892 | +0.0117 |

### ENGLISH (test n=45,573)

**RANKER (ensemble, ≥2025 test)**

| Metric | V3 OLD | V3 NEW (180) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6826 | 0.6527 | -0.0300 |
| ndcg@3 | 0.7775 | 0.7555 | -0.0219 |
| top1_acc | 33.47% | 29.43% | -4.04pp |
| top3_acc | 69.37% | 65.95% | -3.42pp |

**PROB (win classifier)**

| Metric | V3 OLD | V3 NEW (180) | Δ |
|---|---|---|---|
| AUC | 0.7708 | 0.7402 | -0.0305 |
| Brier | 0.0863 | 0.0896 | +0.0033 |
| ECE | 0.0097 | 0.0064 | -0.0033 |
| LogLoss | 0.2956 | 0.3066 | +0.0110 |

## Karar

**✗ V3 NEW ZAYIF** — swap YOK, feature seti gözden geçirilmeli.
