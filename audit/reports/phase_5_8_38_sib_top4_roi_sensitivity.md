# Phase 5.8.38 — SİB top4 ROI sensitivity
_Run: 2026-06-17T14:24:11.224414Z_

## Kaynak

- hit_rate: audit/129 walk-forward (V7 ranker, n_races=6,734, cutoff ≥ 2025-05-24)
- payout sweep: 1.10× → 3.00× (TJK SİB public scraper yok, sözlü tahmin)
- Kelly: f = (p×b − q)/b, b=payout−1
- Half-Kelly (önerilen): variance koruma, drawdown azaltma
- bankroll: 1000TL (per gün, tüm pick'ler bu bankroll'dan paylaşır)

## Strateji × break-even payout

| Strategy | hit | break-even payout |
|---|---|---|
| ALTIN (İstanbul+12+at+mp 35-45) | 89.7% | **1.115×** |
| FIRSAT (mp 25-35+gap≥15) | 81.2% | **1.232×** |
| MODEL_top1 (V7 ham) | 79.7% | **1.255×** |
| AGF_top1 (halk favorisi) | 75.1% | **1.332×** |
| PREMIUM (12+at+mp 35-45 İst-dışı) | 74.7% | **1.339×** |
| RANDOM (4/field) | 46.6% | **2.146×** |

## ROI matrix (hit × payout − 1)

| Strategy | 1.1× | 1.2× | 1.25× | 1.3× | 1.4× | 1.5× | 1.75× | 2.0× | 2.5× | 3.0× |
|---|---|---|---|---|---|---|---|---|---|---|
| ALTIN (İstanbul+12+at+mp 35-45) | -1.3% | **++7.6%** | **++12.1%** | **++16.6%** | **++25.6%** | **++34.5%** | **++57.0%** | **++79.4%** | **++124.3%** | **++169.1%** |
| FIRSAT (mp 25-35+gap≥15) | -10.7% | -2.6% | ++1.5% | **++5.6%** | **++13.7%** | **++21.8%** | **++42.1%** | **++62.4%** | **++103.0%** | **++143.6%** |
| MODEL_top1 (V7 ham) | -12.3% | -4.4% | -0.4% | ++3.6% | **++11.6%** | **++19.6%** | **++39.5%** | **++59.4%** | **++99.3%** | **++139.1%** |
| AGF_top1 (halk favorisi) | -17.4% | -9.9% | -6.1% | -2.4% | **++5.1%** | **++12.7%** | **++31.4%** | **++50.2%** | **++87.8%** | **++125.3%** |
| PREMIUM (12+at+mp 35-45 İst-dışı) | -17.8% | -10.4% | -6.6% | -2.9% | ++4.6% | **++12.1%** | **++30.7%** | **++49.4%** | **++86.8%** | **++124.1%** |
| RANDOM (4/field) | -48.7% | -44.1% | -41.8% | -39.4% | -34.8% | -30.1% | -18.4% | -6.8% | **++16.5%** | **++39.8%** |

## Kelly fraction (bankroll %)

| Strategy | 1.1× | 1.2× | 1.25× | 1.3× | 1.4× | 1.5× | 1.75× | 2.0× | 2.5× | 3.0× |
|---|---|---|---|---|---|---|---|---|---|---|
| ALTIN (İstanbul+12+at+mp 35-45) | 0.0% | 38.2% | 48.5% | 55.4% | 64.0% | 69.1% | 76.0% | 79.4% | 82.8% | 84.5% |
| FIRSAT (mp 25-35+gap≥15) | 0.0% | 0.0% | 6.0% | 18.5% | 34.2% | 43.6% | 56.1% | 62.4% | 68.7% | 71.8% |
| MODEL_top1 (V7 ham) | 0.0% | 0.0% | 0.0% | 12.0% | 29.0% | 39.1% | 52.6% | 59.4% | 66.2% | 69.5% |
| AGF_top1 (halk favorisi) | 0.0% | 0.0% | 0.0% | 0.0% | 12.8% | 25.3% | 41.9% | 50.2% | 58.5% | 62.7% |
| PREMIUM (12+at+mp 35-45 İst-dışı) | 0.0% | 0.0% | 0.0% | 0.0% | 11.4% | 24.1% | 41.0% | 49.4% | 57.8% | 62.1% |
| RANDOM (4/field) | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% | 11.0% | 19.9% |

