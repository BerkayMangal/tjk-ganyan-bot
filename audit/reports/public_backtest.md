# Public Smart Coupon Backtest — audit/57 Mantığı

**Veri:** 2025-2026 · n=850 altılı (her gün her hipodrom için son 6 koşu)
**At seçimi:** AGF rank 1..k (Public). Model devre dışı.
**At sayısı:** combined = 0.50·L1 + 0.50·L2, cap/floor band.

## Overall

- Altılı tutma oranı: **33.41%** (284/850)
- Mean cost: **2914.98 TL**
- Toplam cost (her gün oynansaydı): **2,477,732 TL** (284 hit)

## Leg hit dağılımı

| Legs hit | n | % |
|---|---|---|
| 1/6 | 3 | 0.4% |
| 2/6 | 9 | 1.1% |
| 3/6 | 50 | 5.9% |
| 4/6 | 178 | 20.9% |
| 5/6 | 326 | 38.4% |
| 6/6 | 284 | 33.4% |

## Per breed × year

| Segment | n | altılı_hit % | mean_cost | mean_legs_hit |
|---|---|---|---|---|
| arab 2025 | 253 | 32.02% | 2937.67 | 4.89 |
| arab 2026 | 98 | 28.57% | 2911.07 | 4.89 |
| english 2025 | 360 | 33.61% | 2886.76 | 4.99 |
| english 2026 | 139 | 38.85% | 2949.52 | 5.06 |

## Mean combined band × altılı hit

| Band | n | altılı_hit | mean_cost |
|---|---|---|---|
| <0.20 | 2 | 50.00% | 2000.00 |
| 0.20-0.30 | 119 | 45.38% | 2844.86 |
| 0.30-0.40 | 421 | 35.63% | 2970.13 |
| ≥0.40 | 308 | 25.65% | 2872.63 |

## Verdict

⚠ Bu **ROI** rakamı değil — TR altılı paylaşımlı havuz, payout = toplam havuz / tutmuş kişi. Mean cost vs altılı hit oranı verisi var.

Eğer altılı_hit %X ve mean_cost Y TL ise, **beklenen payout = Y/X**'in üstündeyse +EV. TR altılı tarihsel payouts genelde 5k-500k arası. Gerçek karar yarışın havuzuna bağlı.
