# Analiz Toolu — FINAL Spec (v4 + tier)

**Tarih:** 2026-06-03
**Durum:** BİTMİŞ. Güvenilir + dürüst + tier'lı. Sonsuz iyileştirme yok — gerçek limit'ler belgelendi.
**Disclaimer:** "Analiz amaçlıdır, +EV garantisi değil." Bu bir bahis/para makinesi DEĞİL.

---

## ✅ Final Checklist

| İŞ | Durum | Kanıt |
|---|---|---|
| 1 — Encoder skew temizlik | ✅ | 8 dead _enc DROP (audit/41), v4 retrain max\|ΔAUC\|=0.003 (audit/42) |
| 2 — Radar lift segment | ✅ | audit/43 year×breed×target sweep — 2025 güçlü, 2026 AR zayıf/negatif |
| 3 — Flag-bölgesi kalibrasyon | ✅ | audit/44: 2026'da +0.11-0.17 aşırı güven longshot'larda |
| 4 — 2026 diagnosis | ✅ | audit/45: GENUINE shift (halk +6-9% keskinleşti), veri sorunu yok |
| 5 — Tier'lı digest | ✅ | audit/46: 0 HIGH / 6 MED / 10 LOW gerçek 2026-06-03 programda |
| 6 — Final spec | ✅ | bu belge |

---

## 1. Model Suite — `model/trained_targets_v4/`

