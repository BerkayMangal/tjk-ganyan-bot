# SABAH V2 RAPORU — Model Süiti + SİB Stale-Line Araştırması

**Tarih:** 2026-06-03 sabah
**Hedef:** (A) bet-type'a özel kalibre model SÜİTİ + (B) SİB stale-line tezi araştırması (kapsamlı, dürüst)

---

## (A) MODEL SÜİTİ — 5 binary target × 2 breed × XGB+LGBM+isotonic

**Eğitim:** train 2021-2023, val 2024 (isotonic), HOLDOUT 2025+ (87,573 at).
**Artifacts:** `model/trained_targets/{top1..top5}/{xgb,lgbm,isotonic}_{arab,english}.pkl`

### HOLDOUT karşılaştırma — Model vs AGF baseline (AUC)

| Target | Breed | N | AUC_Model | AUC_AGF | ΔAUC | Brier | ECE | Verdict |
|---|---|---|---|---|---|---|---|---|
| top1 | arab | 42,000 | 0.6762 | **0.7125** | −0.0363 | 0.0851 | 0.0117 | ✗ AGF kazanır |
| top1 | english | 45,573 | 0.6993 | **0.7253** | −0.0260 | 0.0920 | 0.0067 | ✗ AGF kazanır |
| top2 | arab | 42,000 | 0.6859 | **0.7074** | −0.0215 | 0.1467 | 0.0222 | ✗ AGF kazanır |
| top2 | english | 45,573 | 0.7077 | **0.7177** | −0.0101 | 0.1542 | 0.0170 | ✗ AGF kazanır |
| top3 | arab | 42,000 | 0.6932 | **0.7034** | −0.0101 | 0.1880 | 0.0323 | ✗ AGF marjinal |
| top3 | english | 45,573 | 0.7135 | 0.7158 | −0.0023 | 0.1925 | 0.0226 | ✗ neredeyse eşit |
| **top4** | **arab** | 42,000 | **0.7026** | 0.7022 | **+0.0004** | 0.2116 | 0.0486 | ✓ **marjinal** |
| **top4** | **english** | 45,573 | **0.7331** | 0.7196 | **+0.0134** | 0.2058 | 0.0235 | ✓ **MODEL ÜSTÜN** |
| **top5** | **arab** | 42,000 | **0.7234** | 0.7069 | **+0.0164** | 0.2126 | 0.0356 | ✓ **MODEL ÜSTÜN** |
| **top5** | **english** | 45,573 | **0.7560** | 0.7222 | **+0.0338** | 0.1999 | 0.0293 | ✓ **MODEL ÜSTÜN** |

### KRİTİK DESEN
- **top-1/2/3:** Model AGF'den ZAYIF — public favori-sıralama public-aklı işe yarıyor
- **top-4/5:** Model AGF'den ÜSTÜN — derin lookahead (rolling/pedigree feature'ları) model edge'i veriyor
- En güçlü uplift: **top-5 English ΔAUC +0.034** (anlamlı)

### Pratik sonuç
- **GANYAN (top-1) için model kullanma** — AGF doğrudan iyi
- **PLASE (top-3) için model AGF'ye eşit** — alpha YOK
- **TABELA (top-4) ve top-5 için MODEL ALPHA VAR** — radar/analiz değeri
- Ancak TR'de "tek-at top-4 olur mu" bahsi YOK (Tabela 4-at kombi bahsi); doğrudan kâra çevrilemiyor
- Kombi bahis (TABELA SIRASIZ/SIRALI 4 at) için model top-4 prob'u kullanılabilir → audit/12-13'teki coupon_v2 mantığı genelleştirilir

---

## (B) SİB STALE-LINE — Dürüst Verdict

### Veri envanteri keşfi (ÇOK ÖNEMLİ)
SİB `fixed_odds` **SABİT DEĞİL** — gün içinde değişir (örn race 111790: 10:10→1.00, 11:00→4.75, 13:00→3.20).
Ayrıca **first_sib_odds çoğu zaman 1.00 placeholder** (book açılmadan önce default).
**Gerçek 11:00 SİB:** `fixed_odds > 1.0` filtresi şart.

### V2 analiz (gerçek 11:00 ilan)
- 7,591 SİB at (>1.0 odds), 751 yarış
- Saat dağılımı: %99 saat 11'de (TJK SİB protokol)
- Odds dağılımı: median 12.0, mean 26.7 (long-shot ağırlıklı)

### Stale-line magnitude × ROI

