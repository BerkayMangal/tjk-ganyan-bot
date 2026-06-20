# Calibration and Uncertainty

## `mp` is not a probability

The V7 ranker emits a race-relative softmax score (`mp`) intended for
*ordering*, not for calibration. Two horses with `mp=0.30` in different
races can have very different real top-4 probabilities. Telegram
output therefore must not say "this horse has a 30% chance".

## Calibrated probabilities

`top4.calibration.calibrate_race(rows)` produces `p_*_cal` values via:

1. Segment bucketing (field-size, breed, AGF bucket, model rank).
2. A fitted isotonic table (optional, `model/top4_calibration/active.pkl`).
3. A rank-bucket empirical prior (always available, conservative).

Outputs are monotone (`p_win ≤ p_top2 ≤ p_top3 ≤ p_top4`) and clamped
to `[ε, 1-ε]`. If win-probability mass across the race exceeds 1.25, a
uniform downscale is applied and the row is annotated `win_renormalized`.

## Reliability diagnostics

`audit/run_top4_scientific_backtest.py` computes:

- per-segment observed vs predicted top-4 rate
- Brier score per race
- log-loss for winners
- bootstrap CI for hit-rates

If no observed outcomes are available (live backfill missing in prod), the
harness emits a **smoke** report clearly labelled SMOKE.

## Uncertainty levels

`top4.uncertainty.evaluate` returns one of:

- `HIGH` — compact required set, strong top1 gap.
- `MEDIUM` — required set ≤ 5.
- `LOW` — required set ≤ 7.
- `CHAOS` — required set ≥ 9 or field ≥ 16.
- `NO_BET` — required set so large that any reasonable ticket would
  burn capital faster than the calibrated edge can compensate.

The no-bet gate (`top4.no_bet_gate.decide`) consumes uncertainty +
role distribution. CHAOS with zero BANKER → NO_BET. Weak structure
(0 BANKER, ≤1 CORE, required set ≥ 7) → NO_BET.
