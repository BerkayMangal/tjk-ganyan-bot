# Live Forward Monitoring

When `TJK_TOP4_SCIENTIFIC=1`, the engine writes a JSONL forward log:

```
data/top4_forward/YYYY-MM-DD.jsonl              # forecasts
data/top4_forward/YYYY-MM-DD_outcomes.jsonl     # observed results
```

Each forecast record contains:

- `ts_utc` — wall-clock prediction timestamp.
- `race_label`
- `model_version` — e.g. `v7_ndcg4`.
- `feature_snapshot_hash` — 16-hex hash of the feature dict (proves
  feature provenance for later calibration audits).
- `agf_snapshot_ts` — timestamp of AGF snapshot consumed.
- `forecast` — full struct: calibrated rows, roles, uncertainty,
  decision, ticket proposal.

## Daily / weekly reports

Run `python3 audit/run_top4_scientific_backtest.py` to produce
`audit/reports/top4_scientific_master_report.md` plus a JSON summary.

The harness reports:

- top4 hit by tier / role / hipodrom / breed / field-size / class
- calibration drift (Brier per week)
- AGF drift signal performance
- no-bet avoided-loss estimate
- model-vs-AGF lift

If live performance degrades, the engine downgrades confidence; it
never silently becomes more aggressive.

## Data retention

JSONL forward logs are append-only and gitignored. Periodically rotate
into Supabase via `event_store.py` if needed (the schema is compatible).
