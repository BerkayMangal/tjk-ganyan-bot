# Coupon V2 — Backtest Raporu

## Kalibrasyon
- AGF/Σ normalize, ayak içi toplam = 1.

## Dilution model
`log(payout) = 13.665 + -0.2933 × avg_winner_agf + hippo_offset`

- RMSE (log): 1.046
- n=2553
- E[payout @ avg_agf=20]: 2437 TL
- E[payout @ avg_agf=10]: 45789 TL

## Walk-forward
- Train: 2016-01-01 → 2021-01-24 (n=2,553)
- Holdout: 2021-01-25 → 2026-03-23 (n=639)

## Backtest tablosu

| Model | Set | N | Active | Hit | HitRate | AvgCost | TotPnL | ROI |
|---|---|---|---|---|---|---|---|---|
| old_tam_sistem | old_train | 2,553 | 2,553 | 235 | 9.20% | 957 TL | -2,395,100 TL | -98.06% |
| v2_always | new_train | 2,553 | 2,553 | 398 | 15.59% | 1531 TL | -3,803,323 TL | -97.27% |
| v2_gated | old_holdout | 2,553 | 0 | 0 | 0.00% | 0 TL | 0 TL | 0.00% |
| old_tam_sistem | new_holdout | 639 | 639 | 68 | 10.64% | 937 TL | -234,367 TL | -39.13% |

## Karar
**V2 yetersiz — A:-69.1% B:0.0% vs eski -39.1% — default OFF**

- Holdout ROI: yeni 0.00% vs eski -39.13%
- Holdout hit: yeni 0.00% vs eski 10.64%
