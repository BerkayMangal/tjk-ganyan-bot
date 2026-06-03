# EXACT Harville Baseline — SANITY GATE

`top_k_membership_probs` exact tüm permütasyon. MC artefakt'ı yok.

## Sanity Gate: AUC_AGF_Harville_exact ≈ AUC_AGF_rank (|Δ| < 0.02)

| Year | Breed | Target | N | AUC_AGF_rank | AUC_AGF_Harv_exact | |Δ| | Sanity |
|---|---|---|---|---|---|---|---|
| 2025 | arab | top2 | 30,403 | 0.7025 | 0.7226 | 0.0201 | ✗ BOZUK |
| 2025 | arab | top3 | 30,403 | 0.6968 | 0.7172 | 0.0204 | ✗ BOZUK |
| 2025 | arab | top4 | 30,403 | 0.6958 | 0.7183 | 0.0224 | ✗ BOZUK |
| 2025 | english | top2 | 32,862 | 0.7119 | 0.7302 | 0.0183 | ✓ |
| 2025 | english | top3 | 32,862 | 0.7112 | 0.7294 | 0.0182 | ✓ |
| 2025 | english | top4 | 32,862 | 0.7152 | 0.7360 | 0.0208 | ✗ BOZUK |
| 2026 | arab | top2 | 11,597 | 0.7205 | 0.7373 | 0.0168 | ✓ |
| 2026 | arab | top3 | 11,597 | 0.7209 | 0.7373 | 0.0164 | ✓ |
| 2026 | arab | top4 | 11,597 | 0.7189 | 0.7381 | 0.0192 | ✓ |
| 2026 | english | top2 | 12,711 | 0.7331 | 0.7549 | 0.0219 | ✗ BOZUK |
| 2026 | english | top3 | 12,711 | 0.7278 | 0.7514 | 0.0236 | ✗ BOZUK |
| 2026 | english | top4 | 12,711 | 0.7313 | 0.7565 | 0.0252 | ✗ BOZUK |

**Genel sanity:** ✗ BOZUK — bazi baseline sisik

## DÜRÜST ΔAUC (Model vs hem rank hem Harville exact)

| Year | Breed | Target | AUC_Model | Δ_vs_rank | Δ_vs_Harville_exact |
|---|---|---|---|---|---|
| 2025 | arab | top2 | 0.7146 | +0.0121 | -0.0080 |
| 2025 | arab | top3 | 0.7165 | +0.0197 | -0.0007 |
| 2025 | arab | top4 | 0.7270 | +0.0312 | +0.0088 |
| 2025 | english | top2 | 0.7286 | +0.0167 | -0.0016 |
| 2025 | english | top3 | 0.7345 | +0.0233 | +0.0051 |
| 2025 | english | top4 | 0.7516 | +0.0364 | +0.0156 |
| 2026 | arab | top2 | 0.6981 | -0.0224 | -0.0392 |
| 2026 | arab | top3 | 0.7035 | -0.0174 | -0.0337 |
| 2026 | arab | top4 | 0.7142 | -0.0047 | -0.0240 |
| 2026 | english | top2 | 0.7297 | -0.0034 | -0.0253 |
| 2026 | english | top3 | 0.7295 | +0.0016 | -0.0219 |
| 2026 | english | top4 | 0.7457 | +0.0144 | -0.0108 |
