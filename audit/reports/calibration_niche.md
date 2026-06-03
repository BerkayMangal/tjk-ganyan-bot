# Kalibrasyon — ECE + Flag-Bölgesi Reliability (v4)

## ECE (10-bin) per breed × yıl × target

| Year | Breed | Target | N | ECE | Flag N | Flag Pred | Flag Obs | Δ |
|---|---|---|---|---|---|---|---|---|
| 2025 | arab | top3 | 30,403 | 0.0412 | 1,494 | 52.8% | 42.6% | +0.103 ✗ aşırı güven |
| 2025 | arab | top4 | 30,403 | 0.0618 | 5,022 | 50.9% | 46.2% | +0.047 ✓ OK |
| 2025 | english | top3 | 32,862 | 0.0276 | 3,019 | 52.7% | 42.3% | +0.104 ✗ aşırı güven |
| 2025 | english | top4 | 32,862 | 0.0403 | 6,867 | 55.3% | 49.2% | +0.061 ✓ OK |
| 2026 | arab | top3 | 11,597 | 0.0177 | 808 | 51.5% | 34.2% | +0.173 ✗ aşırı güven |
| 2026 | arab | top4 | 11,597 | 0.0223 | 2,870 | 50.8% | 39.0% | +0.119 ✗ aşırı güven |
| 2026 | english | top3 | 12,711 | 0.0152 | 1,619 | 52.6% | 38.1% | +0.145 ✗ aşırı güven |
| 2026 | english | top4 | 12,711 | 0.0222 | 3,115 | 56.0% | 45.1% | +0.109 ✗ aşırı güven |

## Verdict

⚠ Flag-bölgesinde **AŞIRI GÜVEN** (6 segment): longshot tahminleri sistematik üst-fiyatlanmış.
- 2025 arab top3: predicted %52.8 vs observed %42.6 (Δ +10.3pp)
- 2025 english top3: predicted %52.7 vs observed %42.3 (Δ +10.4pp)
- 2026 arab top3: predicted %51.5 vs observed %34.2 (Δ +17.3pp)
- 2026 arab top4: predicted %50.8 vs observed %39.0 (Δ +11.9pp)
- 2026 english top3: predicted %52.6 vs observed %38.1 (Δ +14.5pp)
- 2026 english top4: predicted %56.0 vs observed %45.1 (Δ +10.9pp)

Düzeltme: longshot bölgede flag'lere 'düşük güven' etiketi.
