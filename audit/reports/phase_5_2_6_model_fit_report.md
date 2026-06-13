# Phase 5.2.6 — Model_prob kalibrasyonu (forward fit)
_Tarih: 2026-06-13T17:42:42.621281Z_  ·  _Veri: bet_diary forward_

**Dataset:** n=794 (model_prob+did_we_win), base-rate=0.0793, tarih=2026-06-04 → 2026-06-12
**Yöntem:** walk-forward 3-fold (expanding window), Brier+ECE combined skor
**Seçilen kalibratör:** **beta** (Brier+ECE=0.08191)

## Walk-forward ortalamalar

| Method | Brier | ECE | LogLoss | MCE |
|---|---|---|---|---|
| platt | 0.07539 | 0.00757 | 0.28249 | 0.01442 |
| beta | 0.07540 | 0.00651 | 0.28178 | 0.00651 |
| isotonic | 0.07601 | 0.01370 | 0.36988 | 0.01963 |
| raw | 0.16364 | 0.23322 | 0.51147 | 0.85872 |

## Aktivasyon
- `/Users/berkay/projects/tjk-ganyan-bot/simulation/calibrators/fitted/active.pkl` yazıldı → calibration_loader.apply_calibration() artık no-op değil
- yerli_engine her tahmin için `calibrated_prob` üretir (legs_summary.all_horses_with_mp)
- UX davranışı değişmez (kupon `model_prob` ham değerden gider); shadow meta + audit için kayıt

## Sınırlamalar (dürüst)
- n=794 marjinal (büyük güven aralıkları); 1-2 hafta sonra yeniden koş
- Walk-forward fold sayısı 3 (n<200 olsaydı yetersiz; çift veri birikince 5'e çık)
- model_prob race-içi softmax-normalize (yarış başına toplam 1), bu binary calibrator hâlâ basit kuralı
  uygulanabilir kabul ediliyor (Phase 5.5 forward görev: per-target/per-breed buckets).

## Rollback
```bash
rm /Users/berkay/projects/tjk-ganyan-bot/simulation/calibrators/fitted/active.pkl   # apply_calibration tekrar no-op olur
```
