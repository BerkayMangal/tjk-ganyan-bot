# Phase 5.8.56 — Value Edge (mp − agf) Sweet Spot
_Run: 2026-06-20T05:40:43.445492Z_

## Setup

- Test set: races_v7.csv ≥ 2025-05-24 (64,372 at)
- Model: V7-ndcg@4, mp = softmax(ranker_score) per race
- gap = mp - agf (mp 0-1, agf 0-1)

## Value edge bantları

| Bant | n | avg mp | avg agf | top1% | top3% | **top4%** |
|---|---|---|---|---|---|---|
| A. gap<-30pp (model çok altında halk) | 1,382 | 15.4% | 55.6% | 48.2% | 81.7% | **88.7%** |
| B. -30 to -10pp | 5,880 | 12.6% | 29.3% | 29.8% | 64.4% | **74.7%** |
| C. -10 to 0pp (model nötr-altı) | 14,002 | 10.7% | 14.9% | 14.7% | 43.2% | **55.4%** |
| D. 0 to +5pp (mild value) | 16,824 | 9.0% | 6.0% | 6.3% | 23.6% | **33.2%** |
| E. +5 to +10pp | 21,223 | 9.4% | 2.5% | 3.6% | 16.4% | **24.8%** |
| F. +10 to +15pp (FIRSAT-zone) | 3,908 | 13.7% | 1.9% | 6.0% | 27.2% | **43.1%** |
| G. +15 to +20pp | 766 | 17.8% | 0.9% | 10.1% | 37.6% | **59.5%** |
| H. +20 to +30pp (sweet?) | 284 | 23.2% | 0.2% | 17.3% | 49.3% | **64.8%** |
| I. +30 to +50pp | 75 | 37.1% | 0.1% | 20.0% | 52.0% | **56.0%** |

## Sweet spot tespiti

En yüksek top4 hit:
- **A. gap<-30pp (model çok altında halk)**: top4 %88.7, n=1,382, avg mp %15.4, avg agf %55.6
- **B. -30 to -10pp**: top4 %74.7, n=5,880, avg mp %12.6, avg agf %29.3
- **H. +20 to +30pp (sweet?)**: top4 %64.8, n=284, avg mp %23.2, avg agf %0.2
- **G. +15 to +20pp**: top4 %59.5, n=766, avg mp %17.8, avg agf %0.9
- **I. +30 to +50pp**: top4 %56.0, n=75, avg mp %37.1, avg agf %0.1

## MP × AGF 2D Matrix (top4 hit%, hücre boş ise n<20)

| MP \ AGF | agf 0.00-0.05 | agf 0.05-0.10 | agf 0.10-0.20 | agf 0.20-0.30 | agf 0.30-0.50 | agf 0.50-1.00 |
|---|---|---|---|---|---|---|
| **mp 0.05-0.10** | 17% (n=20895) | 34% (n=6371) | 47% (n=5436) | 63% (n=1115) | 72% (n=351) | 91% (n=33) |
| **mp 0.10-0.15** | 34% (n=7172) | 48% (n=4472) | 62% (n=6194) | 73% (n=2492) | 79% (n=1340) | 89% (n=303) |
| **mp 0.15-0.20** | 55% (n=1241) | 72% (n=847) | 78% (n=1479) | 82% (n=1064) | 89% (n=874) | 93% (n=350) |
| **mp 0.20-0.30** | 70% (n=335) | 91% (n=76) | 95% (n=233) | 93% (n=226) | 95% (n=342) | 97% (n=253) |
| **mp 0.30-0.40** | 65% (n=52) | — | — | — | — | — |
| **mp 0.40-0.60** | 48% (n=40) | — | — | — | — | — |

## Strateji önerisi

1. **FIRSAT eşiği güçlü ise** (sweet spot bant), audit/73 mevcut `mp [0.18, 0.32) + gap ≥ 0.10` eşiği zaten bu bandı yakalıyor.
2. **MP yüksek + AGF düşük** = klasik value pick (halk underbet). Heatmap'te bu hücre netleşir → pick'lerin tier'a göre filter.
3. **MP düşük + AGF yüksek** = halk overbet, model haklı → FADE THE FAVORITE.
