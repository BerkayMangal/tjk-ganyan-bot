# TJK Ganyan Bot — Claude Code Briefing

## Ne yapıyor
Türk at yarışı 6'lı ganyan tahmin botu. AGF (piyasa) + TJK bülten (form/jokey) →
96 feature → XGB+LGBM ensemble (Arab/İngiliz breed-split) → DAR + GENİŞ kupon →
Telegram + Railway dashboard. Bonus: Ganyan Value Bot (model > piyasa) ayrı alarm.

## ÖNEMLİ: Mimari uyarısı
İki paralel pipeline VAR ama prod'da SADECE `dashboard/yerli_engine.py` çalışıyor.
- `main.py`, `engine/kupon.py`, `engine/commentary.py` → LEGACY, prod'da koşmuyor
- `dashboard/yerli_engine.py` (5656 satır) → ASIL prod motor, scheduler buradan
- `dashboard/source_consensus.py` → SHADOW (read-only). Phase 1B.1'de
  `expert_consensus.build_consensus` (at-level, result['consensus']) tabanlı.
  consensus_top_pick dolu. dual-write: JSONL + event_store. Kupon kararını etkilemez.
- `dashboard/bet_diary.py` → bet günlüğü (CLV/EV/Kelly math + persistence).
  dual-write JSONL + event_store('bet_decision')
- `dashboard/bet_diary_writer.py` → pipeline ↔ bet_diary köprüsü (Phase 1E.1/1E.2).
  write_predictions_for_altili (yerli_engine, top-3/ayak) + update_outcomes_for_date
  (retro, sonuç+P&L). Loose coupling, never-raises, sadece KAYIT (davranış değişmez)
