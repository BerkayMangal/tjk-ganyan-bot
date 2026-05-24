# Phase 5.2 — Model Replay Report

## KARAR: FALLBACK (raw_prob = agf_implied_prob)

PRIMARY (full replay) ve SUBSET imkansız → FALLBACK seçildi. Gerekçe ikili:

### 1. Feature availability <%50 (backfill AGF-only)
agftahmin tablosu SADECE `at_no + agf_pct` veriyor (isim/kilo/jokey bile yok).
| Kategori (96-D) | Backfill'de |
|---|---|
| agf (8) | ✅ agftahmin |
| race_level (19) | ⚠ kısmi (time/hippo; distance/weather yok) |
| physical (8) | ❌ kilo/age/gender yok |
| form (8) / jockey (5) / pedigree (8) / pace (3) / other (11) / interactions (26) | ❌ yok |
- Erişilebilir: ~12/96 ≈ **%12.5**. Plan eşiği: <%50 → FALLBACK.

### 2. Out-of-distribution + outcome yok
- Mevcut model'i form/jokey/pace=0 ile çalıştırmak teknik olarak mümkün ama **eğitim
  dağılımından farklı girdi** → model_prob güvenilmez (OOD), kalibre etmek anlamı sınırlı.
- **Tarihsel outcome (won) ZATEN YOK** (PART A) → hangi raw_prob üretirsek üretelim
  kalibrasyon FIT edilemez. Bu, path seçimini akademik kılıyor.

## Uygulanan
- `simulation/model_replay.py`: `compute_raw_prob(agf_pct) = agf_pct/100` (FALLBACK).
- raw_prob = `agf_implied_prob` (dataset'te zaten kolon, PART B).

## Sanity check
- agf düşük at → raw_prob düşük (raw_prob = agf/100, monoton ✓).
- Yarış toplamı: ayak AGF% toplamı ~100 (cross-check kanıtlı) → implied toplam ~1.0 ✓.

## Bilinen sınırlamalar
- **Bu "model kalibrasyonu" DEĞİL, AGF/piyasa kalibrasyonu** (FLB curve temeli, Phase 5.5).
- Gerçek model_prob kalibrasyonu **forward** gerektirir: bet_diary'de prod model_prob +
  outcome (migration apply + ~50-60 gün). O zaman PRIMARY path mümkün.
- agf_implied yine değerli: Phase 5.4 Benter w2 ağırlığı + Phase 5.5 FLB için girdi.
