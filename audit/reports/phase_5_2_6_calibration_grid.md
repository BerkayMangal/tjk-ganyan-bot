# Phase 5.2.6 — Calibration Grid Raporu

Fit zamanı: 2026-06-13T06:23:22.325541Z

## Durum özeti

- AGF kalibrasyon dataset: **n=8073** (30 gün, 2026-04-23 → 2026-05-22)
- Pozitif (winner): 732 / 8073 (9.07%)
- Walk-forward folds: **5**, per-fold test n≈1331
- Distance coverage: 93.8%

**ÖNEMLİ VERİ KISITLARI** (sahte sonuç üretmemek için açık not):

1. **Model_prob kalibrasyonu yapılamadı**: bet_diary'de did_we_win=None (outcome henüz yazılmamış). bet_diary tarihleri (Jun 04/08/09/10/12) ile outcomes dosyaları (Apr 23 → Jun 07) sadece 2026-06-04'te örtüşüyor → join sonucu **n=18** (1 altılı). Bu rapor ASIL olarak **AGF→outcome** (piyasa/FLB kalibrasyonu) için geçerli sonuçlar üretti. Model kalibrasyonu için forward bekliyor (retro tamamlanınca + bet_diary outcome update).
2. **Per-breed yapılamadı**: calibration_dataset_complete.csv'de breed kolonu yok; sire'dan otomatik breed çıkarma güvenilmez. Bunun yerine PER-HIPPODROME bucket'ı kullanıldı (Şanlıurfa/Elazığ/Diyarbakır Arap-ağırlıklı proxy; kesin değil).
3. **Per-target (top1..5) yapılamadı**: AGF dataset at-level (race-internal rank değil). bet_diary'de model_rank var ama outcome eşleşmesi yetersiz.

## Walk-forward split tanımı

Zaman-sıralı expanding window. Fold 5 adet. Train her zaman test'ten önce (future leakage YOK).

- Fold 1: train n=1416 (2026-04-23 → 2026-04-27), test n=1374 (2026-04-28 → 2026-05-02)
- Fold 2: train n=2790 (2026-04-23 → 2026-05-02), test n=1274 (2026-05-03 → 2026-05-07)
- Fold 3: train n=4064 (2026-04-23 → 2026-05-07), test n=1339 (2026-05-08 → 2026-05-12)
- Fold 4: train n=5403 (2026-04-23 → 2026-05-12), test n=1392 (2026-05-13 → 2026-05-17)
- Fold 5: train n=6795 (2026-04-23 → 2026-05-17), test n=1278 (2026-05-18 → 2026-05-22)

## Drift kontrol (oldest fold vs newest fold)

- En eski fold test: n=1374, mean AGF prob=0.0917, win rate=0.0917
- En yeni fold test: n=1278, mean AGF prob=0.0892, win rate=0.0892
- Drift: prob Δ=-0.0025, winrate Δ=-0.0025

## GLOBAL bucket — calibrator sıralaması

Combined score = Brier + 0.5×ECE (lower=better). Bootstrap CI 95% (n=1000 resample).

| Calibrator | Brier | Brier CI95 | ECE | ECE CI95 | LogLoss | MCE | Combined | n_test_avg |
|---|---|---|---|---|---|---|---|---|
| beta | 0.07809 | [0.06671, 0.08984] | 0.01152 | [0.00745, 0.02923] | 0.27916 | 0.35391 | 0.08385 | 1331 |
| histogram_20 | 0.07935 | [0.06787, 0.09135] | 0.01401 | [0.00843, 0.03161] | 0.31611 | 0.75000 | 0.08635 | 1331 |
| histogram_10 | 0.07882 | [0.06749, 0.09075] | 0.01525 | [0.00821, 0.03209] | 0.30402 | 0.53251 | 0.08645 | 1331 |
| isotonic | 0.07828 | [0.06692, 0.09006] | 0.01652 | [0.00839, 0.03278] | 0.29803 | 0.42734 | 0.08655 | 1331 |
| stacking | 0.07905 | [0.06722, 0.09127] | 0.02111 | [0.01153, 0.03717] | 0.28364 | 0.60837 | 0.08960 | 1331 |
| temperature | 0.07966 | [0.06883, 0.09094] | 0.02153 | [0.01509, 0.03833] | 0.28428 | 0.50940 | 0.09042 | 1331 |
| raw | 0.07949 | [0.06825, 0.09122] | 0.02321 | [0.01519, 0.04031] | 0.28647 | 0.52139 | 0.09110 | 1331 |
| histogram_50 | 0.08067 | [0.06897, 0.09275] | 0.02118 | [0.01163, 0.03727] | 0.36015 | 0.67933 | 0.09126 | 1331 |
| platt | 0.07939 | [0.06753, 0.09174] | 0.02439 | [0.01457, 0.04078] | 0.28484 | 0.51066 | 0.09159 | 1331 |
| spline_7 | 0.08199 | [0.07020, 0.09452] | 0.02254 | [0.01415, 0.03943] | 0.41961 | 0.23919 | 0.09326 | 1331 |

