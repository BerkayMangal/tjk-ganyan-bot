# YIL-YIL STABİLİTE — Top-4/5 Edge Gerçek mi 2026-fluke mu?

3 walk-forward pencere, her birinde 5 hedef × 2 breed.

## ΔAUC = AUC_Model − AUC_AGF (test setinde)

| Window | Breed | Target | N_test | PosRate | AUC_M | AUC_AGF | ΔAUC | Sig |
|---|---|---|---|---|---|---|---|---|
| A_2024test | arab | top1 | 19,059 | 10.2% | 0.6793 | 0.6276 | +0.0517 | ✓ |
| A_2024test | arab | top2 | 19,059 | 20.3% | 0.6871 | 0.6228 | +0.0644 | ✓ |
| A_2024test | arab | top3 | 19,059 | 30.5% | 0.6949 | 0.6234 | +0.0715 | ✓ |
| A_2024test | arab | top4 | 19,059 | 40.6% | 0.7048 | 0.6247 | +0.0801 | ✓ |
| A_2024test | arab | top5 | 19,059 | 50.8% | 0.7151 | 0.6280 | +0.0872 | ✓ |
| A_2024test | english | top1 | 20,817 | 11.6% | 0.6854 | 0.6314 | +0.0540 | ✓ |
| A_2024test | english | top2 | 20,817 | 23.2% | 0.6828 | 0.6252 | +0.0576 | ✓ |
| A_2024test | english | top3 | 20,817 | 35.0% | 0.6991 | 0.6259 | +0.0732 | ✓ |
| A_2024test | english | top4 | 20,817 | 46.9% | 0.7127 | 0.6265 | +0.0862 | ✓ |
| A_2024test | english | top5 | 20,817 | 58.5% | 0.7352 | 0.6319 | +0.1033 | ✓ |
| B_2025test | arab | top1 | 30,403 | 9.9% | 0.6831 | 0.7085 | -0.0254 | ✗ |
| B_2025test | arab | top2 | 30,403 | 19.7% | 0.6944 | 0.7025 | -0.0081 | ✗ |
| B_2025test | arab | top3 | 30,403 | 29.6% | 0.6970 | 0.6968 | +0.0003 | ✓ |
| B_2025test | arab | top4 | 30,403 | 39.4% | 0.7083 | 0.6958 | +0.0125 | ✓ |
| B_2025test | arab | top5 | 30,403 | 49.2% | 0.7274 | 0.7013 | +0.0261 | ✓ |
| B_2025test | english | top1 | 32,862 | 10.9% | 0.7036 | 0.7195 | -0.0159 | ✗ |
| B_2025test | english | top2 | 32,862 | 21.7% | 0.7090 | 0.7119 | -0.0029 | ✗ |
| B_2025test | english | top3 | 32,862 | 32.6% | 0.7167 | 0.7112 | +0.0055 | ✓ |
| B_2025test | english | top4 | 32,862 | 43.4% | 0.7358 | 0.7152 | +0.0207 | ✓ |
| B_2025test | english | top5 | 32,862 | 54.1% | 0.7585 | 0.7175 | +0.0409 | ✓ |
| C_2026test | arab | top1 | 11,597 | 9.5% | 0.7053 | 0.7233 | -0.0180 | ✗ |
| C_2026test | arab | top2 | 11,597 | 18.9% | 0.7224 | 0.7205 | +0.0019 | ✓ |
| C_2026test | arab | top3 | 11,597 | 28.3% | 0.7308 | 0.7209 | +0.0099 | ✓ |
| C_2026test | arab | top4 | 11,597 | 37.8% | 0.7476 | 0.7189 | +0.0287 | ✓ |
| C_2026test | arab | top5 | 11,597 | 47.1% | 0.7619 | 0.7214 | +0.0404 | ✓ |
| C_2026test | english | top1 | 12,711 | 10.9% | 0.7185 | 0.7408 | -0.0222 | ✗ |
| C_2026test | english | top2 | 12,711 | 21.8% | 0.7327 | 0.7331 | -0.0004 | ✗ |
| C_2026test | english | top3 | 12,711 | 32.7% | 0.7450 | 0.7278 | +0.0171 | ✓ |
| C_2026test | english | top4 | 12,711 | 43.5% | 0.7646 | 0.7313 | +0.0333 | ✓ |
| C_2026test | english | top5 | 12,711 | 54.1% | 0.7875 | 0.7347 | +0.0528 | ✓ |

## Stabilite verdict

- **top1/arab**: 1/3 pencere +ΔAUC, mean Δ = +0.0028 → marjinal
- **top1/english**: 1/3 pencere +ΔAUC, mean Δ = +0.0053 → marjinal
- **top4/arab**: 3/3 pencere +ΔAUC, mean Δ = +0.0404 → **STABİL**
- **top4/english**: 3/3 pencere +ΔAUC, mean Δ = +0.0467 → **STABİL**
- **top5/arab**: 3/3 pencere +ΔAUC, mean Δ = +0.0513 → **STABİL**
- **top5/english**: 3/3 pencere +ΔAUC, mean Δ = +0.0657 → **STABİL**
