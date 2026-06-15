# Phase 5.8.9 — V5 Dataset (races_v5.csv) Builder Raporu
_Tarih: 2026-06-15T08:00:41.334226Z_  ·  _Kaynak: races_v3.csv (245,139 satır)_

## Eklenen 3 feature

| Feature | Tip | Anlam |
|---|---|---|
| `mf__jockey_cond_top4` | float 0-1 | jokey × mesafe band × track ilk-4 oranı |
| `mf__jockey_cond_win` | float 0-1 | aynı bucket win oranı |
| `mf__jockey_cond_n` | int | bucket örneklem boyutu (≥20 eligible, -1 fallback, 0 yok) |

## Kapsam

- Toplam satır: **245,139**
- Conditional eligible (n ≥ 20): **236,059** (96.3%)
- Fallback overall (cond_n=-1): **7,954** (3.2%)
- No data (cond_n=0): **1,126** (0.5%)

## Feature distribution (eligible bucket icinde)

- `cond_top4` mean: 0.4253
- `cond_win` mean:  0.1060
- `cond_n` median:  317

## Çıktı

- `data/training_v5/races_v5.csv` (188.0 MB, 114 cols)

## Sonraki adım

- Adım 3: `audit/95_train_v5.py` — feature_columns_v5.json üret + XGB+LGBM eğit