| StaleRatio (SİB/Pari) | N | HitRate | Pari→SİB | ROI | CI 95% | Sig |
|---|---|---|---|---|---|---|
| 0-0.5 | 858 | 10.96% | 355.4→19.7 | −48.85% | [−61.9, −34.2] | ✗ |
| 0.5-0.8 | 1042 | 12.76% | 17.0→11.3 | −42.57% | [−54.1, −30.1] | ✗ |
| 0.8-0.95 | 845 | 13.02% | 14.8→12.9 | −45.18% | [−57.0, −31.5] | ✗ |
| 0.95-1.05 | 574 | 12.54% | 14.0→13.9 | −45.88% | [−61.5, −28.3] | ✗ |
| 1.05-1.20 | 767 | 11.60% | 15.6→17.5 | −35.64% | [−53.7, −14.8] | ✗ |
| 1.20-1.50 | 1047 | 9.65% | 17.9→24.0 | −18.92% | [−41.2, +5.7] | ✓ marg |
| 1.50-2.00 | 914 | 7.22% | 20.5→35.3 | −22.73% | [−47.8, +6.8] | ✓ marg |
| **2.00-5.00** | **1190** | **6.13%** | **18.1→50.6** | **+26.64%** | **[−15.7, +75.5]** | **✓ marg** |
| **5.00-100** | **354** | **3.67%** | **7.6→64.9** | **+94.63%** | **[−17.5, +232.5]** | **✓ marg** |

### Koşul profili (SİB cömert, gap>0 subset)
- AR küçük: n=414, ROI +54.29% CI[−14.5, +138.2]
- TB küçük: n=403, ROI +27.87% CI[−41.9, +113.5]
- BÜYÜK: hep negatif

### Power analizi
SD per-bet = 12.12 (long-shot variance büyük):
- ROI ≥ 5% tespit: **~460,883 bet** gerek (38 yıl forward!)
- ROI ≥ 10% tespit: ~115,221 bet
- ROI ≥ 20% tespit: ~28,806 bet (~2-3 yıl forward)

### DÜRÜST SİB VERDICT
- **Stale-line tezi LONG-SHOT segmentinde MARJİNAL UMUT** (2-100x SİB, SİB pari'den 2x+ cömert)
- **CI alt sınırı HİÇBİR bantta 0'dan büyük DEĞİL** → istatistiksel kanıt YOK
- **N yetersiz** — %20 ROI detection için 2-3 yıl forward log gerek
- TR SİB market'i kabaca verimli, kitap pari'ye paralel hareket ediyor
- AR-küçük-şehir nişi nokta-fırsat olabilir AMA n=414 ile crown edilmez

---

## (C) FORWARD LOGGER — `audit/22_forward_logger.py`

3-fazlı snapshot iskeleti hazır:
- `morning` (11:00) — TJK SİB ilk fiyatları
- `midday` (16:00) — yarış-zamanı oran
- `result` (22:00) — finish_position + final_odds + kapanış SİB

Crontab tavsiyesi (Berkay manuel kurar):
```
0 11 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py morning
0 16 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py midday
0 22 * * * cd /Users/berkay/projects/tjk-ganyan-bot && python3 audit/22_forward_logger.py result
```

Output: `data/forward_logs/sib_YYYY-MM-DD_{phase}.parquet`

---

## (D) ⚠ BUG UYARILARI

### audit/24_model_sib_ev.py — top-4/5 SAHTE ROI
Script `pari_payout_approx = last_pari_odds / k` proxy ile **+500% to +1300% ROI** verdi.
SAHTE — TJK'da "tek-at top-4" bahsi YOK; doğru payout race_bettings TABELA'da kombi.
**Sonuçlar İGNORE.** Top-1 sonuçları geçerli:
- top1/AR EV>=0.50: n=1818 ROI +10.51% CI[−21.6, +45.9] (marjinal)
- top1/EN EV>=0.50: n=1718 ROI −23.01% CI[−47.9, +5.0]

### audit/15 (V3 market grid) NaN bug — daha önce dökümante
Düzeltilmedi, sabah backlog.

---

## GENEL VERDICT

### Bulgular
1. **Model top-4/5 AGF'den ÜSTÜN** — yeni keşif. TR'de "tek-at top-4" doğrudan bahis yok ama coupon (TABELA kombi) için kullanılabilir
2. **SİB stale-line teorik var ama market kabaca verimli** — long-shot nişi belki, 2-3 yıl forward log gerek
3. **Forward logger kurulu** — Berkay cron'a koyarsa hipotez test edilebilir hale gelir

### PUSH KARARI
- **Hiçbir new flag default ON yapılmadı** (kanıt yetersiz)
- Model SÜİTİ artifact'leri push'lu — Berkay isterse `dashboard/yerli_engine.py`'a entegre eder (radar/coupon)
- Forward logger iskeleti push'lu — cron kurulum Berkay'da
- **TJK_COUPON_V2=1 default ON** (önceki commit) korunur

### Sabah backlog (Berkay döndüğünde)
- audit/15 NaN fix + V3-prob market grid rerun
- audit/24 sahte ROI: doğru TABELA kombi payout ile yeniden (model top-4 prob → 4-at kombi → race_bettings TABELA payout)
- Forward logger cron kurulum
- 1-2 ay log birikimi sonrası SİB stale-line forward test
- Model SÜİTİ entegrasyon: coupon_v2 + top-3/4 prob ile coverage genişletme
- Plackett-Luce ranking head (binary'lerden türetim — exacta/quinella için)