## Günlük PnL projection (half-Kelly, bankroll=1000TL)

| Strategy | avail/gün | 1.1× | 1.2× | 1.25× | 1.3× | 1.4× | 1.5× | 1.75× | 2.0× | 2.5× | 3.0× |
|---|---|---|---|---|---|---|---|---|---|---|---|
| ALTIN (İstanbul+12+at+mp 35-45) | 0.4 | -0.0TL | +5.8TL | +11.8TL | +18.4TL | +32.7TL | +47.7TL | +86.6TL | +126.1TL | +205.8TL | +285.9TL |
| FIRSAT (mp 25-35+gap≥15) | 3.0 | -0.0TL | -0.0TL | +1.4TL | +15.5TL | +70.2TL | +142.6TL | +354.5TL | +584.1TL | +1060.9TL | +1546.6TL |
| MODEL_top1 (V7 ham) | 6.0 | -0.0TL | -0.0TL | -0.0TL | +13.0TL | +100.6TL | +229.3TL | +623.3TL | +1058.5TL | +1970.1TL | +2902.3TL |
| AGF_top1 (halk favorisi) | 6.0 | -0.0TL | -0.0TL | -0.0TL | -0.0TL | +19.8TL | +96.0TL | +395.0TL | +756.0TL | +1540.0TL | +2355.0TL |
| PREMIUM (12+at+mp 35-45 İst-dışı) | 1.5 | -0.0TL | -0.0TL | -0.0TL | -0.0TL | +3.9TL | +21.8TL | +94.4TL | +183.0TL | +376.3TL | +577.5TL |
| RANDOM (4/field) | 6.0 | -0.0TL | -0.0TL | -0.0TL | -0.0TL | -0.0TL | -0.0TL | -0.0TL | -0.0TL | +54.5TL | +237.6TL |

## Yorum + öneriler

1. **Break-even**: ALTIN ≥1.115× / FIRSAT ≥1.231× / Model_top1 ≥1.255× / PREMIUM ≥1.339×
2. **Pratik gerçek payout aralığı (Berkay sözlü tahmini gerekir)** TR SİB top4: 1.30×-2.00× tipik.
3. **Eğer ortalama payout ≈ 1.5×**:
   - ALTIN (İstanbul+12+at+mp 35-45): ROI = **+34.5%** per bet, half-Kelly = **35%** bankroll
   - FIRSAT (mp 25-35+gap≥15): ROI = **+21.8%** per bet, half-Kelly = **22%** bankroll
   - MODEL_top1 (V7 ham): ROI = **+19.6%** per bet, half-Kelly = **20%** bankroll
   - AGF_top1 (halk favorisi): ROI = **+12.7%** per bet, half-Kelly = **13%** bankroll
   - PREMIUM (12+at+mp 35-45 İst-dışı): ROI = **+12.1%** per bet, half-Kelly = **12%** bankroll
   - RANDOM (4/field): ROI = **-30.1%** per bet, half-Kelly = **0%** bankroll

4. **Strateji önceliklendirme** (uniform 1.5× payout varsayımı):
   1. **ALTIN (İstanbul+12+at+mp 35-45)** (ROI +34.5% per bet, avail/gün 0.4)
   2. **FIRSAT (mp 25-35+gap≥15)** (ROI +21.8% per bet, avail/gün 3.0)
   3. **MODEL_top1 (V7 ham)** (ROI +19.6% per bet, avail/gün 6.0)
   4. **AGF_top1 (halk favorisi)** (ROI +12.7% per bet, avail/gün 6.0)

5. **PREMIUM uniform 1.5×'te marjinal** (+%12 ROI per bet ama hit %74.7 ham MODEL'den kötü);
   farklı paylaşıma izin verirsen `TJK_SIB_PREMIUM_DISABLE=1` Railway env.
6. **Half-Kelly öneri**: full-Kelly variance büyük; half-Kelly maksimum büyüme'nin **%75'ini** korur
   ama drawdown'u **%50** azaltır. Quarter-Kelly daha temkinli.
7. **Gerçek payout için Berkay'ın elinde**: son 10-20 oynanan pick'in kazanç oranı.
   Bunlar paylaşılınca matris üzerinden hassas öneri çıkar.