## En iyi 3 GLOBAL aday (kaydedildi)

### 1. beta (file: cand_01_beta_global.pkl)

- Brier: 0.07809
- ECE: 0.01152
- LogLoss: 0.27916
- MCE: 0.35391
- Combined: 0.08385
- n_train_total: 8073

**Neden seçildi**: Beta calibration (Kull 2017). Asymmetric miscalibration için isotonic'ten daha esnek.

### 2. histogram_20 (file: cand_02_histogram_20_global.pkl)

- Brier: 0.07935
- ECE: 0.01401
- LogLoss: 0.31611
- MCE: 0.75000
- Combined: 0.08635
- n_train_total: 8073

**Neden seçildi**: equal-width binning. Lokal düzeltme.

### 3. histogram_10 (file: cand_03_histogram_10_global.pkl)

- Brier: 0.07882
- ECE: 0.01525
- LogLoss: 0.30402
- MCE: 0.53251
- Combined: 0.08645
- n_train_total: 8073

**Neden seçildi**: equal-width binning. Lokal düzeltme.

## Mevcut agf_outcome_calibrator.pkl baseline (last fold test üzerinde)

- Method: isotonic
- Orijinal n_train: 5651
- Brier (last fold): 0.07854
- ECE (last fold): 0.01513
- LogLoss (last fold): 0.28744
- MCE (last fold): 0.41367
- n_test_last_fold: 1278

Karşılaştırma: top GLOBAL 'beta' Brier 0.07809, ECE 0.01152. 
→ Yeni adaylar mevcuttan parite veya daha iyi. **Berkay karar verir** (active.pkl yazılmadı).

## PER-HIPPODROME bucket sonuçları

Her hipodrom için EN İYİ calibrator + GLOBAL raw karşılaştırma:

| Hipodrom | Best calibrator | Brier | ECE | LogLoss | n_test | GLOBAL_raw_brier (kıyas) |
|---|---|---|---|---|---|---|
| Adana | beta | 0.07939 | 0.00645 | 0.29767 | 135 | 0.07949 |
| Ankara | beta | 0.07937 | 0.02775 | 0.28650 | 244 | 0.07949 |
| Bursa | beta | 0.07015 | 0.02823 | 0.25771 | 205 | 0.07949 |
| Diyarbakır | platt | 0.07311 | 0.02297 | 0.27675 | 75 | 0.07949 |
| Elazığ | histogram_10 | 0.08395 | 0.03377 | 0.50466 | 102 | 0.07949 |
| Kocaeli | isotonic | 0.08307 | 0.02689 | 0.28412 | 121 | 0.07949 |
| İstanbul | beta | 0.08020 | 0.03130 | 0.28632 | 287 | 0.07949 |
| İzmir | spline_7 | 0.08068 | 0.03752 | 0.57440 | 182 | 0.07949 |
| Şanlıurfa | platt | 0.08140 | 0.02410 | 0.30000 | 135 | 0.07949 |

**Sahte-bucket koruması**: n_test < 30 olan hipodrom-fold'ları INSUFFICIENT diye işaretlendi (aşağıdaki tabloya bak).

## PER-DISTANCE bucket sonuçları

| Mesafe bandı | Best calibrator | Brier | ECE | LogLoss | n_test |
|---|---|---|---|---|---|
| long_>=1800 | beta | 0.08050 | 0.02032 | 0.28881 | 445 |
| mid_1500-1700 | temperature | 0.07162 | 0.02789 | 0.25853 | 213 |
| sprint_<=1400 | isotonic | 0.07892 | 0.01388 | 0.29091 | 592 |

## PER-AGF-BAND sonuçları (favori kategorisine göre kalibrasyon)

| AGF Band | Raw_brier | Raw_ece | Best_method | Best_brier | Best_ece | n_test |
|---|---|---|---|---|---|---|
| high_30-50% | 0.20915 | 0.09825 | platt | 0.20418 | 0.07050 | 57 |
| low_5-15% | 0.08350 | 0.02346 | platt | 0.08490 | 0.01611 | 410 |
| mid_15-30% | 0.15502 | 0.02943 | raw | 0.15502 | 0.02943 | 192 |
| veryLow_<5% | 0.03775 | 0.01951 | platt | 0.03752 | 0.00851 | 653 |

