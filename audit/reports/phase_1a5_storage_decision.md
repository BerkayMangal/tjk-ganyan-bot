# Phase 1A.5 — Persistent Storage Decision

## Problem
Phase 0 + 1A iki şeyi birlikte kanıtladı:
1. **Writer key mismatch** (`kupon_dar` vs `dar`) → `measurement_kupons` aylardır boş.
2. **Prod'da `/data` volume YOK** (`is_production_volume=false`) → JSONL yazımları
   her deploy'da SİLİNİR.

Sonuç: production'da hiçbir ölçüm/shadow verisi kalıcı değil. Phase 1A shadow log
(`validator_shadow_log.jsonl`) prod'da yazılsa bile deploy'da kaybolur. Phase 1B
karar mantığı için veri birikmesi gerekiyor — bu altyapı olmadan imkansız.

## Seçenekler

| Seçenek | Artı | Eksi | Karar |
|---|---|---|---|
| **Supabase yeni tablo (`pipeline_events`)** | Additive (mevcut tablolara dokunmaz), writer-bug'tan bağımsız, zaten Supabase var, JSONB esnek | DB URL gerekiyor | ✅ **SEÇİLDİ** |
| Railway volume mount | Basit JSONL devam | Vendor lock-in, manuel mount, deploy başına kayıp riski sürer | ❌ |
| External Postgres | Tam kontrol | Overkill, yeni servis/maliyet | ❌ |

## Önerilen: Supabase + `pipeline_events`

Tek, generic, append-only event tablosu. Tüm pipeline olayları buraya akar.
Writer bug'ı (kupon_dar) bu tabloyu ETKİLEMEZ — yeni, izole yazım yolu.

### Şema
```sql
CREATE TABLE pipeline_events (
  id          BIGSERIAL PRIMARY KEY,
  timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
  event_type  TEXT NOT NULL,
  event_date  DATE,
  hippodrome  TEXT,
  altili_no   INT,
  payload     JSONB NOT NULL
);
CREATE INDEX idx_events_type_date ON pipeline_events(event_type, event_date);
CREATE INDEX idx_events_payload_gin ON pipeline_events USING GIN(payload);
```

### Event types
`kupon_generated`, `shadow_validation`, `retro_result`, `agf_fetch`, `pipeline_run`

## Bu turdaki kapsam (güvenli mod — Berkay onayı)
- DB URL hâlâ placeholder → **prod'a DOKUNULMADI.**
- Üretilenler: migration SQL (`dashboard/migrations/m3_pipeline_events.sql`),
  writer modülü (`dashboard/event_store.py`), shadow dual-write entegrasyonu.
- `event_store` URL yoksa **graceful no-op + warning** (lokal dev OK).
- **Manuel apply gerekli:** Berkay `TJK_MEASURE_DB_URL` set edip migration'ı
  uyguladığında prod'da tablo oluşur, dual-write otomatik aktifleşir (kod hazır).

## measurement_db.py'a dokunulmadı
Yeni `event_store.py` tamamen izole. Mevcut DB katmanına ALTER/DROP yok, additive.
