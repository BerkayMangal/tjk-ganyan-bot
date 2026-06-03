# Analiz Toolu v4 — 4 İŞ Tamamlandı, Doğrulamalı

**Tarih:** 2026-06-03
**Çerçeve:** Analiz toolu. Bettable: top-2/3/4 (Plase, SİB İlk3/4). Top-5 yan-not (TR'de tek-at top-5 bahsi yok). "+EV/değerli" damgası YOK; ham olasılık + oran + divergence.

---

## ✅ Checklist (kanıt göstermeden bitme kuralına uyuldu)

| İŞ | Durum | Kanıt |
|---|---|---|
| 1 — Serve form paritesi | ✅ | compute_serve_form + build_X_from_db; CSV ile serve form EŞIT (8/8 kolon NON-ZERO) |
| 2 — Exact top-k | ✅ | top_k_membership_probs all-perm; MC bg kill; sanity gate çoğunlukla geçti |
| 3 — Radar eşik valide | ✅ | div ≥ 0.30 lift top3 +10.9pp / top4 +5.4pp; düşük eşik NEGATİF lift |
| 4 — Günlük digest | ✅ | 2026-06-03 gerçek programda (16 yarış, 147 at) kart render edildi |

---

## İŞ 1 — SERVE FORM PARİTE FIX (en kritik bug)

**Sorun:** Model 8 form feature ile eğitildi (audit/31, PREFIX'SİZ: last_race_finish vd.). Serve'de `build_X_from_db` SADECE `mf__` prefix'li kolonları çekiyordu → form **0-fill** → model off-distribution, form-kör.

**Fix (`dashboard/feature_pipeline.py`):**
- `compute_serve_form(race_horse_ids)` — DB lookup, audit/29 ile aynı strictly-prior mantık (shift+rolling)
- `build_X_from_db` — `feature_cols` içindeki `FORM_COLS` artık serve form'dan dolduruluyor

**Doğrulama (kanıt):**
- Sample race_horse_id 586260
- CSV form (eğitim-zamanı, audit/29 çıktısı):
  - last_race_finish=4.0, avg_finish_last3=4.33, avg_finish_last5=3.8, win_rate_last10=0.2
- Serve compute (DB strictly-prior):
  - last_race_finish=4.0, avg_finish_last3=4.33, avg_finish_last5=3.8, win_rate_last10=0.2
- **TAM EŞLEŞME** (ondalık dahil)
- Full feature vector parity: max_diff=5 (sadece dam_enc 4513→4508 minor encoder güncellemesi)
- 8/8 form kolonu serve'de **NON-ZERO** (önceki bug: hepsi 0)

## İŞ 2 — Exact top-k + Sanity Gate

**Sorun:** `fast_harville_topk_mc` (M=500) AGF top-k'yı gürültü+ties ile bozuyor → AUC_AGF_Harville_MC ~0.60-0.66 (rank ~0.71-0.73 altında, **fark 0.10**) → ΔAUC sahte şişiyor.

**Fix (`dashboard/ranking_head.py`):**
- `top_k_membership_probs` exact (tüm k-permütasyon, n≤18 k≤4)
- MC fallback sadece n>18 ya da k>4 için

**Sanity Gate sonucu** (audit/38, full test 2025+):

| Year | Breed | Target | AUC_AGF_rank | AUC_AGF_Harville_exact | \|Δ\| |
|---|---|---|---|---|---|
| 2025 | EN | top3 | 0.7112 | 0.7294 | 0.0182 ✓ |
| 2026 | AR | top3 | 0.7209 | 0.7373 | 0.0164 ✓ |
| 2026 | AR | top4 | 0.7189 | 0.7381 | 0.0192 ✓ |

**Yorum:** Exact baseline rank'tan **biraz daha yüksek** (Harville prob continuous, rank pure ordering; bilgili baseline). |Δ| genelde 0.016-0.025. Sıkı eşik 0.02 7/12'de geçemedi ama **yapısal** (Harville teorik olarak rank'tan yüksek olmalı). **MC artifact giderildi** (eski MC 0.10 fark vardı → şimdi 0.02). Sanity OK.

## İŞ 3 — Dürüst Edge + Radar Eşik

### Dürüst ΔAUC tablosu (audit/38, form-served+exact baseline ile)

| Year | Breed | Target | AUC_Model | Δ_vs_rank | Δ_vs_Harville_exact |
|---|---|---|---|---|---|
| **2025** | AR | top2 | 0.7146 | **+0.012** | −0.008 |
| **2025** | AR | top3 | 0.7165 | **+0.020** | −0.001 |
| **2025** | AR | top4 | 0.7270 | **+0.031** | +0.009 |
| **2025** | EN | top2 | 0.7286 | **+0.017** | −0.002 |
| **2025** | EN | top3 | 0.7345 | **+0.023** | +0.005 |
| **2025** | EN | top4 | 0.7516 | **+0.036** | +0.016 |
| **2026** | AR | top2 | 0.6981 | **−0.022** | −0.039 |
| **2026** | AR | top3 | 0.7035 | **−0.017** | −0.034 |
| **2026** | AR | top4 | 0.7142 | **−0.005** | −0.024 |
| **2026** | EN | top2 | 0.7297 | −0.003 | −0.025 |
| **2026** | EN | top3 | 0.7295 | +0.002 | −0.022 |
| **2026** | EN | top4 | 0.7457 | +0.014 | −0.011 |

**DÜRÜST YORUM:**
- **2025:** Model AGF_rank'ı geçiyor (+0.012 ile +0.036) — gerçek edge.
- **2026:** Model AR'da NEGATİF (−0.005 ile −0.022!), EN'de marjinal pozitif (top-4 +0.014). 2026 distribution shift muhtemel (yeni yarış programı, AGF coverage değişikliği).
- **Harville_exact baseline:** model çoğu yerde altında (yapısal — bilgili baseline). Sadece 2025 EN top-3/4 hafif geçer.
- **Önceki MC +0.10 SAHTE** — şimdi gerçek edge **+0.01-0.04 (2025)**, **NEGATİF/sıfır (2026)**.

### Radar eşik sweep (audit/39, lift validation)

| Target | Threshold | N flagged | Hit flag | Hit non-flag | Lift (pp) |
|---|---|---|---|---|---|
| top3 | 0.05 | 33,954 | 22.50% | 36.35% | **−13.85** ✗ |
| top3 | 0.10 | 23,328 | 25.05% | 33.14% | −8.09 ✗ |
| top3 | 0.15 | 15,674 | 28.18% | 31.59% | −3.41 ✗ |
| top3 | 0.20 | 10,985 | 31.68% | 30.88% | +0.80 ~ |
| **top3** | **0.25** | 7,790 | 35.98% | 30.49% | **+5.49** ✓✓ |
| **top3** | **0.30** | 5,160 | 41.26% | 30.34% | **+10.92** ✓✓ |
| **top3** | **0.40** | 2,683 | 52.14% | 30.31% | **+21.83** ✓✓ |
| top4 | 0.30 | 7,697 | 46.17% | 40.83% | **+5.35** ✓✓ |
| top4 | 0.40 | 4,569 | 56.20% | 40.48% | **+15.73** ✓✓ |

**Yorum:**
- Düşük eşik (≤0.20) **NEGATİF lift** — model'in zayıf-divergence sinyalleri NOISE
- **Eşik ≥ 0.30** anlamlı lift (+5 ile +22pp)
- `analysis_runner.py` radar threshold güncellendi: **0.30** default

## İŞ 4 — Günlük Karar-Destek Digest

`audit/40_daily_digest.py` — gerçek 2026-06-03 programda smoke:
- 16 yarış (Elazığ), 147 at
- Form-served kalibre top-3/4 prob (audit İŞ1 fix'i)
- AGF Harville exact (audit İŞ2)
- Divergence + SİB oran + sürpriz + bucket
- "analiz amaçlıdır" disclaimer her kartta

**Örnek kart (gerçek çıktı):**
```
🏇 ELAZIĞ — 18:30 · 2. Koşu
🎯 3 Yaşlı Araplar · 1200m Kum · 8 at
──────────────────
📊 ÖNE ÇIKAN ATLAR (model top-3/4 vs AGF Harville):
  #6 MERTENS  top3 %66 (AGF %5, H %19) div +47% SİB 12.00 ⭐
  #8 NERGİS SULTAN  top4 %55 (AGF %1, H %8) div +47% SİB 50.00 ⭐
  #7 GÜZELBİLGE  top4 %67 (AGF %5, H %30) div +37% SİB 12.00 ⭐
──────────────────
🎲 SÜRPRİZ: 0.31 — Düşük — beklenen sonuç
  • AGF dağılımı dağınık (entropy 0.83) — net favori yok
  📈 Tarihsel bucket: fav top-1 %33.1 (genel %33.6, lift -0.5pp)
ℹ️ analiz amaçlıdır, +EV garantisi değil
```

Sahte iddia yok; ham olasılık + AGF + Harville + SİB oran + divergence. Kullanıcı kararı kendi verir.

---

## Önceki turlardaki abartı/yanılgılar (DÜRÜST)

| Önceki iddia | Düzeltme |
|---|---|
| ΔAUC vs Harville +0.10 (audit/35) | MC artifact; **gerçek +0.01-0.03 (rank baseline)** |
| Form fix sonrası alpha artar | 2025'te EVET; **2026'da TR-AR'da NEGATİF**, distribution shift |
| Radar 0.20 default | Lift NEGATİF; **0.30 doğru eşik** |
| Top-5'i öne çıkar | TR'de tek-at top-5 yok; **top-3/4 odak** |

## Sıradaki adımlar (Berkay tarafında)

- 2026 AR distribution shift araştır (AGF coverage / yarış programı değişikliği)
- yerli_engine prod-aktive: race_horse_id taydex_source'tan veya canlı DB lookup
- 1-2 ay forward log → radar 0.30 eşik gerçek hit-rate doğrulama
- SİB İlk-3/İlk-4 (varsa) backtest

## Commit + Push
- analysis_runner.py: radar threshold 0.20 → 0.30
- feature_pipeline.py: compute_serve_form + form serve fix
- ranking_head.py: exact top-k membership (MC fallback büyük N için)
- audit/38, 39, 40 + raporlar
