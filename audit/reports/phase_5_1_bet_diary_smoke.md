# Phase 5.1 — Bet Diary Smoke

## DURUM: ⏸ PENDING — migration apply gerekli

`event_store.is_enabled()` → **False** (`TJK_MEASURE_DB_URL` .env'de placeholder).
Supabase `pipeline_events` / `bet_diary` tablolarına erişilemiyor → smoke çalıştırılamadı.

## Engel
- DB URL set DEĞİL → event_store no-op modunda (lokal JSONL'e yazıyor, prod tablosu yok).
- m3 (pipeline_events) + m4 (bet_diary) migration'ları **henüz apply edilmemiş.**

## Berkay aksiyonu (playbook hazır)
`audit/reports/phase_1a5_migration_apply_playbook.md` (~5 dk):
1. Railway → `TJK_MEASURE_DB_URL` → lokal `.env`.
2. `psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m3_pipeline_events.sql`
3. `psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m4_bet_diary.sql`
4. Verification: `SELECT COUNT(*) FROM bet_diary;` (0 beklenir).

Apply sonrası bu smoke (yazılacak `audit/smoke_phase_5_1_bet_diary.py`) çalışır:
bugünün 1 altılısı için bet_diary_writer üzerinden ~18 kayıt (top-3×6) → SELECT doğrula.

## Bağımlılık
Phase 5.2 (kalibrasyon) için bet_diary verisi gerekiyor → bu PENDING, forward-collection'ın
(Phase 5.1 SLOW track) ön koşulu. Migration apply = Phase 5.2'nin kapısı.
