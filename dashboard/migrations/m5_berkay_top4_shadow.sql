-- ===========================================================================
-- BERKAY BİLİMSEL DENEME TOP4 — shadow retro storage (OPTIONAL upgrade)
-- Schema: m5.berkay_top4_shadow.v1
-- ===========================================================================
--
-- Why this exists:
--   The default db_store path writes into the existing generic
--   `pipeline_events` table (event_type ∈ {berkay_top4_prediction,
--   berkay_top4_result}). That works without any migration. This file
--   adds STRONGLY-TYPED tables for users who want queryable columns and
--   uniqueness guarantees by prediction_id.
--
-- Apply (optional):
--   psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m5_berkay_top4_shadow.sql
--
-- ADDITIVE. Idempotent (IF NOT EXISTS). NEVER touches other tables.
-- ===========================================================================

CREATE TABLE IF NOT EXISTS berkay_top4_shadow_predictions (
    id                       BIGSERIAL PRIMARY KEY,
    prediction_id            TEXT UNIQUE NOT NULL,
    label                    TEXT NOT NULL DEFAULT 'BERKAY_BILIMSEL_DENEME_TOP4',
    race_id                  TEXT NOT NULL,
    race_label               TEXT,
    race_time                TEXT,
    hippodrome               TEXT,
    field_size               INTEGER,
    prediction_cutoff        TEXT,                  -- morning|T-15|T-5|T-3|latest
    model_version            TEXT,
    feature_snapshot_hash    TEXT,
    agf_snapshot_time        TIMESTAMPTZ,
    generated_at             TIMESTAMPTZ NOT NULL,
    confidence               TEXT,                  -- HIGH|MEDIUM|LOW|CHAOS|NO_BET
    variance                 TEXT,                  -- LOW|MEDIUM|HIGH
    recommended_mode         TEXT,                  -- NO_BET|SMALL|BALANCED|WIDE
    candidate_set_json       JSONB,
    small_ticket_json        JSONB,
    balanced_ticket_json     JSONB,
    wide_ticket_json         JSONB,
    horses_json              JSONB,
    bankers_json             JSONB,
    core_json                JSONB,
    spread_json              JSONB,
    chaos_json               JSONB,
    avoid_json               JSONB,
    no_bet_reason            TEXT,
    engine_status            TEXT,                  -- ok|fallback|error
    telegram_sent            BOOLEAN,
    telegram_send_error      TEXT,
    telegram_message_id      TEXT,
    retro_store_mode         TEXT,                  -- jsonl|db|both
    created_at               TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_berkay_top4_pred_race
    ON berkay_top4_shadow_predictions (race_id, prediction_cutoff);

CREATE INDEX IF NOT EXISTS idx_berkay_top4_pred_generated_at
    ON berkay_top4_shadow_predictions (generated_at DESC);

CREATE INDEX IF NOT EXISTS idx_berkay_top4_pred_hippo
    ON berkay_top4_shadow_predictions (hippodrome, generated_at DESC);

CREATE TABLE IF NOT EXISTS berkay_top4_shadow_results (
    id                          BIGSERIAL PRIMARY KEY,
    prediction_id               TEXT UNIQUE NOT NULL,
    race_id                     TEXT NOT NULL,
    race_label                  TEXT,
    finalized_at                TIMESTAMPTZ NOT NULL,
    finish_order_json           JSONB,
    top4_actual_json            JSONB,
    banker_survived             BOOLEAN,
    candidate_set_captured_top4 BOOLEAN,
    small_ticket_hit            BOOLEAN,
    balanced_ticket_hit         BOOLEAN,
    wide_ticket_hit             BOOLEAN,
    payouts_json                JSONB,
    notes_json                  JSONB,
    created_at                  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_berkay_top4_res_finalized
    ON berkay_top4_shadow_results (finalized_at DESC);

-- VERIFICATION (optional — run after apply):
--
-- SELECT COUNT(*) FROM berkay_top4_shadow_predictions
--   WHERE generated_at::date = CURRENT_DATE;
--
-- SELECT COUNT(*) FROM berkay_top4_shadow_results
--   WHERE finalized_at::date = CURRENT_DATE;
--
-- SELECT recommended_mode, COUNT(*)
--   FROM berkay_top4_shadow_predictions
--   WHERE generated_at::date = CURRENT_DATE
--   GROUP BY recommended_mode;
