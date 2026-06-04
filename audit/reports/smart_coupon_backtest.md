# Smart Coupon Backtest — audit/51 Mantığı

**Veri:** 2025-2026 race-level (n=8,205 race)  
**Yöntem:** audit/51 score_leg + cap_floor + pick_horses uygulandı, finish_position ≤ 3/4 ile karşılaştırıldı.

## A. Per Uncertainty Band Hit Rate

| Band | n | hit3 % | hit4 % | mean n_sel | n_top3_caught | n_top4_caught |
|---|---|---|---|---|---|---|
| <0.20 | 1,832 | 82.5% | 93.4% | 3.61 | 1.26/3 | 1.82/4 |
| 0.20-0.40 | 4,501 | 67.5% | 80.9% | 4.10 | 0.95/3 | 1.34/4 |
| 0.40-0.60 | 1,712 | 60.6% | 75.4% | 5.00 | 0.76/3 | 1.10/4 |
| ≥0.60 | 160 | 59.4% | 74.4% | 5.58 | 0.72/3 | 1.01/4 |

## B. Per Breed × Year

| Segment | n | hit3 | hit4 | mean_unc |
|---|---|---|---|---|
| arab 2025 | 2,717 | 69.1% | 83.2% | 0.328 |
| arab 2026 | 987 | 61.1% | 75.2% | 0.356 |
| english 2025 | 3,231 | 72.3% | 84.3% | 0.274 |
| english 2026 | 1,270 | 68.3% | 81.4% | 0.291 |

## C. PARA Arama — Sürpriz Yarışlarda Top-3 Finisher

Filter: combined ≥ 0.40 (7,505 at-yarış).

**AGF rank top-3 finisher dağılımı** (sürpriz yarış):

- AGF rank 1.0: 1228 (16.4%)
- AGF rank 2.0: 1104 (14.7%)
- AGF rank 3.0: 909 (12.1%)
- AGF rank 4.0: 849 (11.3%)
- AGF rank 5.0: 708 (9.4%)
- AGF rank 6.0: 592 (7.9%)
- AGF rank 7.0: 530 (7.1%)
- AGF rank 8.0: 438 (5.8%)
- AGF rank 9.0: 377 (5.0%)
- AGF rank 10.0: 254 (3.4%)

**Underdog (AGF rank ≥5) top-3 oranı:** 40.3%

**Form ortalamaları (top-3 finisher):**

- avg_finish_last3: 5.24
- win_rate_last10: 0.101
- days_since median: 14

**AGF rank × win_rate_last10 (top-3 finisher)**:

```
form_band      0-5%  5-15%  15-30%  30%+
agf_rank_band                           
1-2(fav)        688    620     480   156
3-4             581    456     249    64
5-6             376    322     189    31
7+              672    447     189    39
```

## Verdict

- En yüksek hit4 oranı: **<0.20** (93.4%)
- En düşük: **≥0.60** (74.4%)
- En güçlü segment: **english 2025** (hit4 84.3%)
- En zayıf segment: **arab 2026** (hit4 75.2%)

**PARA mesajı:** Sürpriz yarışlarda (combined ≥ 0.40) underdog (AGF rank ≥5) top-3 oranı %40 — baseline'a göre sapma analizi için audit/55 (sonraki tur).
