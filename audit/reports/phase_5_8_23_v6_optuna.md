# Phase 5.8.23 — V6 Optuna 100-trial (top-3 NDCG objective)
_Tarih: 2026-06-15T15:50:01.488453Z_

## Optuna

- n_trials: 100
- best val NDCG@3 mean: **0.8535**
- search space: XGB+LGBM+CB hyperparams + ensemble weights (23 dim)

## Test set Top-K hit (≥2025-05-24)

| Breed | Model | top1 | top3 | top4 |
|---|---|---|---|---|
| arab | V6 baseline | 26.66% | 60.15% | 70.76% |
| arab | V6 Optuna | **26.16%** | **57.59%** | **68.34%** |
| arab | **Δ Optuna−base** | -0.50pp | -2.55pp | -2.42pp |
| english | V6 baseline | 27.13% | 60.81% | 72.22% |
| english | V6 Optuna | **27.21%** | **60.40%** | **71.59%** |
| english | **Δ Optuna−base** | +0.08pp | -0.41pp | -0.63pp |

## Best params

```json
{
  "xgb_n_estimators": 935,
  "xgb_max_depth": 5,
  "xgb_lr": 0.026632014084149804,
  "xgb_subsample": 0.7285136799084334,
  "xgb_colsample": 0.8615747183695974,
  "xgb_min_child": 9,
  "xgb_gamma": 0.09107431515783679,
  "xgb_alpha": 0.6329531215444795,
  "xgb_lambda": 1.5448523221813775,
  "lgbm_n_estimators": 755,
  "lgbm_max_depth": 7,
  "lgbm_lr": 0.042737226126972935,
  "lgbm_num_leaves": 62,
  "lgbm_subsample": 0.8352166210549662,
  "lgbm_colsample": 0.8235153921843046,
  "lgbm_min_child": 7,
  "lgbm_alpha": 0.605243681157928,
  "lgbm_lambda": 4.15185127068865,
  "cb_iterations": 795,
  "cb_depth": 7,
  "cb_lr": 0.055700647521454504,
  "cb_l2": 8.308236697883068,
  "w_xgb": 0.5594402492366033,
  "w_lgbm": 0.2953939812139863
}
```
