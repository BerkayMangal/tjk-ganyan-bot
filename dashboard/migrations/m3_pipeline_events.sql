-- ===========================================================================
-- PHASE 1A.5 — pipeline_events (persistent event storage)
-- Schema: m3.events.v1
-- ===========================================================================
--
-- ADDITIVE migration. Mevcut measurement_* tablolarına DOKUNMAZ.
-- Writer-bug'tan (kupon_dar vs dar) ve ephemeral /data volume'dan bağımsız,
-- yeni izole yazım yolu. Tüm pipeline olayları tek generic tabloya akar.
--
-- Apply:
--   psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m3_pipeline_events.sql
-- veya Supabase Dashboard → SQL Editor → paste → Run.
-- Idempotent (IF NOT EXISTS) — tekrar çalıştırmak güvenli.
--
-- Event types: kupon_generated, shadow_validation, retro_result, agf_fetch, pipeline_run
-- ===========================================================================

CREATE TABLE IF NOT EXISTS pipeline_events (
    id          BIGSERIAL PRIMARY KEY,
    timestamp   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    event_type  TEXT NOT NULL,
    event_date  DATE,
    hippodrome  TEXT,
    altili_no   INTEGER,
    payload     JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS idx_events_type_date
    ON pipeline_events (event_type, event_date);

CREATE INDEX IF NOT EXISTS idx_events_payload_gin
    ON pipeline_events USING GIN (payload);

-- Sanity:
-- SELECT event_type, COUNT(*) FROM pipeline_events GROUP BY 1 ORDER BY 2 DESC;
