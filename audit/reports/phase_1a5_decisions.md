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
