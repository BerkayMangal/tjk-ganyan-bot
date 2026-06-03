# Harville AGF Baseline (Fast MC) — DÜZGÜN ΔAUC top-2/3/4

AGF top-k implied = `fast_harville_topk_mc` (Plackett-Luce sampling M=500).
Eski kaba proxy `5×p` YANLIŞ; bu DOĞRU baseline.

## ΔAUC tablosu (top-2/3/4 — BETTABLE hedefler)

| Year | Breed | Target | N | AUC_Model | AUC_AGF_rank | AUC_AGF_Harville | Δ_vs_Harville |
|---|---|---|---|---|---|---|---|
| 2025 | arab | top2 | 30,403 | 0.7132 | 0.7025 | 0.6009 | +0.1123 |
| 2025 | arab | top3 | 30,403 | 0.7175 | 0.6968 | 0.6118 | +0.1057 |
| 2025 | arab | top4 | 30,403 | 0.7270 | 0.6958 | 0.6264 | +0.1005 |
| 2025 | english | top2 | 32,862 | 0.7283 | 0.7119 | 0.6037 | +0.1247 |
| 2025 | english | top3 | 32,862 | 0.7345 | 0.7112 | 0.6219 | +0.1126 |
| 2025 | english | top4 | 32,862 | 0.7527 | 0.7152 | 0.6420 | +0.1107 |
| 2026 | arab | top2 | 11,597 | 0.6980 | 0.7205 | 0.6190 | +0.0791 |
| 2026 | arab | top3 | 11,597 | 0.7078 | 0.7209 | 0.6319 | +0.0759 |
| 2026 | arab | top4 | 11,597 | 0.7140 | 0.7189 | 0.6424 | +0.0716 |
| 2026 | english | top2 | 12,711 | 0.7276 | 0.7331 | 0.6275 | +0.1001 |
| 2026 | english | top3 | 12,711 | 0.7309 | 0.7278 | 0.6453 | +0.0855 |
| 2026 | english | top4 | 12,711 | 0.7458 | 0.7313 | 0.6660 | +0.0797 |

## Verdict

- 12/12 (year × breed × target) MODEL Harville baseline'ı GEÇTİ.
- En güçlü edge: **2025 english top2 ΔAUC = +0.1247**
