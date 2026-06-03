# 2026 Negatif Edge Diagnosis — Bounded

Sorun: 2025'te model AGF rank'ı +0.01-0.04 geçiyor; 2026'da AR'da NEGATİF.
Yetersiz n? Veri shift? Yapay sorun?

## Segment istatistikleri

| Seg | N_horses | N_races | Field | AGF_fill | AGF_μ | Fav_AGF | top12_gap | Fav_hit |
|---|---|---|---|---|---|---|---|---|
| 2024_arab | 19,059 | 3,099 | 4.3 | 67.1% | 10.38 | 17.49 | nan | 30.2% |
| 2024_english | 20,817 | 3,724 | 3.7 | 69.0% | 11.62 | 19.66 | nan | 34.8% |
| 2024_all | 39,876 | 6,823 | 4.0 | 68.1% | 11.04 | 18.68 | nan | 32.7% |
| 2025_arab | 30,403 | 3,045 | 10.8 | 88.9% | 9.82 | 29.18 | nan | 30.6% |
| 2025_english | 32,862 | 3,624 | 10.0 | 89.1% | 10.73 | 31.63 | nan | 34.6% |
| 2025_all | 63,265 | 6,669 | 10.4 | 89.0% | 10.29 | 30.51 | nan | 32.8% |
| 2026_arab | 11,597 | 1,094 | 11.5 | 89.6% | 9.43 | 31.08 | nan | 31.7% |
| 2026_english | 12,711 | 1,383 | 10.3 | 92.1% | 10.75 | 34.35 | nan | 36.9% |
| 2026_all | 24,308 | 2,477 | 10.9 | 90.9% | 10.13 | 32.91 | nan | 34.6% |

## 2025 → 2026 değişim

| Metric | 2025 | 2026 | Δ | Δ% |
|---|---|---|---|---|
| arab_agf_mean_nonzero | 9.817 | 9.433 | -0.384 | -3.9% |
| arab_fav_agf_mean | 29.175 | 31.082 | +1.907 | +6.5% |
| arab_mean_field_size | 10.828 | 11.523 | +0.695 | +6.4% |
| arab_top12_gap_mean | nan | nan | +nan | +nan% |
| arab_agf_sum_per_race_mean | 87.186 | 89.623 | +2.437 | +2.8% |
| arab_fav_top1_hit_rate | 0.306 | 0.317 | +0.011 | +3.6% |
| english_agf_mean_nonzero | 10.727 | 10.747 | +0.021 | +0.2% |
| english_fav_agf_mean | 31.628 | 34.355 | +2.727 | +8.6% |
| english_mean_field_size | 10.015 | 10.281 | +0.267 | +2.7% |
| english_top12_gap_mean | nan | nan | +nan | +nan% |
| english_agf_sum_per_race_mean | 86.702 | 90.929 | +4.227 | +4.9% |
| english_fav_top1_hit_rate | 0.346 | 0.369 | +0.023 | +6.7% |

## Verdict

- Sample stat'lar 2025 vs 2026 BENZER (|Δ%| < 10 hepsi). Yapay veri sorunu YOK.
- 2026 n yetersiz olabilir (sample size küçük) — sample variance.
- **VERDICT (DÜRÜST):** Genuine shift veya sample variance — düzeltme yok. Forward'da 1-2 ay daha veri biriktikten sonra re-evaluate. **Tool kullanırken: 2026 AR LOW güven.**
