# SABAH GRID RAPORU — TR Bahis Marketlerinde +EV Taraması

**Tarih:** 2026-06-02 (gece çalıştırma)
**Analiz:** Tüm parimutuel marketler × stratejiler × dilimler × eşikler
**Walk-forward:** train+val 2016-01-01 → 2024-12-31 | HOLDOUT 2025-01-01 → 2026-06-02
**Sample:** 454,477 horse-bet, 56,929 yarış, 239,034 betting record

---

## FAZ 0 — Veri envanteri

| Veri kaynağı | Durum |
|---|---|
| race_horses.fixed_odds (SİB) | **Yalnız 2026, %31 dolu (~10k at)** — küçük dataset |
| race_horses.odds (parimutuel) | %72 dolu, 2016-2026 zengin |
| race_horses.agf_value (AGF) | Çoğu yıl >%80 |
| race_horses.final_odds | %100 dolu, kapanış oranı |
| GANYAN payout | 39,113 yarış (2016+) |
| PLASE payout | 14,474 yarış (3 satır per yarış) |
| İKİLİ / SIRALI İKİLİ | 32,094 / 37,677 |
| ÜÇLÜ BAHİS | 21,804 |
| Çok-ayak (6'lı/5'li/4'lü) | Önceki analizlerde kapsandı (audit/12, 13) |
| **DB'de İlk-N SİB?** | **YOK** — fixed_odds yalnız WIN (Ganyan SİB) |
| Measurement DB (canlı ROI) | **YOK** (Supabase placeholder, bet_diary migration pending) |

## FAZ 1 — Discrimination (önceki analiz — `audit/13_v3_oos_edge`)

| Metric | AGF | V3 OOS | Δ |
|---|---|---|---|
| AUC | **0.7748** | 0.7501 | −0.0247 |
| Brier | 0.0826 | 0.0847 | +0.0021 |
| ECE | 0.0038 | 0.0073 | +0.0035 |

**V3 model halkı yenmiyor — AUC AGF'den 2.5 puan ZAYIF.**

## FAZ 2 — Grid sonuçları (yeni, bu gece)

### Pillar 1 — AGF/odds/edge sweep (audit/14 + 16)

**294 in-sample × 144 holdout config tarandı. Bootstrap 5000-iter CI.**

**En iyi 5 holdout +ROI (n_bets ≥ 50):**

| Strategy | Slice | edge | N | HitRate | ROI | CI %95 |
|---|---|---|---|---|---|---|
| GANYAN edge_agf_minus_mkt | all | 0.07 | 83 | 34.9% | **+31.93%** | [−17.59, +89.89] |
| GANYAN edge_agf_minus_mkt | all | 0.06 | 110 | 32.7% | **+22.68%** | [−18.73, +71.50] |
| GANYAN edge_agf_minus_mkt | buyuk | 0.06 | 84 | 34.5% | **+31.19%** | [−18.81, +87.50] |
| GANYAN edge_agf_minus_mkt | buyuk | 0.07 | 64 | 34.4% | **+32.42%** | [−23.21, +100.09] |
| GANYAN edge_agf_minus_mkt | all | 0.08 | 64 | 35.9% | +16.25% | [−27.27, +63.91] |

**⚠ HİÇBİR CONFIG'İN %95 CI ALT SINIRI 0'DAN BÜYÜK DEĞİL.**

Bonferroni-corrected (144 test, alfa=0.05/144=0.00035): 21 holdout +ROI / 144 = %14.6 success rate. Beklenen-by-chance ~%5 (one-tail). Marjinal sinyal var ama istatistiksel kanıt değil.

### Pillar 2 — SİB (fixed_odds 2026)

**Sonuç: HEPSİ NEGATİF.** 7,727 SİB satırı içinde edge≥0.02 filtresi sonrası N maks 9 → istatistiksel test imkânsız. SİB market'i 2026'da yeni başlamış, fixed_odds çoğunlukla AGF ile uyumlu (edge nadir).

| Slice | edge | N | ROI |
|---|---|---|---|
| AR | 0.02 | 7 | −64.29% |
| all | 0.02 | 9 | −72.22% |
| TB | 0.02 | 2 | −100% |
| (edge≥0.03+) | — | <5 | −100% |

→ **SİB GANYAN'da +EV YOK** (mevcut dataset ile, küçük sample).

### Pillar 3 — Kombi marketler (audit/17)

**Tek-strateji: top-N AGF rank kombinasyonu (n=2/3/4/5)**

| Market | n_pick | Slice | IS_N | IS_ROI | HO_N | HO_ROI |
|---|---|---|---|---|---|---|
| **ÜÇLÜ BAHİS** | 3 | field_large | 4,380 | −87.35% | **1,008** | **+28.86%** |
| **ÜÇLÜ BAHİS** | 4 | buyuk | 262,152 | −88.01% | **71,352** | **+1.00%** |
| **ÜÇLÜ BAHİS** | 4 | field_med | 181,992 | −88.41% | **43,392** | **+3.26%** |
| **ÜÇLÜ BAHİS** | 5 | field_small | 279,540 | −87.19% | **94,020** | **+5.29%** |
| İKİLİ / SIRALI | tümü | tümü | — | −40-50% | — | −30-40% |

**ÜÇLÜ BAHİS in-sample (2016-2024) −%88 ROI vs holdout (2025-2026) +%1 ile +%29.**

Hipotez: **TJK ÜÇLÜ market 2025'te platform değişikliği** (ödüller artmış veya takeout düşmüş). In-sample/holdout ROI ayrımı %90 — kırık baseline. PRODUCTION'A ALINMAZ (bu rejim sürer mi belirsiz, 1-2 yıl daha veri gerek).

İKİLİ / SIRALI İKİLİ her dilimde negatif (TR'de favori-overbet × takeout = kayıp).

### Pillar 4 — V3 prob ile market grid (audit/15, background)

V3 OOS (2025-05-24 → 2026-06-02) 9k yarış için V3 predict + market backtest. Background süreç hâlâ çalışıyor — sonuç beklemede.

---

## DÜRÜST VERDICT

### 1. Gerçek +EV market var mı?
**Net cevap: KANITLANMIŞ +EV market YOK.** 

- Edge stratejisi (AGF prob > market_implied + 0.05) holdout'ta marjinal +ROI gösteriyor (+%2 ile +%32) AMA hiçbir config'in **%95 CI alt sınırı 0'dan büyük değil**. Bootstrap çıktıları geniş varyans → tesadüf etkisi elenemez.
- ÜÇLÜ BAHİS 2025+'da +ROI gösteriyor AMA in-sample/holdout regime divergence var (−88% → +5%). TJK ödül değişikliği muhtemel. **Sürdürülebilir alpha değil.**
- SİB (fixed_odds) test edilemiyor: 2026'da %31 dolu, edge bandlarında N<10.

### 2. V3 model alpha?
**HAYIR — V3 AUC AGF'den ZAYIF** (0.750 vs 0.775). V3 model halkı yenmiyor, sadece kalibrasyon kuralı.

### 3. Mevcut sistem (V2 coupon + V3 prob)?
**−%17 ROI** (eski −%72'den 4x iyi) ama hala kayıp. UX iyileştirmesi var (sade kupon, değişken genişlik) — net kayıp azaltıcı (Berkay sürdürür).

---

## PUSH KARARI

**Berkay direktifi: "config holdout'ta NET +EV ise → flag arkası + push. Hiçbiri değilse → push (rapor) + dürüst verdict."**

**Hiçbir config NET +EV değil → push (rapor + leaderboard), default OFF.**

`TJK_EDGE_BET` ENV-FLAG kurulmadı çünkü kanıt yetersiz. Edge stratejisi (AGF > market_implied + 0.07) MANUEL test için açık — Berkay isterse 1-2 ay canlı dener, gerçek ROI birikir.

## NEVER-STOP backlog (sabah devam)

- V3 market grid (background buu/15) — V3 prob ile divergence stratejisi
- Top-N classifier retrain (place / show hedefli) — yeni model
- 7'Lİ PLASE backtest (4,394 yarış, max payout 810k)
- Çok-ayak SİB kombinasyonu (fixed_odds genelleşince)
- Sample biriktikçe edge stratejisinin canlı ROI'sini izle (1-2 ay bet_diary)

---

**SONUÇ:** TR bahis piyasasında sistematik +EV **KANITLANAMADI**. Mevcut sistem (V3-prob V2-coupon) kayıp azaltıcı ama net negatif. Sürdürülebilir alpha aramak için: (a) sample biriktir, (b) classifier retrain, (c) bet_diary canlı ROI 1-2 ay sonra re-evaluate.
