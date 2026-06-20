# Phase 5.8.54 — TOP-3/TOP-4 Segment Analysis
_Run: 2026-06-20T05:28:42.714571Z_

## Setup

- Test set: races_v7.csv ≥ 2025-05-24 (6,579 yarış)
- Model: V7-ndcg@4 (trained_v7_225, Phase 5.8.45)
- Strateji: per-yarış model top1 atının actual top-K'da olma yüzdesi

## Global baseline

- top1 (kazanır): **32.06%**
- top3 (plase):   **67.24%**
- top4 (tabela):  **77.70%**

## Segment'ler — model nerede daha güçlü?

### 🏆 Yarış sınıfı (min n=30)

| class | n | top1 | top3 | top4 |
|---|---|---|---|---|
| Diğer | 6,579 | 32.1% | 67.2% | **77.7%** |

### 🐎 Field size (min n=50)

| field_band | n | top1 | top3 | top4 |
|---|---|---|---|---|
| küçük (≤8) | 2,556 | 36.5% | 75.1% | **85.5%** |
| orta (9-11) | 2,294 | 32.2% | 66.4% | **76.7%** |
| büyük (12-14) | 1,286 | 26.0% | 57.7% | **69.1%** |
| devasa (15+) | 443 | 23.7% | 54.0% | **63.0%** |

### 📏 Mesafe (min n=50)

| distance_band | n | top1 | top3 | top4 |
|---|---|---|---|---|
| stayer (1800-2400) | 2,078 | 32.9% | 69.0% | **78.7%** |
| middle (1400-1800) | 2,428 | 33.2% | 67.2% | **78.1%** |
| sprint (<1400) | 2,065 | 29.7% | 65.5% | **76.1%** |

### 🛤 Pist tipi (min n=50)

| track_type | n | top1 | top3 | top4 |
|---|---|---|---|---|
| dirt | 4,006 | 33.5% | 68.5% | **78.8%** |
| synthetic | 840 | 32.0% | 67.9% | **76.9%** |
| turf | 1,733 | 28.7% | 64.0% | **75.5%** |

### 🏟 Hipodrom (min n=50)

| hippodrome | n | top1 | top3 | top4 |
|---|---|---|---|---|
| Antalya Hipodromu | 408 | 36.5% | 73.5% | **82.6%** |
| Ankara 75. Yıl Hipodromu | 784 | 31.5% | 70.5% | **81.5%** |
| Adana Yeşiloba Hipodromu | 810 | 34.3% | 69.3% | **80.2%** |
| İzmir Şirinyer Hipodromu | 1,051 | 34.5% | 69.4% | **79.4%** |
| Bursa Osmangazi Hipodromu | 809 | 32.4% | 69.1% | **79.2%** |
| Kocaeli Kartepe Hipodromu | 346 | 34.4% | 67.6% | **78.9%** |
| İstanbul Veliefendi Hipodromu | 1,222 | 30.2% | 65.2% | **75.9%** |
| Elazığ Hipodromu | 408 | 32.4% | 63.2% | **73.0%** |
| Şanlıurfa Hipodromu | 478 | 27.2% | 58.2% | **69.2%** |
| Diyarbakır Hipodromu | 263 | 22.8% | 58.9% | **68.8%** |

### 🐴 Cins (min n=100)

| breed | n | top1 | top3 | top4 |
|---|---|---|---|---|
| english | 3,588 | 34.5% | 70.2% | **80.4%** |
| arab | 2,991 | 29.2% | 63.8% | **74.5%** |

## ⭐ En güçlü çapraz subset'ler (class × field × pist, min n=20)

| Combo | n | top1 | top3 | top4 |
|---|---|---|---|---|
| Diğer · küçük (≤8) · turf | 663 | 32.1% | 73.0% | **85.8%** |
| Diğer · küçük (≤8) · dirt | 1607 | 37.9% | 76.1% | **85.7%** |
| Diğer · küçük (≤8) · synthetic | 286 | 38.5% | 74.5% | **83.9%** |
| Diğer · orta (9-11) · dirt | 1421 | 34.1% | 68.0% | **78.3%** |
| Diğer · orta (9-11) · synthetic | 309 | 32.7% | 68.9% | **77.3%** |
| Diğer · orta (9-11) · turf | 564 | 27.1% | 61.0% | **72.3%** |
| Diğer · büyük (12-14) · synthetic | 175 | 22.9% | 60.0% | **71.4%** |
| Diğer · büyük (12-14) · dirt | 707 | 26.6% | 57.7% | **69.6%** |
| Diğer · büyük (12-14) · turf | 404 | 26.2% | 56.7% | **67.1%** |
| Diğer · devasa (15+) · dirt | 271 | 22.9% | 54.6% | **64.9%** |
| Diğer · devasa (15+) · synthetic | 70 | 25.7% | 55.7% | **60.0%** |
| Diğer · devasa (15+) · turf | 102 | 24.5% | 51.0% | **59.8%** |

## ⚠ En zayıf çapraz subset'ler (KAÇIN)

| Combo | n | top1 | top3 | top4 |
|---|---|---|---|---|
| Diğer · devasa (15+) · turf | 102 | 24.5% | 51.0% | **59.8%** |
| Diğer · devasa (15+) · synthetic | 70 | 25.7% | 55.7% | **60.0%** |
| Diğer · devasa (15+) · dirt | 271 | 22.9% | 54.6% | **64.9%** |
| Diğer · büyük (12-14) · turf | 404 | 26.2% | 56.7% | **67.1%** |
| Diğer · büyük (12-14) · dirt | 707 | 26.6% | 57.7% | **69.6%** |
| Diğer · büyük (12-14) · synthetic | 175 | 22.9% | 60.0% | **71.4%** |
| Diğer · orta (9-11) · turf | 564 | 27.1% | 61.0% | **72.3%** |
| Diğer · orta (9-11) · synthetic | 309 | 32.7% | 68.9% | **77.3%** |
| Diğer · orta (9-11) · dirt | 1421 | 34.1% | 68.0% | **78.3%** |
| Diğer · küçük (≤8) · synthetic | 286 | 38.5% | 74.5% | **83.9%** |

## Strateji önerisi

### 🚀 STRONG SUBSET'lere ÖZEL TIER (top-pick subset filter):
- Diğer · küçük (≤8) · turf (+8.1pp), Diğer · küçük (≤8) · dirt (+8.0pp), Diğer · küçük (≤8) · synthetic (+6.2pp)

Bu segment'lerde modelin top1'i top4'e girme yüzdesi global'den **+%2-5pp** yüksek.
Pick yapılırken bu segment'lere ÖZEL bütçe ayrılabilir (booster).

### ⚠ KAÇINILACAK SUBSET'ler:
- Diğer · devasa (15+) · dirt: top4=64.9% (global'den −%12.8pp)
- Diğer · devasa (15+) · synthetic: top4=60.0% (global'den −%17.7pp)
- Diğer · devasa (15+) · turf: top4=59.8% (global'den −%17.9pp)
