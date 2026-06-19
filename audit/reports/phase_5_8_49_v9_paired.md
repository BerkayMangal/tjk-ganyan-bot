# Phase 5.8.49 — V9 (V7 + sf2__ GEÇMİŞ sec_prev) Paired vs V7-ndcg@4

_Run: 2026-06-19_

## Sonuç

V9 = V7 (225) + 22 sf2__ feature (sec_prev1..5 sectional history).

Cutoff = 2025-05-24, ndcg@4 loss.

| Breed | Metric | V7-ndcg@4 | V9 | Δ |
|---|---|---|---|---|
| ARAB | top1 | 30.09% | 30.63% | +0.53pp |
| ARAB | top3 | 63.46% | 63.36% | -0.10pp |
| ARAB | top4 | 74.06% | 73.59% | **-0.47pp** ⚠ |
| ENGL | top1 | 30.88% | 31.22% | +0.33pp |
| ENGL | top3 | 64.46% | 64.33% | -0.14pp |
| ENGL | top4 | 75.81% | 75.72% | -0.08pp |

## Karar

**V9 KAYBETTİ — V7-ndcg@4 ortak best kalır.**

Net Δ:
- top1 +0.43pp (marjinal +)
- top3 -0.12pp
- **top4 -0.28pp** (ANA HEDEF negatif)

## Açıklama

sec_prev* GEÇMİŞ yarış sectional aggregate'leri V7'nin cf__ (career history)
feature'larıyla **redundant**. cf__ zaten son-N-yarış top4 rate ve recent
performance trend yakalıyor; sec_prev* ek bilgi katmadı, hatta noise ekledi.

Doluluk: 70,112/245,139 (%28.6) → %71.4 satırda sf2__ = 0.0 fillna →
model bu bilgisiz örnekler için belirsizlik öğreniyor, top4 sıralamayı
bozuyor.

İlk denemede sec_* (prefix'siz) kullanılmıştı: top1 %30→%64 leakage
gözlemlendi (post-race outcome). Düzeltme yapıldı (sec_prev* GEÇMİŞ-only).
Ama yine de yararlanamadık.

## İleride deneme adayları

- horse_sectional_features (76K × 259 col) — at-bazlı uzun pencere sectional
  aggregate (career history derinleştirme)
- accurace_splits → at-bazlı pace style sınıflandırma (sprinter/closer/leader)
  → kategorik feature
- horse_training_stats time-1400m/1200m × form trend (V8 sf__ idman boyutu)

