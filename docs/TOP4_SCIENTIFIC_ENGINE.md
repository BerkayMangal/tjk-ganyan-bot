# TJK Top-4 Scientific Forecasting Engine

The `top4/` package is a *research and decision-support* layer that sits
**alongside** the existing V7 ranker. It does not replace the production
Telegram pipeline. It does not place bets. It does not promise profit.

## What it provides

- **Calibrated probabilities** (`top4/calibration.py`) — converts race-relative
  `mp` softmax scores into `p_win_cal`, `p_top2_cal`, `p_top3_cal`,
  `p_top4_cal` via segment buckets and (when fitted) isotonic regression.
  When no fitted calibrator is present, an honest rank-bucket empirical
  prior is used and the row is annotated `method="fallback_rank_prior"`.
- **Candidate-set construction** (`top4/candidate_sets.py`) — picks
  4..10 horses by `mp`, by `p_top4_cal`, or by a model/AGF blend.
  Reports required set size for an 80% coverage target.
- **Role assignment** (`top4/roles.py`) — `BANKER`, `CORE`, `SPREAD`,
  `CHAOS`, `AVOID`, `NO_SIGNAL`. BANKER requires *both* high calibrated
  probability AND model rank ≤ 2 AND market support. Uncertainty CHAOS
  forcibly downgrades all BANKER candidates.
- **Race uncertainty** (`top4/uncertainty.py`) — `HIGH / MEDIUM / LOW /
  CHAOS / NO_BET` derived from field size, required-set size, AGF
  entropy, model top1-top2 gap.
- **No-bet gate** (`top4/no_bet_gate.py`) — turns uncertainty + role
  distribution into `skip=True` / mode = small / balanced / wide.
- **Ticket proposal** (`top4/ticket_builder.py`) — never bets. Returns
  a structured proposal that downstream renderers display.
- **Plackett-Luce simulation** (`top4/simulation.py`) — Monte-Carlo for
  empirical P(top-k) and set-frequency tables. 2k iters default (prod),
  50k+ for offline audit.
- **AGF benchmark** (`top4/agf_benchmark.py`) — AGF-only vs model-only
  vs blended top1/top4 hit-rates. Safer term mapping (`insider →
  sharp_money_candidate`).
- **Risk-adjusted EV** (`top4/ev.py`) — trimmed mean, p5..p95, bootstrap
  CI, max drawdown estimate, risk-of-ruin proxy. Skew warning if median
  is far below mean.
- **User-facing renderer** (`top4/report.py`) — banned-language
  detector; never says "guaranteed", "kesin", "free money", "insider",
  "safe profit".
- **Forward logger** (`dashboard/top4_forward_logger.py`) — writes
  `data/top4_forward/YYYY-MM-DD.jsonl` with `ts_utc` and
  `feature_snapshot_hash`. Disabled when `TJK_TOP4_SCIENTIFIC != 1`.

## Default state

The feature flag is `TJK_TOP4_SCIENTIFIC`. Default value: `0`.
When `0`, the engine is dormant — production V7 / V5.1 / tier outputs
are unchanged.

The intent is to deploy the engine as a SHADOW first: log forecasts to
JSONL alongside the live Telegram message. After two to four weeks of
forward data, calibration is validated honestly and the engine can be
considered for the user-facing message.

## What it does NOT do

- It does not auto-place bets, generate auto-stake commands, or hit any
  TJK / Betfair endpoint.
- It does not relabel `mp` as a probability.
- It does not fabricate calibration when no fitted model exists; the
  fallback rank prior is clearly marked.
- It does not use any post-race data as a feature.
- It does not bypass the no-bet gate.
