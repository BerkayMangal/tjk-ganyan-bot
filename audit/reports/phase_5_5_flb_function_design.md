# Phase 5.5 PART B — FLB Compensator Function Tasarımı

## Formül (magic number YOK)
```
multiplier(agf) = clamp( winrate_calib(agf) / agf , corr_min , corr_max )
compensate(raw_value, agf) = raw_value × multiplier(agf)
```
- `winrate_calib` = CV-seçilmiş kalibratör (agf_implied → gerçek win prob).
- `clamp` = gözlenen bucket-corr extremleri (veri-türevli) → isotonic-floor'un micro-AGF'de
  multiplier'ı patlatmasını önler.

## B.2 — Smoothing seçimi (5-fold CV Brier, n=8073)
| yöntem | CV Brier |
|---|---|
| raw_bucket | 0.07731 |
| **isotonic** ✅ | **0.07709** |
| platt | 0.07837 |
→ **isotonic** seçildi (en düşük CV Brier). Phase 5.2.5 bulgusuyla tutarlı (isotonic > platt).
clamp = **[0.507, 2.01]** (50%+ bucket corr ile 0-5% bucket corr — veri-türevli).

## B.3 — Function (simulation/calibrators/flb_compensator.py)
- `FLBCompensator.fit(agf_pcts, won_flags)`: CV ile isotonic/platt/raw_bucket karşılaştırır,
  en iyiyi saklar + clamp'i bucket-corr extremlerinden türetir.
- `.multiplier(agf_pct)` / `.compensate(raw, agf_pct)`.
- Fitted pickle: `simulation/calibrators/fitted/flb_compensator.pkl`.

## B.4 — Sanity validation (✅ hepsi beklenen yönde)
| AGF% | multiplier | beklenen | sonuç |
|---|---|---|---|
| 2 | 1.705 | >1.5 bonus | ✅ longshot bonus |
| 8 | 1.010 | ~1 | ✅ nötr |
| 15 | 1.176 | ~1 | ✅ ~nötr |
| 40 | 0.633 | <0.8 ceza | ✅ favori ceza |
| 60 | 0.507 | <0.7 ceza | ✅ ağır favori ceza (clamp tabanı) |

## B.5 — Monotonicity
- **Spearman(agf, multiplier) = −0.861** → güçlü negatif: agf↑ → multiplier↓ (longshot bonus,
  favori ceza yönü DOĞRU).
- Lokal artış-ihlali 13/68 (isotonic-step gürültüsü, ör. 8%→12% 1.01→1.03). Genel trend net;
  monotonik-zorlama YAPMADIM (veri lokal gürültülü, zorlamak sinyali bozardı — dürüst tercih).

## Multiplier eğrisi (ASCII)
```
  1% 2.01 ######################################## (longshot AĞIR bonus)
  3% 1.86 #####################################
  5% 1.11 ######################
  8% 1.01 ####################  (nötr bölge)
 12% 1.03 ####################
 18% 0.98 ###################
 25% 0.78 ###############
 35% 0.72 ##############       (favori ceza başlıyor)
 45% 0.68 #############
 60% 0.51 ##########           (ağır favori, clamp tabanı 0.507)
```

## Bilimsel temel
multiplier = corrected_winrate/market → piyasa-bias düzeltmesi. TR'de favori-overbet
(Phase 5.3 D) → favori multiplier <1 (ceza), longshot >1 (bonus). Klasik FLB'nin (longshot
overbet) TERSİ; Busche-Hall (1988) Asya "reverse FLB" ile uyumlu. Detay PART E.

COMMIT sonrası: PART C (shadow integration).
