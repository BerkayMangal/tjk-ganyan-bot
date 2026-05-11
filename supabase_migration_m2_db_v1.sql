-- ===========================================================================
-- PATCH_M2_DB_v1 — TJK Ganyan Bot Measurement Schema
-- Schema version: m2.db.v1
-- ===========================================================================
--
-- Apply this migration to a fresh Supabase Postgres project.  All statements
-- are idempotent (IF NOT EXISTS), so re-running this is safe.
--
-- Apply via:
--   Supabase Dashboard → SQL Editor → paste this file → "Run"
-- or via psql:
--   psql "$TJK_MEASURE_DB_URL" < supabase_migration_m2_db_v1.sql
--
-- Tables:
--   measurement_pipeline_runs   — one row per scheduled (or manual) run
--   measurement_kupons          — one row per kupon (bot or manual)
--   measurement_results         — one row per race result
--   measurement_matches         — one row per kupon × result evaluation (M3)
--
-- All tables include raw_json jsonb so schema migrations don't lose history.
-- ===========================================================================


-- ---------------------------------------------------------------------------
-- measurement_pipeline_runs
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS measurement_pipeline_runs (
    run_id           TEXT PRIMARY KEY,
    schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
    started_at       TIMESTAMPTZ NOT NULL,
    finished_at      TIMESTAMPTZ,
    duration_sec     DOUBLE PRECISION,
    status           TEXT NOT NULL,
    trigger          TEXT NOT NULL,
    telegram_sent    BOOLEAN,
    kupon_count      INTEGER DEFAULT 0,
    hippodromes      TEXT[] DEFAULT ARRAY[]::TEXT[],
    warnings         JSONB DEFAULT '[]'::JSONB,
    errors           JSONB DEFAULT '[]'::JSONB,
    error_traceback  TEXT,
    env              TEXT,
    git_sha          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS ix_pipeline_runs_started_at
    ON measurement_pipeline_runs (started_at DESC);


-- ---------------------------------------------------------------------------
-- measurement_kupons
--
-- kupon_id format:
--   {date}_{hippo_normalized}_{altili_no}_{source}_{mode}_{kupon_type}
--   manual variant: ..._manual_{kupon_type}_{seq_3digit}
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS measurement_kupons (
    kupon_id         TEXT PRIMARY KEY,
    schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
    run_id           TEXT,
    source           TEXT NOT NULL,
    trigger          TEXT,
    record_status    TEXT NOT NULL DEFAULT 'active',
    date             DATE NOT NULL,
    hippodrome       TEXT NOT NULL,
    altili_no        INTEGER NOT NULL,
    mode             TEXT,
    kupon_type       TEXT NOT NULL,
    race_numbers     INTEGER[] DEFAULT ARRAY[]::INTEGER[],
    cost             DOUBLE PRECISION,
    combo            INTEGER,
    n_singles        INTEGER,
    data_quality     JSONB DEFAULT '{}'::JSONB,
    selections       JSONB DEFAULT '{}'::JSONB,
    v7_meta          JSONB DEFAULT '{}'::JSONB,
    telegram_sent    BOOLEAN,
    telegram_msg_id  TEXT,
    env              TEXT,
    git_sha          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS ix_kupons_date
    ON measurement_kupons (date DESC);
CREATE INDEX IF NOT EXISTS ix_kupons_date_hippo
    ON measurement_kupons (date, hippodrome);
CREATE INDEX IF NOT EXISTS ix_kupons_run_id
    ON measurement_kupons (run_id);
CREATE INDEX IF NOT EXISTS ix_kupons_source
    ON measurement_kupons (source);


-- ---------------------------------------------------------------------------
-- measurement_results
--
-- result_id is a natural composite-ish string, e.g.
--   2026-05-11_bursa_race_3
-- but we don't enforce that format — the natural unique constraint is
-- (date, hippodrome, race_number) via ux_results_natural.
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS measurement_results (
    result_id        TEXT PRIMARY KEY,
    schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
    run_id           TEXT,
    date             DATE NOT NULL,
    hippodrome       TEXT NOT NULL,
    race_number      INTEGER NOT NULL,
    winner_num       INTEGER,
    winner_name      TEXT,
    finishing_order  JSONB DEFAULT '[]'::JSONB,
    scratched        INTEGER[] DEFAULT ARRAY[]::INTEGER[],
    track_condition  TEXT,
    weather          TEXT,
    source           TEXT,
    env              TEXT,
    git_sha          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS ix_results_date
    ON measurement_results (date DESC);

CREATE UNIQUE INDEX IF NOT EXISTS ux_results_natural
    ON measurement_results (date, hippodrome, race_number);


-- ---------------------------------------------------------------------------
-- measurement_matches  (populated in M3, schema fixed now to avoid migration)
-- ---------------------------------------------------------------------------
CREATE TABLE IF NOT EXISTS measurement_matches (
    match_id         TEXT PRIMARY KEY,
    schema_version   TEXT NOT NULL DEFAULT 'm2.db.v1',
    run_id           TEXT,
    kupon_id         TEXT NOT NULL,
    date             DATE NOT NULL,
    hippodrome       TEXT NOT NULL,
    altili_no        INTEGER NOT NULL,
    total_hits       INTEGER DEFAULT 0,
    kupon_won_full   BOOLEAN DEFAULT FALSE,
    won_partial_5    BOOLEAN DEFAULT FALSE,
    won_partial_4    BOOLEAN DEFAULT FALSE,
    n_unresolved     INTEGER DEFAULT 0,
    leg_results      JSONB DEFAULT '[]'::JSONB,
    calibration      JSONB DEFAULT '{}'::JSONB,
    evaluated_at     TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    source           TEXT,
    env              TEXT,
    git_sha          TEXT,
    created_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at       TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    raw_json         JSONB NOT NULL DEFAULT '{}'::JSONB
);

CREATE INDEX IF NOT EXISTS ix_matches_date
    ON measurement_matches (date DESC);
CREATE INDEX IF NOT EXISTS ix_matches_kupon_id
    ON measurement_matches (kupon_id);


-- ---------------------------------------------------------------------------
-- Sanity: list the tables created.  Comment out if running via psql -f.
-- ---------------------------------------------------------------------------
-- SELECT tablename FROM pg_tables WHERE tablename LIKE 'measurement_%' ORDER BY 1;
