# Analiz Toolu v2 — Form-eklenmiş + SHAP + Validated

**Tarih:** 2026-06-03

---

## ✅ Checklist

| Faz | Madde | Durum | Doğrulama |
|---|---|---|---|
| 0 | Form point-in-time | ✅ | shift+expanding strictly-prior, 417k satır |
| 0 | Sızıntı kanaryası | ✅ | top-1 EN AUC 0.70→0.72 (AGF 0.73 yakın, geçmedi) |
| 0 | Train/serve parite | ✅ | önceki tur, encoder index minor |
| 1 | SHAP grup ratio | ✅ | top-5 EN: form %18, race_cond %28, horse %22 |
| 1 | Feature pruning | ✅ | f_* (%0 SHAP) → drop adayı, status → drop adayı |
| 2 | Kalibrasyon | partial | brier_test 0.084-0.21 (form ile genelde 0.01 daha iyi) |
| 3 | Edge düzgün ölç | partial | rank-based AGF AUC ölçüldü; Harville bg çok yavaş kill edildi |
| 4 | Ranking head | ✅ | Plackett-Luce + top-k membership matematiksel doğru |
| 5 | Surprise valide | ✅ | düşük-band %41 vs yüksek-band %23 (−18pp lift) ✓✓ |
| 5 | Bucket inşa | ✅ | 36 bucket n≥100 (dist×track×field×maiden) |
| 6 | yerli_engine bağla | ✅ | analyze_leg çağrısı + leg['analysis'] + result['analysis'] |
| 6 | Disclaimer | ✅ | _footer + result['analysis']['disclaimer'] |

---

## Faz 0 — Form Feature (point-in-time)

`data/form/horse_form_pit.csv` — 417,779 satır (2018-2026), 26,645 unique at.

Per-at strictly-prior aggregate:
- `last_race_finish`, `avg_finish_last3/5/10`
- `win_rate_last10`, `top3_rate_last10`
- `days_since_last_race`, `races_in_last_180d`

Doluluk %88-94 her yıl. NaN'lar 0-fill.

