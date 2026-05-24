# Phase 0 — DATA AUDIT — Kapanış Özeti

Tarih aralığı: 2026-05-21 → 2026-05-23
Branch: `refactor`
Prensip: ölçüm yapıldı, kod düzeltilmedi (writer bug dahil — raporlandı, dokunulmadı).

---

## Ne sorduk / ölçtük (4 alan)

1. **Kaynak güvenilirliği** — hangi veri kaynağı ne kadar sağlam, fallback gerçek mi?
2. **Feature kullanımı** — model 96-D'nin kaçını gerçek sinyalle, kaçını default'la dolduruyor?
3. **Kalibrasyon** — model olasılıkları gerçek sonuçla karşılaştırılıyor mu?
4. **AGF tier ayrımı** — "3-tier fallback" iddiası gerçek mi?

---

## Ana bulgular (numerik)

### Feature doluluk (96-D)
- **45 ✅ tam-dolu / 51 ⚠ default-maskeli** (%53 default'a düşebilir)
- ✅ = eksikse NaN/drop (görünür arıza). ⚠ = eksikse sessiz sabit (model gerçek sinyal sanır)
- Tam-dolu: race_level (19), interactions (26 — ama kalite parent'tan miras)
- Default-maskeli: agf(8), physical(8), form(8), jockey_trainer(5), pedigree(8), pace(3), other(7), equipment(4)
- Duplicate: `f_X_weight_dist` ≡ `f_X_weight_distance` (backward-compat dead-weight, features.py:357-360)

### AGF "3-tier fallback" → gerçekte tek-kaynak
- Pipeline-level 3 tier (yerli_engine.py:2371): proper → local → dashboard
  - Bunlar **ImportError fallback'i**, data-outage fallback'i DEĞİL
- Üçü de aynı upstream'e gider: **agftablosu.com**
- Scraper-level (agf_scraper.py:61): tek URL, 3 retry × 2s
- **Canlı kanıt (2026-05-23):** AGF prod'da HTTP 403 (bot koruması). Prod pipeline `source: dashboard` tier'ına düşmüş, 2 altılı `REPAIRED_FROM_TJK`

### measurement writer key mismatch (P0)
- `record_kupons_from_pipeline_result` (measurement.py:857-859) `kupon_dar`/`kupon_genis` arıyor
- Pipeline result `dar`/`genis`/`v7_coupon` yazıyor → eşleşme yok → `attempted=0`
- **Lokal kanıt:** model_used=True, kupon dolu, ama kupons.jsonl boş
- **Prod kanıt (HTTP /api/measure/status):** measurement_kupons=0, matches=0, results=0, pipeline_runs=11. Son run status=success, telegram_sent=true, **kupon_count=0**
- → Ölçüm katmanı (JSONL + Supabase) fiilen veri toplamıyor. JSONL prod'da ayrıca volume'suz (devre dışı)

### multi_source_validator yazılmış ama bağlı değil (kritik)
- `dashboard/multi_source_validator.py` 3 GERÇEK kaynağı çapraz-doğruluyor:
  agftablosu + tjk_official (www.tjk.org) + horseturk
- Ama yalnız `/api/source_check` teşhis endpoint'inde. **Kupon pipeline'ı kullanmıyor.**
- → "Sağlam çok-kaynak"ın yarısı zaten var; sadece pipeline'a bağlanmamış. Phase 1A'nın temeli bu.

### retro fetch_results de agftablosu'na bağımlı
- engine/retro.py:142 `fetch_results` → agftablosu.com/at-yarisi-sonuclar (TJK fallback)
- Lokal IP'den çalışıyor (21 May: 6 altılı, 22 May: 12 altılı sonuç geldi), ama prod IP'de AGF 403

### Kalibrasyon
- Ölçüm YOK: matches.calibration JSONB boş placeholder, model_prob ↔ outcome join hiçbir yerde yok
- Kalibrasyon **mekanizması** kanıtlandı: 21 Mayıs snapshot model-pick ↔ gerçek kazanan join çalıştı (1/6 hit), ama n=6 → istatistiksel anlamsız
- Engel: snapshot date drift (dosya adı date.today(), içerik target_date — yerli_engine.py:2169) + sonuç verisi hizalama

---

## Phase 1 alt-fazları

- **1A — Shadow Validator Integration** (BU COMMIT'TE BAŞLIYOR): validator pipeline'a
  read-only bağlanır, gözlemler, karar vermez. Shadow log toplar.
- **1B — Confidence-based source selection**: validator confidence'a göre kaynak seçimi
- **1C — Low-confidence race flag/skip**: düşük güvenli ayakları işaretle/atla
- **1D — Calibration dataset generation**: model_prob ↔ outcome join veri seti
- **Phase 2** — Kalibrasyon (Brier/ECE/reliability, 1D verisi üzerinden)
- **Phase 3** — UI/Telegram format birleştirme + **writer bug fix** (P0 ölçüm onarımı)
- **Phase 4** — Foreign arb canlandırma (aşağıda)

---

## Discovered legacy assets (Phase 4 hedefi)

Phase 0 sırasında keşfedilen, şu an atıl duran arbitraj altyapısı:

- **STRATEJI tab konsepti** — TJK %27 takeout vs Betfair %2 spread arbitrajı
  (dashboard/index.html + app.py'de tab var)
- **Kaynaklar:** `scrapers/tjk_foreign.py:204` + `dashboard/tjk_scraper.py:264`
  `fetch_foreign_races`
- **Edge motoru:** `dashboard/edge_calc.py` — `TAKEOUTS` 6 kaynak
  (tjk:0.27, tab_au:0.16, betfair:0.02, oddschk:0.08, twinspires:0.20, betfair_uk:0.02)
  - Edge formula: Hausch-Ziemba (1990) — `norm_prob(ref) - norm_prob(tjk)`
  - FLB (favorite-longshot bias) filtresi: Griffith (1949)
- **Durum:** Şu an sadece TJK HTML scraper çalışıyor, **5 yabancı kaynak gri**
- **Hedef:** Phase 1-3 tamamlandıktan sonra Phase 4'te canlandırma

---

## Kapanış

Phase 0 (DATA AUDIT) KAPALI. 4 alan ölçüldü, 2 P0 bug (writer mismatch, AGF tek-nokta)
ve 1 fırsat (bağlanmamış multi-source validator) tespit edildi.

**Phase 1A bu commit'te başlıyor.**
