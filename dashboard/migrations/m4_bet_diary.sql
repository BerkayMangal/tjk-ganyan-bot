-- ===========================================================================
-- PHASE 1E.0 — bet_diary (pro betçi günlüğü)
-- Schema: m4.betdiary.v1
-- ===========================================================================
--
-- ADDITIVE migration. Mevcut tablolara DOKUNMAZ. Idempotent (IF NOT EXISTS).
-- Her tahmin için karar-anı + kapanış + sonuç → CLV/EV/Kelly/P&L analizi.
--
-- Apply:
--   psql "$TJK_MEASURE_DB_URL" -f dashboard/migrations/m4_bet_diary.sql
-- ===========================================================================

CREATE TABLE IF NOT EXISTS bet_diary (
    id                      BIGSERIAL PRIMARY KEY,
    prediction_id           TEXT UNIQUE NOT NULL,
    predicted_at            TIMESTAMPTZ NOT NULL,
    race_starts_at          TIMESTAMPTZ,
    hippodrome              TEXT NOT NULL,
    altili_no               INTEGER,
    race_number             INTEGER NOT NULL,
    horse_number            INTEGER NOT NULL,
    horse_name              TEXT,
    model_prob              NUMERIC,
    model_prob_calibrated   NUMERIC,
    agf_pct_at_prediction   NUMERIC,
    agf_pct_at_close        NUMERIC,
    odds_at_prediction      NUMERIC,
    odds_at_close           NUMERIC,
    ev_at_prediction        NUMERIC,
    kelly_fraction          NUMERIC,
    flat_bet_size           NUMERIC,
    recommended_bet_size    NUMERIC,
    did_we_bet              BOOLEAN DEFAULT FALSE,
    bet_rationale           JSONB,
    confidence_grade        TEXT,
    consensus_snapshot      JSONB,
    actual_winner_number    INTEGER,
    did_we_win              BOOLEAN,
    payout                  NUMERIC,
    theoretical_pnl_flat    NUMERIC,
    theoretical_pnl_kelly   NUMERIC,
    notes                   TEXT,
    created_at              TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at              TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_bet_diary_hippo_date
    ON bet_diary (hippodrome, predicted_at);
CREATE INDEX IF NOT EXISTS idx_bet_diary_horse
    ON bet_diary (horse_number, race_number);
CREATE INDEX IF NOT EXISTS idx_bet_diary_outcome
    ON bet_diary (did_we_win) WHERE did_we_win IS NOT NULL;

-- Sanity:
-- SELECT confidence_grade, COUNT(*), AVG(theoretical_pnl_flat)
--   FROM bet_diary WHERE did_we_win IS NOT NULL GROUP BY 1;
