# MODEL SÜİTİ VALİDASYON — Test Set (2025+)

5 binary target × 2 breed × {XGB+LGBM+isotonic}. Walk-forward: train 2021-2023, val 2024 (isotonic), test 2025-2026.

## AUC: Model vs AGF baseline

| Target | Breed | N | PosRate | AUC_model | AUC_AGF | ΔAUC | Brier | ECE | Beats AGF? |
|---|---|---|---|---|---|---|---|---|---|
| top1 | arab | 42,000 | 9.8% | 0.6762 | 0.7125 | -0.0363 | 0.0851 | 0.0117 | ✗ |
| top2 | arab | 42,000 | 19.5% | 0.6859 | 0.7074 | -0.0215 | 0.1467 | 0.0222 | ✗ |
| top3 | arab | 42,000 | 29.2% | 0.6932 | 0.7034 | -0.0101 | 0.1880 | 0.0323 | ✗ |
| top4 | arab | 42,000 | 39.0% | 0.7026 | 0.7022 | +0.0004 | 0.2116 | 0.0486 | ✓ |
| top5 | arab | 42,000 | 48.6% | 0.7234 | 0.7069 | +0.0164 | 0.2126 | 0.0356 | ✓ |
| top1 | english | 45,573 | 10.9% | 0.6993 | 0.7253 | -0.0260 | 0.0920 | 0.0067 | ✗ |
| top2 | english | 45,573 | 21.7% | 0.7077 | 0.7177 | -0.0101 | 0.1542 | 0.0170 | ✗ |
| top3 | english | 45,573 | 32.6% | 0.7135 | 0.7158 | -0.0023 | 0.1925 | 0.0226 | ✗ |
| top4 | english | 45,573 | 43.4% | 0.7331 | 0.7196 | +0.0134 | 0.2058 | 0.0235 | ✓ |
| top5 | english | 45,573 | 54.1% | 0.7560 | 0.7222 | +0.0338 | 0.1999 | 0.0293 | ✓ |

## DÜRÜST verdict

- 4/10 target×breed kombinasyonunda model **AGF AUC'unu geçti**.
- **Marjinal** — bazı target'larda model üstün, çoğunda değil.
