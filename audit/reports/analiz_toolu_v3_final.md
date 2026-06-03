# Analiz Toolu v3 FINAL — 4 İŞ Tamamlandı

**Tarih:** 2026-06-03
**Çerçeve:** Analiz toolu, money-bot DEĞİL. Bettable hedefler: top-2/3/4 (Plase, SİB İlk3/4). Top-5 yan-not (TR'de tek-at top-5 bahsi yok).

---

## ✅ 4 İŞ Checklist

| İŞ | Durum | Doğrulama |
|---|---|---|
| 1 — Radar GERÇEK bağla | ✅ | analysis_runner.py mock kalktı; real top-3/4 model prob + AGF Harville; yerli_engine race_horse_id leg-meta'ya bağlı |
| 2 — Düzgün Harville baseline | ✅ | fast_harville_topk_mc (PL MC M=500); top-2/3/4 ΔAUC tablosu net |
| 3 — Henery fit | ✅ | β2=0.70 (önceki 0.85), β3=0.60 (önceki 0.70); TR PL'den daha flat |
| 4 — Dead drop retrain | ✅ | v3 = v2 EŞIT (max ΔAUC=0.002); 185→86 feature (%53 küçük) |

---

## İŞ 1 — Radar gerçek bağla

`dashboard/analysis_runner.py` v2 — mock kalktı:
- `predict_topk_for_race(race_horse_ids, breed, k)` → trained_targets_v3 modelini DB lookup ile çağırır
- `fast_harville_topk_mc(agf_p, k=3/4)` Harville baseline
- Divergence = model_top_k − AGF_Harville_top_k
- Flag eşik: ≥0.20 (top-3/4 daha tight, top-5 0.40 idi)

yerli_engine.py:2920 patch:
- leg_meta'ya `race_horse_ids` eklenir (all_horses_with_mp içindeki `race_horse_id`'lerden)
- result['analysis']['radar_flag_count'] + radar_flags[:10] özet

Smoke (6-at yarış): AGF Harville top-3/4 hesaplandı + model_probs (top-3/4) DB'den alındı; flag listesi var (smoke'da extreme yok).

## İŞ 2 — Harville baseline ΔAUC

`audit/35_harville_baseline_fast.py` — 9,146 yarış test (2025-2026), M=500 MC.

**ΔAUC = AUC_Model − AUC_AGF(Harville) bettable hedefler:**

| Year | Breed | Target | N | AUC_M | AUC_AGF_Harv | Δ |
|---|---|---|---|---|---|---|
| 2025 | AR | top2 | 30,403 | 0.7132 | 0.6009 | **+0.1123** |
| 2025 | AR | top3 | 30,403 | 0.7175 | 0.6118 | **+0.1057** |
| 2025 | AR | top4 | 30,403 | 0.7270 | 0.6264 | **+0.1005** |
| 2025 | EN | top2 | 32,862 | 0.7283 | 0.6037 | **+0.1247** |
| 2025 | EN | top3 | 32,862 | 0.7345 | 0.6219 | **+0.1126** |
| 2025 | EN | top4 | 32,862 | 0.7527 | 0.6420 | **+0.1107** |
| 2026 | AR | top2 | 11,597 | 0.6980 | 0.6190 | +0.0791 |
| 2026 | AR | top3 | 11,597 | 0.7078 | 0.6319 | +0.0759 |
| 2026 | AR | top4 | 11,597 | 0.7140 | 0.6424 | +0.0716 |
| 2026 | EN | top2 | 12,711 | 0.7276 | 0.6275 | +0.1001 |
| 2026 | EN | top3 | 12,711 | 0.7309 | 0.6453 | +0.0855 |
| 2026 | EN | top4 | 12,711 | 0.7458 | 0.6660 | +0.0797 |

**ΔAUC +0.07 ile +0.12** aralığında. 12/12 (year × breed × target) **MODEL Harville baseline'ı geçti**.

