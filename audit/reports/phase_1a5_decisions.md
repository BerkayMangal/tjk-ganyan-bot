# Phase 1A.5 — Karar Logu

Otonom yürütme. Her PART sonunda kritik kararlar tek cümleyle.

## PART A — Persistent Event Storage
- **Storage seçimi:** Supabase `pipeline_events` (additive, generic event tablosu) —
  writer-bug ve ephemeral /data volume'dan bağımsız. (Railway volume / external PG elendi.)
- **Güvenli mod (Berkay onayı):** DB URL placeholder → prod'a DOKUNULMADI; SQL migration
  + event_store.py + dual-write kodu üretildi, lokal no-op test edildi, manuel apply notu.
- **İzolasyon:** `event_store.py` measurement_db.py'a dokunmuyor; fresh psycopg2 conn
  (pooling yok — basitlik), URL yoksa graceful no-op.
- **Dual-write:** shadow log artık hem JSONL (lokal) hem event_store (prod) — izole try/except.

## PART B — AGF 403 Hardening
- **Kök neden:** IP-based block (Railway datacenter IP), Cloudflare challenge DEĞİL.
  Lokal IP'den 4 yöntem de 200; prod 403. cloudscraper IP block'u çözmez (SO-5).
- **Workaround:** multi_source_validator 3 fetch → cloudscraper SESSION (fallback
  requests). agf_scraper'a DOKUNULMADI (zaten cloudscraper'lı). UA rotation eklenmedi
  (faydasız, SO-4).
- **agf_fetch event:** validate_sources artık write_event('agf_fetch') ile AGF erişim
  sağlığını (success/status/latency/method/n_altilis) event_store'a logluyor.
- **Yeni bulgu:** AGF fetch 200 ama parse raw_count=0 (h3 parse eski) → SO-6, C'de ele alındı.