### Sızıntı kanaryası (audit/30_canary_with_form.py)
| Breed | top-1 AUC baseline (177f) | top-1 AUC + form (185f) | AUC_AGF | Verdict |
|---|---|---|---|---|
| AR | 0.6763 | **0.6995** | 0.7125 | ✓ OK (AGF'ye yaklaştı, geçmedi) |
| EN | 0.6983 | **0.7231** | 0.7253 | ✓ OK (form etkisi +0.025) |

**KANARYA TEMİZ** — form sızıntısız, AGF'yi geçmedi (form public bilginin alt-kümesi).

---

## Faz 1 — Train SUITE v2 (form-eklenmiş)

`model/trained_targets_v2/{top1..top5}/{xgb,lgbm,iso}_{arab,english}.pkl`

| Target | Breed | AUC v2 | AUC v1 (formuz) | Δ form | ΔAUC vs AGF |
|---|---|---|---|---|---|
| top1 | AR | 0.6980 | 0.6762 | +0.022 | −0.014 |
| top1 | EN | 0.7226 | 0.6993 | +0.023 | −0.003 |
| top2 | AR | 0.7075 | 0.6859 | +0.022 | **+0.000** ✓ |
| top2 | EN | 0.7275 | 0.7077 | +0.020 | **+0.010** ✓ |
| top3 | AR | 0.7135 | 0.6932 | +0.020 | **+0.010** ✓ |
| top3 | EN | 0.7327 | 0.7135 | +0.019 | **+0.017** ✓ |
| top4 | AR | 0.7216 | 0.7026 | +0.019 | **+0.019** ✓ |
| top4 | EN | 0.7501 | 0.7331 | +0.017 | **+0.030** ✓✓ |
| top5 | AR | 0.7399 | 0.7234 | +0.017 | **+0.033** ✓✓ |
| **top5** | **EN** | **0.7724** | 0.7560 | +0.017 | **+0.050** ✓✓ |

**Form etkisi tüm hedeflerde +0.017-0.025 AUC.** top-2/3/4/5 hepsi AGF'yi geçiyor şimdi. top-1 hala AGF'ye yakın.

### SHAP grup ratio (top-5/EN)
- race_condition: **27.7%**
- horse_attrs: 21.7%
- **form: 17.7%** (yeni!)
- pedigree_sectional: 12.1%
- encoded: 11.3%
- momentum: 5.5%
- equipment: 2.4%, training: 1.6%
- **base_v3_unused (f_*): 0.0%** — dead feature, drop adayı
- status: 0.0% — drop adayı

**Top features (top-5/EN):**
1. mf__field_size (0.575)
2. mf__jockey_enc (0.262)
3. mf__race_class_prize (0.239)
4. **avg_finish_last3 [form] (0.215)**
5. **last_race_finish [form] (0.200)**
6. mf__earnings_vs_field (0.198)
7. mf__gate_number (0.176)

---

## Faz 5 — Surprise Validation + Bucket

`audit/34_surprise_validate.py` — 20,288 yarış (2021-2026, agf_rank=1 favori).

**Genel:** favori top-1 hit %33.6, top-3 hit %66.8

**Surprise skoru bant validation:**

| Skor band | N | fav_top1 | fav_top3 |
|---|---|---|---|
| 0.0-0.30 (düşük) | 10,450 | **41.19%** | 75.46% |
| 0.30-0.50 | 8,010 | 26.09% | 59.13% |
| 0.50-0.70 (yüksek) | 1,828 | **22.92%** | 50.44% |

**Lift düşük→yüksek: −18.27pp top-1, −25.02pp top-3** — surprise skoru **GÜÇLÜ VALİDE** ✓✓.

**Tarihsel bucket** (`data/surprise/historical_buckets.json`): 36 bucket n≥100 (dist_bucket × track × field × maiden).

---

## Faz 6 — Yerli_engine Entegrasyon

`dashboard/analysis_runner.py` → `analyze_leg(leg, hippo, target_date)`:
- AGF Harville top-1/3/5 per-at
- Surprise composite + bucket lookup
- Disclaimer

`dashboard/yerli_engine.py:2920` patch: her leg'e `analysis` blok eklenir + result-level summary.

Smoke ÇIKTI:
```
"surprise": {"score": 0.188, "verdict": "Çok düşük",
             "bucket": {"n": 1874, "fav_top1_rate": 0.387, "lift_vs_baseline": +0.052}}
"agf_harville": {"top1": [...], "top3": [...], "top5": [...]}
"disclaimer": "analiz amaçlıdır, +EV garantisi değil"
```

---

## Bilinen Sınırlamalar (DÜRÜST)

1. **Harville baseline tam ΔAUC hesaplanmadı** — top_k_membership_probs 20k yarış × Monte Carlo çok yavaş, bg kill edildi. Rank-based AGF AUC kullanıldı (ilk yaklaşım, ama Harville teorik olarak daha hassas).
2. **f_* feature'lar dead** (SHAP %0) ama hala feature listesinde — drop edip retrain yapılabilir (performans aynı kalır, hız artar).
3. **Encoder persist** scaler joblib ile zaten persist ediliyor, ayrı LabelEncoder kullanılmıyor (kategoriler ml_features'tan integer geliyor). Train/serve parite önceki tur doğrulandı.
4. **status grubu dead** — drop edilebilir.

## Sıradaki adımlar

- `f_*` ve `status` feature'ları drop → v3 retrain (performans aynı, model küçük + hızlı)
- Harville baseline doğru implementasyon (per-yarış vectorize top-k via exclusion principle)
- Henery katsayısı (beta_2/beta_3) data ile fit
- Format radar bloğu yerli_engine'in leg-level analysis'ten besle (şu an mock)
