# Phase 1A.5 — Storage Smoke (lokal no-op mod)

Tarih: 2026-05-23 | `TJK_MEASURE_DB_URL`: SET DEĞİL (güvenli mod)

## Test sonuçları
| # | Test | Sonuç | Beklenen | Durum |
|---|---|---|---|---|
| 1 | `event_store.is_enabled()` | False | False | ✅ |
| 2 | `write_event(...)` (URL yok) | False + WARNING | no-op | ✅ |
| 3 | `read_events(...)` (URL yok) | `[]` + WARNING | [] | ✅ |
| 4 | `log_shadow_result` dual-write | JSONL 2176→2722 (yazdı), event_store no-op | JSONL yazar, ES sessiz | ✅ |
| 5 | `_parse_altili_id` | `('2026-05-23','Bursa Hipodromu',1)` | (date,hippo,altili) | ✅ |

## Doğrulananlar
- `event_store` URL yokken **graceful no-op** — exception fırlatmıyor, WARNING basıyor.
- **Dual-write izole**: event_store no-op olsa bile JSONL yazımı çalışıyor; biri
  diğerini ya da pipeline'ı bloklamıyor.
- `py_compile` temiz (event_store.py 150 satır, source_consensus.py güncel).
- `measurement_db.py`'a dokunulmadı.

## Prod'da ne olacak (manuel apply sonrası)
Berkay `TJK_MEASURE_DB_URL` set edip `dashboard/migrations/m3_pipeline_events.sql`'i
uyguladığında:
- `is_enabled()` → True
- shadow validation her altılıda `pipeline_events`'e (`event_type='shadow_validation'`) yazılır
- writer-bug ve /data volume yokluğundan **bağımsız** kalıcı kayıt başlar
- Kod değişikliği GEREKMEZ — dual-write zaten yerinde, sadece URL + tablo.
