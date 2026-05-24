# Phase 5.2 — Calibration Analysis

## DURUM: ⏸ FIT YAPILAMADI — tarihsel outcome (won_flag) yok

Kalibrasyon = f(prob, **outcome**). Dataset 8073 satır AGF var ama **won_flag dolu: 0**
(sonuç kaynağı bloke, PART A). Fit için minimum n≥50 etiketli çift gerekir → 0 → İMKANSIZ.

## Section 2 (calibration_dataset üzerinde)
- Reliability/Brier/log-loss: **INSUFFICIENT_DATA** (label yok). 04_bet_diary_report
  Section 2 zaten bu durumu graceful handle ediyor (Phase 5.1.5).

## Fit mekanizması: HAZIR + doğrulandı (gerçek veri bekliyor)
- `simulation/calibrators/{isotonic,platt}.py` — fit/predict çalışıyor (Phase 5.1.5 smoke:
  isotonic 0.5, platt 0.492 synthetic). Mekanizma sağlam; eksik olan SADECE etiketli veri.
- isotonic vs platt karşılaştırma, before/after Brier, active.pkl: **N/A** (label yok).

## active.pkl: ÜRETİLMEDİ
Etiketli veri olmadan kalibratör fit edilip prod'a verilemez (yanlış kalibratör riski).
`simulation/calibrators/fitted/` boş; PART E shadow no-op modunda kalır (active.pkl yok → None).

## Forward fit protokolü (outcome gelince — tek seferde)
1. Outcome kaynağı: bet_diary (migration apply + ~50-60 gün, prod model_prob + retro outcome)
   VEYA TJK JS-render çözümü (Playwright — Berkay kararı) → tarihsel won.
2. won_flag doldur: `horse_matcher.match_by_at_no` (at_no join — hazır).
3. Section 2: calibration_gap + Brier (raw).
4. `IsotonicCalibrator`/`PlattCalibrator` fit (train 60g, val 30g hold-out).
5. Validation Brier düşük olan → `fitted/active.pkl`. before/after raporu.

## Dürüst özet
Bu turun kalibrasyon FIT'i **outcome engeline takıldı** (tarihsel sonuç 3 kaynakta bloke).
Sahte kalibratör üretilmedi. AGF backfill + cross-check (pearson 0.9996) + fit mekanizması +
forward protokol HAZIR — outcome gelince fit tek adım. **H1 (model kalibrasyonu) hâlâ açık**,
forward'a bağlı.
