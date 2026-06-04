# Kombi Bahis Gerçek Payout Backtest (audit/67)

**Veri:** bettings.csv 2021-2026 · 23,578 race ile AGF eşleşmesi.

**Yöntem:** AGF top-N atları + EXPAND (0/1/2) ile kombi kuponları.
Per yarış: cost = n_kombi TL, return = sum(payout) match olan kombi(ler).
ROI per 1 TL staked = mean(return/cost) − 1. Bootstrap 95% CI.

## Overall ROI per bet_type × expand

| bet_type | expand | n | kombi | hit% | ROI | CI 95% | sig |
|---|---|---|---|---|---|---|---|
| GANYAN | +0 | 10,820 | 1 | 30.1% | -35.20% | [-37.24, -33.16] | ✗ |
| GANYAN | +1 | 10,820 | 2 | 48.5% | -35.54% | [-37.08, -34.00] | ✗ |
| GANYAN | +2 | 10,820 | 3 | 61.1% | -36.55% | [-37.85, -35.35] | ✗ |
| İKİLİ | +0 | 9,433 | 1 | 11.7% | -44.17% | [-48.37, -40.01] | ✗ |
| İKİLİ | +1 | 9,433 | 3 | 25.8% | -40.26% | [-42.92, -37.56] | ✗ |
| İKİLİ | +2 | 9,433 | 6 | 39.1% | -39.86% | [-42.14, -37.46] | ✗ |
| SIRALI İKİLİ | +0 | 10,813 | 2 | 13.4% | -43.00% | [-46.72, -38.84] | ✗ |
| SIRALI İKİLİ | +1 | 10,813 | 6 | 28.8% | -40.96% | [-43.59, -38.30] | ✗ |
| SIRALI İKİLİ | +2 | 10,813 | 12 | 42.8% | -40.18% | [-42.49, -37.95] | ✗ |
| ÜÇLÜ BAHİS | +0 | 5,413 | 6 | 9.1% | -34.57% | [-43.02, -24.78] | ✗ |
| ÜÇLÜ BAHİS | +1 | 5,413 | 24 | 22.1% | -29.80% | [-39.45, -17.38] | ✗ |
| ÜÇLÜ BAHİS | +2 | 5,413 | 60 | 36.1% | -31.47% | [-37.19, -25.08] | ✗ |
| TABELA BAHİS | +0 | 1,527 | 24 | 1.7% | -74.25% | [-85.40, -60.43] | ✗ |
| TABELA BAHİS | +1 | 1,527 | 120 | 5.4% | -72.04% | [-79.35, -63.80] | ✗ |
| TABELA BAHİS | +2 | 1,527 | 360 | 11.3% | -71.65% | [-77.84, -64.73] | ✗ |
| TABELA BAHİS SIRASIZ | +0 | 1,549 | 1 | 1.7% | -88.94% | [-93.72, -83.38] | ✗ |
| TABELA BAHİS SIRASIZ | +1 | 1,549 | 5 | 5.4% | -87.00% | [-90.51, -83.25] | ✗ |
| TABELA BAHİS SIRASIZ | +2 | 1,549 | 15 | 11.2% | -86.66% | [-89.56, -83.37] | ✗ |

## En iyi segment slice (ROI desc, n≥150)

| bet_type | exp | breed | yr | field | n | hit% | ROI | CI 95% | sig |
|---|---|---|---|---|---|---|---|---|---|

## VERDICT

❌ Hiçbir bet_type×expand×segment'te anlamlı +EV YOK. Pari-mutuel takeout yapısal olarak negatif. Plase gibi.