**78 feature** (audit/42; v3'ten 8 dead `_enc` drop). 5 binary target × 2 breed × XGB+LGBM+isotonic.

**Drop'lar (SHAP %0-1, audit/41):**
- `sire_enc`, `hippodrome_enc`, `trainer_enc`, `distance_category_enc`
- `weather_condition_enc`, `track_condition_enc`, `sec_pace_style_enc`, `sec_prev1_pace_style_enc`

**Tutulan _enc (SHAP ≥%1):** jockey_enc (8%), dam_enc (2.8%), hf_rest_category_enc (~2%), group_code_enc (~1%), track_type_enc (~1%)

**v3 vs v4 perf eşit** (max \|ΔAUC\|=0.003) — temiz + hızlı.

**Form serve** (audit/29 mantığı, strictly-prior): `dashboard/feature_pipeline.py:compute_serve_form`. Train/serve form parite ✓.

## 2. Edge (DÜRÜST — segment-segment)

ΔAUC = AUC_Model − AUC_AGF_rank (form-served + v4):

| Segment | top-2 | top-3 | top-4 |
|---|---|---|---|
| **2025 AR** | +0.012 | +0.020 | +0.031 |
| **2025 EN** | +0.017 | +0.023 | **+0.036** |
| **2026 AR** | **−0.022** | **−0.017** | −0.005 |
| 2026 EN | −0.003 | +0.002 | +0.014 |

**Genuine shift (audit/45):** 2026'da halk daha keskin (fav_agf +6-9%, fav_hit +3-7%). Model marjı azaldı; AR'da NEGATİF.

## 3. Radar Lift — Segment-Specific Eşikler

audit/43: divergence eşiği × hit-rate lift (pp):

| Segment | thr 0.30 | thr 0.40 |
|---|---|---|
| 2025 AR top3 | **+16.15** | +23.38 |
| 2025 AR top4 | +10.33 | +19.66 |
| 2025 EN top3 | +13.55 | +25.17 |
| 2025 EN top4 | +9.29 | +19.57 |
| **2026 AR top3** | **+2.32** | +11.33 (n=292) |
| **2026 AR top4** | **−4.24** ✗ | +4.43 |
| **2026 EN top3** | +4.29 | +14.68 |
| **2026 EN top4** | **−1.70** ✗ | +7.57 |

**Sonuç:** 2025'te 0.30 yeterli; 2026'da **0.40** lazım; 2026 AR top4 hâlâ marjinal. Düşük eşik (<0.20) HER YERDE noise.

## 4. Flag-Bölgesi Kalibrasyon (audit/44)

Flag bölgesi = model_top_k ≥ 0.40 + AGF ≤ 10% (longshot):

| Year | Breed | Target | Pred | Obs | Δ |
|---|---|---|---|---|---|
| 2025 AR top3 | 52.8% | 42.6% | +10.3pp |
| 2025 EN top3 | 52.7% | 42.3% | +10.4pp |
| **2026 AR top3** | 51.5% | **34.2%** | **+17.3pp** |
| **2026 EN top3** | 52.6% | 38.1% | **+14.5pp** |

**Tüm flag bölgesinde AŞIRI GÜVEN.** Düzeltme: tier (İŞ 5).

## 5. Tier Sistemi (digest)

```
HIGH  ⭐ — radar lift VALİDE + kalibrasyon kabul edilebilir
MED   ◇ — modest aşırı güven (2025 flag bölgesi) veya 2026 EN normal
LOW   ⚠ — 2026 arab (genuine shift, AR top4 negatif) veya
          longshot flag bölgesi 2026 (+%17 aşırı güven)
```

**Gerçek 2026-06-03 programda render:**
- HIGH: 0 (2026'da güvenilir segment çok dar)
- MED: 6 (İngiliz yarışları, longshot olmayan)
- LOW: 10 (Arap yarışları + longshot atlar) — bastırılıyor

**Önceki "Mertens top3 %66 AGF %5 ⭐" örneği → şimdi ⚠ LOW** (audit/44 +17pp aşırı güven kanıtı).

## 6. Format

`dashboard/telegram_formatter_v9.py` — format_v2_message radar+sürpriz okuyor. Disclaimer `_footer`'da.

Kart yapısı (per yarış):
```
🏇 HIPODROM — saat · N. Koşu  [tier güven]
🎯 grup · mesafe · pist · at sayısı
──────────────────
📊 ÖNE ÇIKAN ATLAR:
  ⭐/◇/⚠ #N AT_ADI  topK %X (AGF %Y) div +Zpp SİB oran [tier]
🎲 SÜRPRİZ: skor — neden
  📈 Bucket: fav top-1 %X (lift +/-pp)
ℹ️ analiz amaçlıdır, +EV garantisi değil
```

## 7. NE İDDİA EDİLMİYOR

- **+EV YOK.** Bu para makinesi değil.
- **Top-5 tek-at bahsi yok** TR'de — top-5 yan-not.
- **2026 AR'da edge yok** (negatif ΔAUC).
- **Longshot flag'leri güvensiz** (+%17 aşırı güven).
- **Sahte metrik / crowning yok.**

## 8. NE İDDİA EDİLİYOR (kanıtlı)

- **2025'te English board-finish (top-3/4) için modest edge var** (ΔAUC +0.017-0.036).
- **Radar lift validate** 0.30+ eşikte (2025'te) — flag'lenen atlar baseline'dan +9-25pp daha sık top-3/4'e giriyor.
- **Sürpriz skoru valide** — 0.50+ band'da favori top-1 %23 vs %41 (audit/34).
- **Form serve strictly-prior + sızıntısız** (audit/30 kanaryası temiz).
- **Tier sistemi** kullanıcıyı güvensiz longshot flag'lerden uzak tutar.

## 9. Disclaimer (her kartta)

> "ℹ️ analiz amaçlıdır, +EV garantisi değil — tier: HIGH⭐ MED◇ LOW⚠"

## 10. Forward Iyileştirme Yolu

- 1-2 ay log birikim → 2026 segment'de gerçek hit-rate doğrulama
- 2026 AR'da AGF coverage artımı vs model gerçek değişim ölçümü
- Henery fit periyodik update (β2/β3 — şu an 0.70/0.60)
- Encoder skew için stable hash-based persist (eğer prod-aktive)

---

## Dosya İndeksi

| Dosya | Açıklama |
|---|---|
| `model/trained_targets_v4/` | Final modeller (78 feature, 5 target × 2 breed) |
| `dashboard/feature_pipeline.py` | TEK pipeline (train+serve), form strictly-prior |
| `dashboard/ranking_head.py` | Plackett-Luce exact top-k |
| `dashboard/analysis_runner.py` | per-leg analiz (radar+surprise+disclaimer) |
| `dashboard/surprise.py` | composite skor + bucket |
| `dashboard/telegram_formatter_v9.py` | format radar+surprise blokları |
| `audit/41_enc_shap_audit.py` | _enc dead drop kararı |
| `audit/42_train_v4_clean.py` | v4 retrain |
| `audit/43_radar_segment_lift.py` | year×breed×target lift |
| `audit/44_calibration_niche.py` | ECE + flag bölgesi |
| `audit/45_2026_diagnosis.py` | 2026 negatif sebebi |
| `audit/46_daily_digest_tier.py` | tier'lı kart render |
| `audit/reports/analiz_toolu_FINAL.md` | bu belge |

**Bu tool BİTMİŞ.** Sonraki adım: production'da kullan, 1-2 ay veri birik, sonra re-evaluate.
