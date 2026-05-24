# Phase 5.1.5 — Calibration Measurement Infrastructure

Veriyi BEKLEMEYEN altyapı: bugün yazıldı, bet_diary'ye veri akınca otomatik çalışır.

## Ne eklendi
| Dosya | İçerik |
|---|---|
| `audit/04_bet_diary_report.py` `_sec_calibration` | Section 2 güçlendirildi: reliability tablosu (expected vs actual + gap + over/under-conf), **Brier score**, **log-loss** (n≥50). n<50 → INSUFFICIENT_DATA (graceful). |
| `simulation/calibrators/isotonic.py` | IsotonicCalibrator (sklearn, non-parametrik, fit/predict) |
| `simulation/calibrators/platt.py` | PlattCalibrator (sklearn LogisticRegression, fit/predict) |
| `audit/smoke_daily_calibration.py` | günlük çağrılabilir: bet_diary 30g → Section 2 + calibrator self-test |

## Ne zaman fire edecek
- **Section 2 (Brier/log-loss)**: bet_diary'de n≥50 sonuçlanmış (model_prob + did_we_win)
  kayıt birikince. Şu an 0 → INSUFFICIENT_DATA (smoke doğruladı, hata atmadı).
- **Calibrators**: Phase 5.2'de gerçek (raw_prob, outcome) çiftleriyle fit. Şu an synthetic
  self-test geçiyor (isotonic 0.5, platt 0.492 — sklearn yüklü, çalışıyor).

## Phase 5.2 akışı (hazır)
1. bet_diary n≥200 (forward VEYA agftahmin backfill — PART A FAST POSSIBLE).
2. `smoke_daily_calibration` → Section 2: calibration_gap büyükse model overconfident.
3. IsotonicCalibrator/PlattCalibrator fit (raw_model_prob, outcome).
4. Brier/log-loss before/after kıyas → kazanan kalibratör.
5. calibrated_prob'u V7/kupon.py/smart_genis'e shadow-first enjekte (coverage/width
   artık kalibre olasılıkla — H1 çözülür).

## Bağımlılık
- Henüz hiçbir prod yoluna bağlı DEĞİL (sadece kütüphane + ölçüm). Prod davranışı değişmedi.
- Gate: bet_diary verisi (migration apply). FAST track (PART A) ile backfill hızlandırabilir.
