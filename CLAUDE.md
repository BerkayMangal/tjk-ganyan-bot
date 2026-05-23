# TJK Ganyan Bot — Claude Code Briefing

## Ne yapıyor
Türk at yarışı 6'lı ganyan tahmin botu. AGF (piyasa) + TJK bülten (form/jokey) →
96 feature → XGB+LGBM ensemble (Arab/İngiliz breed-split) → DAR + GENİŞ kupon →
Telegram + Railway dashboard. Bonus: Ganyan Value Bot (model > piyasa) ayrı alarm.

## ÖNEMLİ: Mimari uyarısı
İki paralel pipeline VAR ama prod'da SADECE `dashboard/yerli_engine.py` çalışıyor.
- `main.py`, `engine/kupon.py`, `engine/commentary.py` → LEGACY, prod'da koşmuyor
- `dashboard/yerli_engine.py` (5656 satır) → ASIL prod motor, scheduler buradan
- `dashboard/source_consensus.py` → Phase 1A SHADOW validator wrapper (read-only,
  kupon kararını etkilemez; dual-write: JSONL + event_store)
- `dashboard/event_store.py` → Phase 1A.5 persistent storage (Supabase `pipeline_events`,
  writer-bug'tan bağımsız; URL yoksa graceful no-op)
- `dashboard/migrations/m3_pipeline_events.sql` → pipeline_events additive migration
  (MANUEL APPLY gerekli — Berkay TJK_MEASURE_DB_URL set edip uygulayınca aktif olur)
- AGF resilience: `multi_source_validator` + `agf_scraper` cloudscraper'lı (fallback
  requests). NOT: prod 403 IP-based block, cloudscraper çözmez → Phase 4 proxy (SO-5)
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
- **Phase 1B (REVISED)** — `audit/reports/phase_1b_plan_revised.md`. SENARYO A:
  shadow'u expert_consensus consensus field'ına bağla (consensus_top_pick artık var),
  confidence = all_agree/super_banko/consensus_count. Model birincil kalır.
- **Phase 1C (pending)** — low-confidence race flag/skip
- **Phase 1D (pending)** — calibration dataset generation
- **Phase 2 (pending)** — kalibrasyon (Brier/ECE/reliability)
- **Phase 3 (pending)** — UI/Telegram format birleştirme + **writer bug fix** (P0)
- **Phase 4 (pending)** — foreign arb canlandırma (5 yabancı kaynak gri)

Audit dizini: `audit/01_data_quality_report.py`, `audit/02_prod_db_audit.py`,
`audit/03_validator_shadow_report.py`. Kalıcı belgeler tracked, tarihli raporlar
+ shadow log gitignore'lu.

## Çalışma stili
- Önce plan, sonra kod. Plan onayı olmadan dosya yazma.
- Soru sor, varsayım yapma. Belirsizse dur, kullanıcıya danış.
- Yeni dosya `audit/` klasörü altında: `audit/01_*.py`, `audit/reports/*.md`
