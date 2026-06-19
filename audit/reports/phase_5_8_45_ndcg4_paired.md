# Phase 5.8.45 — V7 LambdaRank ndcg@4 Paired vs V7
_Tarih: 2026-06-19T11:32:54.294274Z_  ·  _Cutoff: 2025-05-24_

Top4 odaklı loss: XGBRanker rank:ndcg + ndcg_exp_gain=False, LGBMRanker lambdarank label_gain=[0,1,2,4,8,16] eval_at=[4], CatBoostRanker YetiRank.

Relevance label: pos1=5, pos2=4, pos3=3, pos4=2, pos≥5=0

### ARAB (test n_races=2,991)

| Metric | V7 (pairwise) | V7-ndcg@4 | Δ |
|---|---|---|---|
| top1 | 28.25% | 30.09% | +1.84pp |
| top2 | 48.55% | 49.15% | +0.60pp |
| top3 | 62.62% | 63.46% | +0.84pp |
| top4 | 72.58% | 74.06% | +1.47pp |
| top5 | 80.54% | 81.61% | +1.07pp |

### ENGLISH (test n_races=3,588)

| Metric | V7 (pairwise) | V7-ndcg@4 | Δ |
|---|---|---|---|
| top1 | 29.29% | 30.88% | +1.59pp |
| top2 | 48.91% | 50.67% | +1.76pp |
| top3 | 62.99% | 64.46% | +1.48pp |
| top4 | 75.00% | 75.81% | +0.81pp |
| top5 | 82.33% | 84.25% | +1.92pp |

## Karar

**✓ ndcg@4 top4'te V7'i geçiyor** — yerli_engine'a SHADOW olarak entegre edilebilir.