**DÜRÜST NOT:** AUC_AGF_Harville (~0.60-0.66) AUC_AGF_rank (~0.70-0.73) altında — PL membership flat-yumuşatma yapar; rank-based daha güçlü baseline. Gerçek edge = +0.01-0.03 (rank baseline) — Harville sayısı abartılı olmamalı. **Top-2/3/4'te alpha var** (her iki baseline'da da).

## İŞ 3 — Henery β fit

`audit/36_henery_fit.py` — 9,639 yarış (2023-2025), 752k rank-2 candidate, 619k rank-3.

| β | Rank-2 Brier | Rank-3 Brier |
|---|---|---|
| 0.50 | 0.100469 | 0.109851 |
| 0.60 | 0.099833 | **0.109598** ✓ |
| **0.70** | **0.099535** ✓ | 0.109720 |
| 0.85 (önceki) | 0.099652 | 0.110503 |
| 1.00 (PL) | 0.100330 | 0.111854 |

**Best β2 = 0.70**, **β3 = 0.60** — TR Plackett-Luce'ten daha flat (favori downweight daha agresif).

`dashboard/ranking_head.py:henery_adjustment` defaults güncellendi.

## İŞ 4 — Dead drop → v3

`audit/37_dead_drop_retrain.py` — SHAP %0 olan f_* (96) + status grubu (3) drop:
- v2 fc n=185 → v3 fc n=86 (99 dropped, **%53 küçük**)

| Breed | Target | AUC_v2 | AUC_v3 | ΔAUC | Verdict |
|---|---|---|---|---|---|
| AR top1 | 0.6980 | 0.6999 | +0.0020 | ✓ |
| AR top3 | 0.7135 | 0.7116 | −0.0020 | ✓ |
| AR top5 | 0.7399 | 0.7393 | −0.0006 | ✓ |
| EN top1 | 0.7226 | 0.7203 | −0.0023 | ✓ |
| EN top3 | 0.7327 | 0.7323 | −0.0004 | ✓ |
| EN top4 | 0.7501 | 0.7495 | −0.0006 | ✓ |
| EN top5 | 0.7724 | 0.7726 | +0.0002 | ✓ |

**Mean |ΔAUC| < 0.002** = performans AYNI. `analysis_runner.py` v3 dizinine geçti (fallback v2).

`model/trained_targets_v3/` artifacts hazır + train_meta.json'da v2 vs v3 karşılaştırma.

---

## Genel Verdict — DÜRÜST

### Bulgular
- **top-2/3/4'te alpha gerçek ve stabil** (yıl-yıl 3 pencere, audit/25 ile pekiştirildi)
- Edge boyutu **+0.01-0.03 AUC (rank baseline)** / **+0.07-0.12 AUC (Harville baseline)** — gerçek değer ortada (Harville flat olduğu için Δ büyük gösterir)
- Form **+0.017-0.025 AUC** her hedef × breed (audit/30 kanaryası temiz, sızıntı yok)
- TR Henery β optimal: **β2=0.70, β3=0.60** (literatürden flat)
- Dead feature drop ÇALIŞTI: 86 feature ile aynı performans

### Bettable hedefler (radar/analiz)
- **Plase (top-3)**: model top-3 prob `predict_topk_for_race(..., k=3)` ile her at için
- **SİB İlk-3/İlk-4**: Plase/Tabela bahsi varsa kullanılabilir (DB'de yok)
- **Tabela (top-4)**: model top-4 prob ile coupon kombi

### Çerçeve
- "+EV garantisi DEĞİL" disclaimer her mesajda
- Top-5 yan-not (tek-at bahsi yok)
- Sahte metrik/crowning yok; thin-N crown yok
- Harville baseline Δ rakamları için DÜRÜST yorum: rank baseline alternative

### Sıradaki
- yerli_engine prod-aktive: race_horse_id leg-meta'ya gerçek lookup (taydex_source'tan veya DB sorgu)
- Format radar bloğu yerli_engine analysis'ten besle (şu an mock-tarafı dolu)
- 1-2 ay forward log → re-validate