- AGF band `high_30-50%` raw brier: 0.20915 → FLB (favori overbet) Phase 5.5'te kanıtlanmıştı; bu bant'ta calibrator gerekiyor.

## INSUFFICIENT / DEGENERATE bucket'lar

| Bucket type | Bucket | Status | Hücre sayısı |
|---|---|---|---|
| PER_AGF_BAND | veryHigh_>=50% | INSUFFICIENT | 20 |
| PER_HIPPODROME | Adana | INSUFFICIENT | 20 |
| PER_HIPPODROME | Diyarbakır | INSUFFICIENT | 30 |
| PER_HIPPODROME | Elazığ | INSUFFICIENT | 20 |
| PER_HIPPODROME | Kocaeli | INSUFFICIENT | 20 |
| PER_HIPPODROME | Şanlıurfa | INSUFFICIENT | 20 |

**Toplam insufficient hücre: 130** (n<50 train veya n<30 test; sahte fit ÜRETİLMEDİ).

## Yol B — bet_diary mini-analiz (model_prob)

bet_diary outcomes join: **n=18** satır (threshold n≥50, fit yapılmadı).
- Tarihler: ['2026-06-04']
- Hipodromlar: ['Kocaeli Hipodromu']
- Win rate: 0.1667

Raw skorlar (sadece bilgi, calibrator FIT EDİLMEDİ):
- Model raw Brier: 0.13668
- Model raw ECE: 0.16861
- Model raw LogLoss: 0.42724
- AGF raw Brier: 0.14241
- AGF raw ECE: 0.21277
- AGF raw LogLoss: 0.45521
- Model raw Brier (0.1367) < AGF raw Brier (0.1424) → n=18'de model marjinal iyi görünüyor; **ölçüm güvenilir DEĞİL** (n<50, geniş CI). Forward 200+ outcome bekleyin.

⚠ **n=18 → istatistiksel güç çok düşük.** Kalibratör fit edilmedi; active.pkl yazılmadı.

## Reliability diagram noktaları (last fold, isotonic vs raw)

| Bin | Raw_conf | Raw_acc | Raw_n | Cal_conf | Cal_acc | Cal_n |
|---|---|---|---|---|---|---|
| 1 | 0.0335 | 0.0523 | 879 | 0.0445 | 0.0525 | 877 |
| 2 | 0.1406 | 0.1453 | 234 | 0.1520 | 0.1642 | 274 |
| 3 | 0.2431 | 0.2062 | 97 | 0.2428 | 0.1667 | 102 |
| 4 | 0.3463 | 0.2051 | 39 | 0.3143 | 0.2381 | 21 |
| 5 | 0.4435 | 0.1579 | 19 | 0.4500 | - | 0 |
| 6 | 0.5326 | 0.4000 | 5 | 0.5500 | - | 0 |
| 7 | 0.6551 | 0.3333 | 3 | 0.6500 | - | 0 |
| 8 | 0.7422 | 0.0000 | 2 | 0.7457 | 0.2500 | 4 |
| 9 | 0.8500 | - | 0 | 0.8500 | - | 0 |
| 10 | 0.9500 | - | 0 | 0.9500 | - | 0 |

PNG: `audit/reports/figures/phase_5_2_6_reliability_isotonic.png`

## En iyi 3 aday seçim mantığı

`combined_score = brier + 0.5 * ece` (Brier ağırlıklı, ECE ikincil). Walk-forward'da TÜM fold'lar ortalamalandı. Her aday TÜM dataset üzerinde yeniden fit edilip `candidates/cand_NN_method_GLOBAL.pkl` olarak kaydedildi.

## Karar tavsiyesi (Berkay'a)

Bu rapor ölçüm odaklı; **aktif kararını Berkay verir**. Olası yollar:

1. **Mevcut agf_outcome_calibrator değişiklik gerekmiyor**: top GLOBAL aday Brier mevcut <= mevcut → status quo.
2. **Yeni aday daha iyi**: `cand_01_*.pkl`'i `simulation/calibrators/fitted/agf_outcome_calibrator.pkl` olarak kopyala (önce backup al).
3. **Model kalibrasyonu için forward**: bet_diary'de outcome update + n≥200 birikince Yol B yeniden koş. Şimdilik `model_prob_calibrated=None` kalır.

**+EV/edge iddiası BU RAPORDA YOKTUR.** Sadece Brier/ECE/LL/MCE.
