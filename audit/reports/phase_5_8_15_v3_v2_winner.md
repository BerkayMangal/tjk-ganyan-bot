# Phase 5.8.15 — V3 LIVE v2 (kazanan-odaklı retrain)
_Tarih: 2026-06-15T09:35:55.956043Z_

**Config**: XGBoost rank:ndcg + LGBM lambdarank + CB YetiRank | n_estimators=1500 (early stop val 2024) | max_depth=6 | lr=0.025 | ensemble weights grid search val NDCG@1

## Karşılaştırma

### ARAB (test n=42,000)

**RANKER (≥2025 test)**

| Metric | V3 NEW (prod) | V3 v2 (winner) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6267 | 0.5889 | -0.0377 |
| top1_acc | 27.75% | 24.48% | -3.27pp |
| top3_acc | 62.60% | 55.44% | -7.16pp |
| ndcg@3 | 0.7313 | 0.6899 | -0.0414 |

**PROB (best_calib: raw)**

| Metric | V3 NEW | V3 v2 | Δ |
|---|---|---|---|
| AUC | 0.7314 | 0.7019 | -0.0295 |
| Brier | 0.0825 | 0.0838 | +0.0013 |
| ECE | 0.0096 | 0.0032 | -0.0064 |
| LogLoss | 0.2892 | 0.2959 | +0.0066 |

**Best ensemble weights**: xgb=0.2, lgbm=0.6, cb=0.2

### ENGLISH (test n=45,573)

**RANKER (≥2025 test)**

| Metric | V3 NEW (prod) | V3 v2 (winner) | Δ |
|---|---|---|---|
| ndcg@1 | 0.6527 | 0.6151 | -0.0375 |
| top1_acc | 29.43% | 25.57% | -3.86pp |
| top3_acc | 65.95% | 60.53% | -5.42pp |
| ndcg@3 | 0.7555 | 0.7232 | -0.0323 |

**PROB (best_calib: beta)**

| Metric | V3 NEW | V3 v2 | Δ |
|---|---|---|---|
| AUC | 0.7402 | 0.7171 | -0.0231 |
| Brier | 0.0896 | 0.0912 | +0.0016 |
| ECE | 0.0064 | 0.0070 | +0.0005 |
| LogLoss | 0.3066 | 0.3135 | +0.0068 |

**Best ensemble weights**: xgb=0.2, lgbm=0.2, cb=0.6


## Karar

**~ Karışık** — manuel inceleme.
