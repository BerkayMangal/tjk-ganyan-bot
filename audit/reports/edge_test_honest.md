# DÜRÜST Edge Testi — Model vs Public vs Random

**Veri:** 2025-2026 race-level (n=8,205 race)
**Yöntem:** Aynı leg, Model'in seçtiği k atı vs Public'in (AGF rank 1..k) vs Random k base rate. Paired McNemar.

## İŞ 1 — hit-K Model vs Public vs Random

**hit3:**

| Band | n | Model | Public | Random | M-P | p (McNemar) | sig |
|---|---|---|---|---|---|---|---|
| <0.20 | 1,832 | 82.5% | 99.2% | 93.8% | -16.7pp | 0.0000 | ✓ |
| 0.20-0.40 | 4,501 | 67.5% | 99.0% | 86.6% | -31.5pp | 0.0000 | ✓ |
| 0.40-0.60 | 1,712 | 60.6% | 98.0% | 81.2% | -37.3pp | 0.0000 | ✓ |
| ≥0.60 | 160 | 59.4% | 94.4% | 79.4% | -35.0pp | 0.0000 | ✓ |

**hit4:**

| Band | n | Model | Public | Random | M-P | p (McNemar) | sig |
|---|---|---|---|---|---|---|---|
| <0.20 | 1,832 | 93.4% | 99.7% | 98.2% | -6.3pp | 0.0000 | ✓ |
| 0.20-0.40 | 4,501 | 80.9% | 99.7% | 93.9% | -18.8pp | 0.0000 | ✓ |
| 0.40-0.60 | 1,712 | 75.4% | 99.5% | 90.2% | -24.2pp | 0.0000 | ✓ |
| ≥0.60 | 160 | 74.4% | 96.9% | 89.0% | -22.5pp | 0.0000 | ✓ |

## İŞ 1b — Per breed × year × band (hit4)

| Band | Breed | Year | n | Model | Public | Random | M-P | p |
|---|---|---|---|---|---|---|---|---|
| <0.20 | arab | 2025 | 406 | 94.1% | 100.0% | 98.2% | -5.9pp | 0.0000 |
| <0.20 | arab | 2026 | 131 | 92.4% | 100.0% | 98.8% | -7.6pp | 0.0020 |
| <0.20 | english | 2025 | 920 | 92.2% | 99.5% | 97.9% | -7.3pp | 0.0000 |
| <0.20 | english | 2026 | 375 | 96.3% | 100.0% | 99.0% | -3.7pp | 0.0001 |
| 0.20-0.40 | arab | 2025 | 1,563 | 82.1% | 99.6% | 93.6% | -17.5pp | 0.0000 |
| 0.20-0.40 | arab | 2026 | 499 | 73.7% | 99.8% | 93.5% | -26.1pp | 0.0000 |
| 0.20-0.40 | english | 2025 | 1,820 | 82.8% | 99.8% | 94.2% | -17.0pp | 0.0000 |
| 0.20-0.40 | english | 2026 | 619 | 77.7% | 99.7% | 94.3% | -22.0pp | 0.0000 |
| 0.40-0.60 | arab | 2025 | 680 | 79.3% | 99.6% | 90.4% | -20.3pp | 0.0000 |
| 0.40-0.60 | arab | 2026 | 309 | 70.6% | 99.4% | 90.5% | -28.8pp | 0.0000 |
| 0.40-0.60 | english | 2025 | 467 | 75.6% | 99.8% | 89.7% | -24.2pp | 0.0000 |
| 0.40-0.60 | english | 2026 | 256 | 70.3% | 99.2% | 90.4% | -28.9pp | 0.0000 |
| ≥0.60 | arab | 2025 | 68 | 80.9% | 97.1% | 89.7% | -16.2pp | 0.0074 |
| ≥0.60 | arab | 2026 | 48 | 72.9% | 93.8% | 89.0% | -20.8pp | 0.0129 |

## İŞ 2 — leg-WIN (winner inclusion)

Altılı gerçek metriği: kupon altılıyı tutmak için her ayakta WINNER seçili olmalı, top-4 inclusion DEĞİL. Naive altılı = prod(leg_win)^6.

| Band | n | Model | Public | Random | M-P | p (McNemar) | Model^6 | Public^6 |
|---|---|---|---|---|---|---|---|---|
| <0.20 | 1,832 | 35.8% | 84.9% | 55.2% | -49.2pp | — | 0.21% | 37.54% |
| 0.20-0.40 | 4,501 | 26.2% | 81.2% | 46.1% | -55.0pp | — | 0.03% | 28.72% |
| 0.40-0.60 | 1,712 | 21.7% | 76.1% | 40.1% | -54.4pp | — | 0.01% | 19.35% |
| ≥0.60 | 160 | 25.6% | 65.6% | 38.3% | -40.0pp | — | 0.03% | 7.99% |

**Overall**: Model winner-incl = 27.4%, Public = 80.7%. Altılı: Model 0.04% vs Public 27.56%.

⚠ **0.934^6 ≈ %65 yanlış** çünkü top-4 inclusion altılı'da geçerli değil. Doğru altılı = leg_WIN^6. Yukarıdaki rakamlar doğru baz.

## İŞ 3 — Underdog (AGF rank ≥5) in sürpriz race

- Total rank≥5 atlar in sürpriz race (combined≥0.40): **16,160**
- Top-3 finisher: **2,265 (14.0%)**
- 95% CI: [13.5%, 14.6%]
- Base rate (3/N): **22.7%**
- Observed − Base: **-8.66pp**
- Binomial p (H0: rate = base): 0.0000

### Ex-ante predictability (within rank≥5 atlar)

- AUC(model_top3 vs actual top-3): **0.631** (distinguishes)
- AUC(win_rate_last10 vs actual top-3): **0.504**

**İŞ 3 verdict:** rate < base, anlamlı (underdog'lar BEKLENENDEN DAHA AZ top-3 yapıyor); model ex-ante distinguish edebiliyor

## NET VERDICT


❌ **Model PUBLIC'i hit4'te anlamlı geçemiyor.** Mutlak hit oranı yüksek ama bu base-rate serabı — Public da aynı oranlarda tutuyor. Model edge yok veya ölçülemez.
