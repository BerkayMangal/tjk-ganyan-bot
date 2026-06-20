# Top-4 Leakage / Timestamp Audit

Heuristic scan; not a substitute for unit tests in
`tests/test_top4_leakage_safety.py`.

- Total matches: 1018
- Production-path warnings: 44
- Eval-path info: 974

## Production-path warnings

- `dashboard/telegram_formatter_v9.py:6` — `payout` — payout field — must be evaluation-only
- `dashboard/prerace_logger.py:5` — `payout` — payout field — must be evaluation-only
- `dashboard/prerace_logger.py:8` — `payout` — payout field — must be evaluation-only
- `dashboard/yerli_engine.py:2075` — `payout` — payout field — must be evaluation-only
- `dashboard/yerli_engine.py:2084` — `payout` — payout field — must be evaluation-only
- `dashboard/yerli_engine.py:2888` — `payout` — payout field — must be evaluation-only
- `dashboard/yerli_engine.py:4306` — `payout` — payout field — must be evaluation-only
- `dashboard/insider_signals.py:6` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:13` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:33` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:34` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:92` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:98` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:105` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:115` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:115` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:116` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:121` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:123` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:123` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:160` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/insider_signals.py:160` — `agf_close` — agf_close — must be timestamp-gated
- `dashboard/v3_live.py:7` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:332` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:351` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:356` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:361` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:383` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:386` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:407` — `finish_position` — finish_position referenced — must be label only
- `dashboard/v3_live.py:407` — `finish_position` — finish_position referenced — must be label only
- `dashboard/prerace_coupon_builder.py:308` — `payout` — payout field — must be evaluation-only
- `dashboard/prerace_coupon_builder.py:314` — `payout` — payout field — must be evaluation-only
- `dashboard/feature_pipeline.py:6` — `finish_position` — finish_position referenced — must be label only
- `dashboard/feature_pipeline.py:44` — `finish_position` — finish_position referenced — must be label only
- `dashboard/feature_pipeline.py:82` — `finish_position` — finish_position referenced — must be label only
- `dashboard/feature_pipeline.py:87` — `finish_position` — finish_position referenced — must be label only
- `dashboard/feature_pipeline.py:87` — `finish_position` — finish_position referenced — must be label only
- `dashboard/feature_pipeline.py:104` — `finish_position` — finish_position referenced — must be label only
- `train/retrain_v2.py:23` — `finish_position` — finish_position referenced — must be label only
- `train/retrain_v2.py:106` — `finish_position` — finish_position referenced — must be label only
- `train/retrain_v2.py:160` — `finish_position` — finish_position referenced — must be label only
- `train/retrain_v2.py:163` — `finish_position` — finish_position referenced — must be label only
- `train/retrain_v2.py:163` — `finish_position` — finish_position referenced — must be label only

## Eval/audit-path info (allowed)

_974 matches in audit/, tests/, simulation/, scrapers/, data/, etc._

## Mandatory invariants

1. `finish_position` never appears as a model feature input.
2. `payout_amount` is only consumed by EV / backtest modules.
3. AGF snapshots are timestamped and the pre-race builder must reject
   snapshots taken after `T-0` (post-off).
4. Walk-forward splits are chronological. No shuffled CV in train.
5. Forward logger writes `ts_utc` AND `feature_snapshot_hash`.

## Status

REVIEW REQUIRED
