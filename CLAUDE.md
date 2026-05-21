# TJK Ganyan Bot — Claude Code Briefing

## Ne yapıyor
Türk at yarışı 6'lı ganyan tahmin botu. AGF (piyasa) + TJK bülten (form/jokey) →
96 feature → XGB+LGBM ensemble (Arab/İngiliz breed-split) → DAR + GENİŞ kupon →
Telegram + Railway dashboard. Bonus: Ganyan Value Bot (model > piyasa) ayrı alarm.

## ÖNEMLİ: Mimari uyarısı
İki paralel pipeline VAR ama prod'da SADECE `dashboard/yerli_engine.py` çalışıyor.
- `main.py`, `engine/kupon.py`, `engine/commentary.py` → LEGACY, prod'da koşmuyor
- `dashboard/yerli_engine.py` (5656 satır) → ASIL prod motor, scheduler buradan
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

## Şu an Phase 0'dayız: DATA AUDIT
Tek hedef: hangi veri kaynağı ne kadar güvenilir, model gerçekte hangi feature'larla
karar veriyor, kalibrasyon var mı yok mu. Kod düzenleme YOK, ölçüm var.

## Çalışma stili
- Önce plan, sonra kod. Plan onayı olmadan dosya yazma.
- Soru sor, varsayım yapma. Belirsizse dur, kullanıcıya danış.
- Yeni dosya `audit/` klasörü altında: `audit/01_*.py`, `audit/reports/*.md`
