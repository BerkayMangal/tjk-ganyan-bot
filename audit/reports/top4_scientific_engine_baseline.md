# Top-4 Scientific Engine — Baseline

Date: 2026-06-20
Branch: main
Reference commit: 1dfc8a6 (phase_5_8_57)
Author: scientific engine sprint (forecasting + risk management, NOT auto-bet)

## What exists today

- V7 LambdaRank ensemble (XGB + LGBM + CatBoost YetiRank), retrained
  with `ndcg@4` objective (Phase 5.8.45/50).
- `mp` softmax score = race-relative ranker strength, **not a
  probability**.
- Tier system: DIAMOND / ALTIN / PREMIUM / FIRSAT / SWEET-2 / HALÜSİN.
- Walk-forward audit numbers (Phase 5.8.x):
  - Model top1 horse enters top-4 ≈ 77.7%
  - Model top4 unordered set hit ≈ 14.55%
  - Ordered top-4 hit / payout heavily skewed.
- AGF (`agftablosu.com`) used as public consensus signal, with a live
  drift scanner (`dashboard/agf_live_scanner.py`).
- Multiple prod paths (yerli_engine, smart_coupon_service, sib_top4_service).

## What this sprint adds

A new `top4/` package + audit harness + tests + docs:

| Module                                  | Purpose                                          |
|-----------------------------------------|--------------------------------------------------|
| `top4/calibration.py`                   | Segment + isotonic calibration of `p_top{1..4}`  |
| `top4/candidate_sets.py`                | Candidate-set construction & coverage helpers    |
| `top4/roles.py`                         | BANKER/CORE/SPREAD/CHAOS/AVOID/NO_SIGNAL         |
| `top4/uncertainty.py`                   | HIGH/MEDIUM/LOW/CHAOS/NO_BET                     |
| `top4/no_bet_gate.py`                   | NO_BET decision                                  |
| `top4/ticket_builder.py`                | Ticket *proposal* (never bets)                   |
| `top4/simulation.py`                    | Plackett-Luce Monte-Carlo                        |
| `top4/agf_benchmark.py`                 | AGF vs model lift, safe term mapping             |
| `top4/ev.py`                            | Risk-adjusted EV (trimmed, bootstrap, drawdown)  |
| `top4/report.py`                        | Telegram renderer + banned-language detector     |
| `top4/pipeline.py`                      | End-to-end `forecast_race()` entry point         |
| `dashboard/top4_forward_logger.py`      | JSONL forward log                                |
| `audit/top4_leakage_audit.py`           | Heuristic leakage scan                           |
| `audit/run_top4_scientific_backtest.py` | Master backtest harness                          |
| `tests/test_top4_engine.py`             | 30+ safety tests                                 |
| `tests/test_top4_leakage_safety.py`     | Leakage invariants                               |

## What this sprint does NOT change

- The existing Telegram message (`send_telegram_simple` /
  `_get_telegram_messages`) is **unchanged**.
- V7 ensemble weights, tier thresholds, AGF scraper, retro flow — all
  untouched.
- `TJK_KUPON_MODE` default remains `v5_1_only`.
- `TJK_V9_LIVE` default remains `1`.
- `TJK_TOP4_SCIENTIFIC` default is **`0`** (engine dormant).

When the new flag is off, production behaves identically to commit
1dfc8a6. When on, additional shadow JSONL is written and (optionally)
the rendered forecast is available for downstream display.

## Tests run

```
python3 -m unittest tests.test_top4_engine tests.test_top4_leakage_safety
Ran 32 tests in 0.013s  OK
```

## Leakage audit headline

```
python3 audit/top4_leakage_audit.py
1018 matches, 44 production-path warnings, 974 eval-path info
```

The 44 warnings are concentrated in:
- `dashboard/insider_signals.py` — references to `agf_close` (legacy
  module; rename to `sharp_money_candidate` planned for Phase 5.8.58).
- `dashboard/yerli_engine.py` — `payout` references in retro/scoring
  blocks (post-race only; reviewed manually OK).
- `dashboard/prerace_logger.py`, `telegram_formatter_v9.py` — string
  templates containing the word `payout` (documentation strings, not
  features).

All warnings are flagged for review. Unit tests in
`tests/test_top4_leakage_safety.py` enforce the invariants the scan
cannot prove (no label fields consumed as features).

## Limitations

1. The fitted isotonic calibrator (`model/top4_calibration/active.pkl`)
   does not yet exist. The fallback rank-bucket prior is conservative
   and honest; it does NOT claim to beat V7. It exists so the layer
   does not block on a fitted model.
2. The forward log JSONL is empty in prod until `TJK_TOP4_SCIENTIFIC=1`
   is flipped and races accumulate.
3. The AGF benchmark requires backfilled `observed_top4` rows; if
   `data/backfill/outcomes/` is empty, the harness writes a smoke
   report and clearly labels it as such.
4. The ticket builder does not yet consume real payout distributions.
   `top4/ev.py` is wired but `compute()` requires a payouts list from
   the user; until then, the engine returns proposals, never EV claims.

## Honest delta

This sprint **does not** add a new alpha. It adds:

- a calibration framework (necessary for honest forward calibration);
- a no-bet gate (necessary because TR pari-mutuel is structurally -EV);
- a role/ticket layer (necessary to translate ranker output into
  honest coverage and stake guidance);
- a forward log (necessary to ever validate any future alpha claim);
- a banned-language detector (necessary to keep the user-facing
  message honest).

If, after two to four weeks of forward logging, the calibrated p_top4
materially beats raw `mp` on Brier / ECE, we earn the right to surface
it in the user message. Until then, dormant.
