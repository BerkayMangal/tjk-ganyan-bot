# Phase 5.3 PART D — FLB Signal Validation (n=8073 at-satırı)

Phase 5.2.5'in "orta-favori OVERBET" ön bulgusu → ince bucket'larla NET ölçüm. Phase 5.5
(FLB compensation) için doğrudan girdi.

## D.1 — AGF bucket × gerçek win-rate
| AGF% bucket | n | won | **actual%** | avgAGF% | gap (pp) | **corr× (act/agf)** |
|---|---|---|---|---|---|---|
| 0–5 | 4006 | 154 | 3.84% | 1.91% | +1.93 | **2.01** |
| 5–10 | 1530 | 102 | 6.67% | 7.18% | −0.52 | 0.93 |
| 10–15 | 944 | 125 | 13.24% | 12.37% | +0.87 | 1.07 |
| 15–20 | 570 | 102 | 17.89% | 17.23% | +0.67 | 1.04 |
| 20–25 | 364 | 68 | 18.68% | 22.43% | −3.74 | 0.83 |
| 25–30 | 219 | 60 | 27.40% | 27.22% | +0.17 | 1.01 |
| 30–40 | 228 | 54 | 23.68% | 34.33% | −10.65 | 0.69 |
| 40–50 | 108 | 35 | 32.41% | 44.37% | −11.96 | 0.73 |
| 50–100 | 104 | 32 | 30.77% | 60.66% | **−29.90** | **0.51** |

## D.2 — Reliability diagram (ASCII; `#`=actual win%, `E`=AGF-implied/fair)
```
  0-5  a= 3.8% #E#                                          (longshot UNDERBET, act>impl)
 5-10  a= 6.7% ######E
10-15  a=13.2% ############E
15-20  a=17.9% #################E
20-25  a=18.7% ##################    E                      (overbet başlıyor)
25-30  a=27.4% ###########################E
30-40  a=23.7% #######################          E           (favori OVERBET)
40-50  a=32.4% ################################           E
50-100 a=30.8% ##############################                          E  (E≈60.7%, ağır overbet)
```

## Bulgu: 🟢 FLB DOĞRULANDI (klasik FLB'nin "favori-overbet" formu)
- **Deep longshot (0–5% AGF) UNDERBET**: actual %3.84 vs implied %1.91 → **corr ×2.01**
  (priced'ın 2x'i kazanıyor). Halk favorilere yığılıyor → longshot artığı ucuz kalıyor.
- **Orta (10–20%) ≈ fair** (corr 1.04–1.07).
- **Favori (≥30%) AĞIR OVERBET**: 30-40 corr 0.69, 40-50 corr 0.73, **50%+ corr 0.51**
  (piyasa %61 diyor, gerçek %31 — yarı yarıya). Favori ne kadar ağırsa o kadar overbet.
- **Value yönü**: longshot/orta-alt'ta value VAR (model favoriye değil, underbet'e bakmalı);
  ağır favoride NEGATIF value (favori körü körüne oynanmaz).

## D.3 — Phase 5.5 düzeltme faktörü tablosu (çarpımsal: true ≈ corr × agf_implied)
| AGF% | corr× | Phase 5.5 aksiyon |
|---|---|---|
| 0–5 | 2.01 | longshot value BONUS (dikkatli — n büyük ama base düşük, gürültü) |
| 5–10 | 0.93 | ~nötr |
| 10–25 | 0.83–1.07 | ~nötr/hafif |
| 30–40 | 0.69 | favori CEZA −%31 |
| 40–50 | 0.73 | favori CEZA −%27 |
| 50+ | 0.51 | favori AĞIR CEZA −%49 (n=104, az → regularize et) |

**Phase 5.5 tavsiyesi**:
- **Birincil**: `agf_outcome_calibrator.pkl` (isotonic, sürekli, smoothed) — bu bucket tablosunun
  düzgünleştirilmiş hâli. value_score = calibrated(agf_implied) − agf_implied (FLB-value).
- Bucket tablosu = sanity cross-check + yorumlanabilir görünüm.
- ⚠ **CAVEAT**: yüksek bucket'larda n küçük (50%+ n=104). Çarpımsal faktörü ham kullanma →
  isotonic (regularized) tercih et. 0-5% bonus dikkatli (base-rate düşük, gürültülü).
- ⚠ Bu **AGF→outcome** (piyasa) sinyali; model_prob'a karışmaz (Phase 5.2.5 disiplini).

## Karar bağlantısı (PART E)
FLB sinyali GERÇEK ve güçlü → Phase 5.5'in değeri yüksek. Bu, "model + FLB-düzeltme" (Benter
5.4 + FLB 5.5) yönünü destekler; saf-favori stratejilerin (ör. tek-favori %0) neden öldüğünü
de açıklar (favori overbet).