- `dashboard/event_store.py` → Phase 1A.5 persistent storage (Supabase `pipeline_events`,
  writer-bug'tan bağımsız; URL yoksa graceful no-op)
- `dashboard/migrations/{m3_pipeline_events,m4_bet_diary}.sql` → additive migration'lar
  (MANUEL APPLY — bkz. phase_1a5_migration_apply_playbook.md; URL set + psql -f)
- AGF: agftablosu için DÜZ requests kullan (cloudscraper bu sayfada 17KB eksik içerik,
  brotli decode sorunu — SO-6). prod 403 ayrı: IP-based block → Phase 4 proxy (SO-5).
  `agf_scraper.py` hâlâ cloudscraper (SO-7, dokunulmadı)
- `Dockerfile` ve `railway.toml` ikisi de `cd dashboard && gunicorn app:app` çalıştırıyor

README henüz `main.py --schedule`'dan bahsediyor → yanıltıcı, ileride güncellenecek.

## Patch konvansiyonu — ARTIK YOK
67 tane `PATCH_FAZ*_v1`, `PATCH_M*_v1` marker'ı birikmiş. Bundan sonra:
- YENİ `PATCH_*` marker'ı EKLEME. Direkt temiz koda yaz.
- Eski PATCH bloklarına dokunduğunda, marker'ı kaldır, kodu modüle taşı.
- Refactor branch'inde çalışıyoruz, prod (main) ayrı.

## Dosya boyutu kuralı
Yeni dosya 500 satırı geçiyorsa modüle bölünmeli. Geçmeden önce sor.

## Veri kaynakları (hassasiyet sırasıyla)
1. AGF (agftablosu.com) — sequential 6-race matching
2. TJK HTML (programme) — form/jokey/kilo/pedigree, HTML → CSV CDN fallback
3. TJK PDF (legacy fallback)
4. HorseTurk (expert consensus, opsiyonel)
5. Taydex (historical, training-time only — runtime'da yok)

## AGF "3-tier fallback" — iddia vs gerçek
README ve eski yorumlar "3-tier fallback chain" der. Doğru kelime DEĞİL. Aslında:

**Pipeline-level (yerli_engine.py:2371-2398)** — IMPORT fallback, data outage'a karşı DEĞİL:
- Tier 1: `from scraper.agf_scraper import ...`
- Tier 2: `from agf_scraper_local import ...` (dashboard/ kopyası)
- Tier 3: `_fetch_domestic_tracks()` → `fetch_domestic_races()` (dashboard scraper)

**Scraper-level (agf_scraper.py:61-76)** — tek URL'e retry:
- `https://www.agftablosu.com/agf-tablosu`
- 3 attempt, 2s backoff arası, timeout=30s

**Gerçek:** Üç pipeline tier'ı da aynı upstream'e (`agftablosu.com`) HTTP isteği atıyor.
agftablosu.com çökerse hepsi çöker. Fallback sadece **kod hatalarına / module-not-found'a** koruma.
"AGF down → predictions skipped" mesajı ÜRETİLMİYOR şu an. Phase 1+ için not.

## Çalıştırma
- Lokal smoke test:    `python smoke_test_m2.py`
- Dashboard lokal:     `cd dashboard && gunicorn app:app -b 0.0.0.0:8080`
- Belirli tarih:       `python main.py 2026-05-21`  (legacy, ama feature build için kullanışlı)

## Env vars
- TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID (lokal testte boş bırak → console'a basar)
- TJK_MEASURE_DB_URL (Supabase, opsiyonel)
- TJK_DATA_DIR (JSONL backend, opsiyonel)

## Phase status
- **Phase 0 — DATA AUDIT: KAPALI** → `audit/reports/phase_0_summary.md`
  4 alan ölçüldü; 2 P0 bug (writer key mismatch, AGF tek-nokta) + bağlanmamış
  multi_source_validator bulundu.
- **Phase 1A — SHADOW validator integration: LIVE** → `audit/reports/validator_shadow_log.jsonl`
  Validator pipeline'da read-only gözlemliyor, karar vermiyor. Rapor:
  `python audit/03_validator_shadow_report.py [--days N]`
- **Phase 1A.5 — STORAGE + AGF HARDENING + CAPABILITY: COMPLETE**
  - Persistent storage: `event_store.py` + `migrations/m3_pipeline_events.sql`
    (MANUEL APPLY bekliyor — writer-bug + ephemeral /data bypass)
  - AGF: multi_source_validator cloudscraper'a yükseltildi; 403 kök neden IP-block
    (SO-5, Phase 4 proxy)
  - Bulgu: at-level consensus ZATEN var (`expert_consensus.build_consensus`), Phase 1A
    yanlış modülü (multi_source_validator) shadow'lamış. Detay: `phase_1b_plan_revised.md`
- **Phase 1B.1 — SHADOW REWIRE: COMPLETE** → shadow artık `expert_consensus`
  at-level consensus tüketiyor (multi_source_validator değil). consensus_top_pick DOLU.
  SO-6 fixed (agf fetch requests + brotli kaldırıldı, raw_count=2). yerli_engine
  shadow consensus sonrasına taşındı (read-only). `phase_1b1_*` raporları.
- **Phase 1E.0 — BET DIARY SCAFFOLDING: COMPLETE** → `bet_diary.py` (CLV/EV/Kelly +
  persistence) + `m4_bet_diary.sql`. CLV finansal-doğru log(odds_pred/odds_close).
- **Phase 1E.1 — PREDICTION WRITE: COMPLETE** → her altılı top-3/ayak → BetRecord
  (`bet_diary_writer.write_predictions_for_altili`, yerli_engine'de). did_we_bet=value_horses.
- **Phase 1E.2 — OUTCOME UPDATE: COMPLETE** → retro sonuçları → did_we_win + P&L
  (`update_outcomes_for_date`, retro.py'de). race_number=ayak eşleşmesi.
- **Phase 1E.3 — TRUE CLV: DEFERRED** → pre-race AGF fetch gerek; AGF 403 nedeniyle
  Phase 4 proxy'e bağımlı. `phase_1e3_clv_capture_plan.md`. Şu an clv=None.
- **Phase 1F — BET DIARY REPORT: COMPLETE** → `audit/04_bet_diary_report.py` (6 section).
  Veri birikince çalışır (şu an boş → "no data").
- **Phase 1B (kalan)** — confidence eşikleri kalibrasyonu: bet_diary'de n≥50 + 5+ gün
  birikince (migration apply sonrası) → Section 2/5 eşik tuning. Model birincil.
- **Phase 5.0 — ALTILI LOGIC AUDIT: COMPLETE** (salt-okuma, kod değişmedi) →
  `audit/reports/phase_5_*.md` (5 rapor) + `docs/PHASE_5_PLAN_ALTILI_REFACTOR.md`.
  Kritik bulgular: ÜÇ paralel kupon sistemi (V5.1 kupon.py + V7 + genis_smart, hepsi
  prod'da, kullanıcı 3 kupon görüyor); coverage/width KALİBRE-OLMAYAN model_prob'a dayalı
  (H1, en yüksek leverage); ~30 magic number gerekçesiz; Layer3 historical prior boş;
  V7 expand yapmıyor. 8 hipotez + backtest planı.
- **Phase 5.1 — MEASUREMENT LAYER: COMPLETE** (read-only, kod değişmedi) →
  `audit/reports/phase_5_1_*.md` + `simulation/`. Backfill = **SLOW track** (geçmiş AGF
  erişilemez → forward-only). Simulation engine + 3 strateji adaptörü hazır (replay smoke:
  3 sistem ~5x combo farkı, V7 en geniş, smart_genis canlı-state bağımlı). VALUE_THRESHOLD
  + bet_diary smoke PENDING (migration apply bekliyor).
- **Phase 5.2 — MODEL KALİBRASYONU: NEXT** (H1, en kritik). Gate: bet_diary verisi
  (migration apply + ~50-60 gün forward VEYA backfill alternatifi). isotonic/Platt →
  calibrated_prob; tüm coverage/width buna geçer. Plan: `docs/PHASE_5_2_TO_5_9_ROADMAP.md`.

## Production activation checklist (Berkay)
1. **Migration apply**: `phase_1a5_migration_apply_playbook.md` (m3 + m4, ~5 dk).
2. **Sonraki deploy**: pipeline otomatik bet_diary'ye yazar (her tahmin → write,
   her retro → outcome). Kod hazır, ek değişiklik gerekmez.
3. **~1 hafta sonra**: `python audit/04_bet_diary_report.py` → gerçek edge raporu.
4. **Phase 1B**: n≥50 birikince confidence threshold kalibrasyonu.
NOT: AGF prod 403 (SO-5) → prediction/retro AGF'si prod'da kırılgan; lokal IP çalışıyor.
- **Phase 1C (pending)** — low-confidence race flag/skip
- **Phase 1D (pending)** — calibration dataset generation
- **Phase 1E.1 (pending)** — bet_diary pipeline entegrasyonu (gerçek prediction kaydı)
- **Phase 2 (pending)** — kalibrasyon (Brier/ECE/reliability)
- **Phase 3 (pending)** — UI/Telegram format birleştirme + **writer bug fix** (P0)
- **Phase 4 (pending)** — foreign arb canlandırma (5 yabancı kaynak gri) + AGF proxy (SO-5)

Audit dizini: `audit/01_data_quality_report.py`, `audit/02_prod_db_audit.py`,
`audit/03_validator_shadow_report.py`. Kalıcı belgeler tracked, tarihli raporlar
+ shadow log gitignore'lu.

## Çalışma stili
- Önce plan, sonra kod. Plan onayı olmadan dosya yazma.
- Soru sor, varsayım yapma. Belirsizse dur, kullanıcıya danış.
- Yeni dosya `audit/` klasörü altında: `audit/01_*.py`, `audit/reports/*.md`
