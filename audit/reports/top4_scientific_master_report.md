# Top-4 Scientific Engine — Master Backtest

Data source: **synthetic_smoke**
Races evaluated: 1

⚠ This run uses synthetic smoke data so headline numbers
are NOT a real backtest. Wire backfill outcomes to get real results.

## Candidate-set coverage by size

| size | n | full top4 | ≥3 of top4 | full% | ≥3% |
|---|---|---|---|---|---|
| 4 | 1 | 0 | 1 | 0.000 | 1.000 |
| 5 | 1 | 1 | 1 | 1.000 | 1.000 |
| 6 | 1 | 1 | 1 | 1.000 | 1.000 |
| 7 | 1 | 1 | 1 | 1.000 | 1.000 |
| 8 | 1 | 1 | 1 | 1.000 | 1.000 |
| 9 | 1 | 1 | 1 | 1.000 | 1.000 |
| 10 | 1 | 1 | 1 | 1.000 | 1.000 |

## AGF vs Model overall
- n_races: 1
- AGF top1-in-top4: 1.000
- Model top1-in-top4: 1.000
- Blended top1-in-top4: 1.000
- Model lift over AGF: +0.000

## Decision modes
- small: 1

## 10 questions (master rubric)

1. Did calibrated p_top4 improve over raw mp?  -> see calibration report
2. What set size is needed by segment?  -> coverage table above
3. Does banker-core-spread improve top4 ticket coverage?  -> see ticket report
4. Where does model beat AGF?  -> AGF benchmark per-segment
5. Where does AGF beat model?  -> AGF benchmark per-segment
6. Which races should be no-bet?  -> decisions table
7. Which ticket types are robustly positive?  -> EV report (data required)
8. Which EV claims are too skewed to trust?  -> EV report (data required)
9. What should go live?  -> deployment gates doc
10. What should remain offline?  -> deployment gates doc
