# HK Benter Feasibility Backtest (eprochasson schema)

**Veri:** eprochasson/horserace_data — HK perf 2007-2018, dividends parse
**Train:** <race-level 60/40 (train ends 2017-11-01, test starts 2017-11-01) (11,071 rows) · **Test:** ≥race-level 60/40 (train ends 2017-11-01, test starts 2017-11-01) (7,370 rows)
**Features:** 22 strictly-prior
**Model:** XGB+LGBM ensemble + isotonic
**Takeout HK:** ~%17.5 (win), ~%17.5 (place)

## ROI Backtest

| Strateji | n_bets | hit% | ROI | CI 95% | sig |
|---|---|---|---|---|---|
| WIN_model | 1,186 | 12.4% | -30.54% | [-46.86, -12.29] | ✗ |
| WIN_public | 604 | 29.0% | -22.38% | [-32.48, -11.80] | ✗ |
| WIN_random | 604 | 7.9% | -21.47% | [-53.93, +21.48] | marjinal |
| PLACE_model | 2,612 | 37.9% | -15.57% | [-20.40, -10.41] | ✗ |
| PLACE_public | 604 | 60.9% | -15.71% | [-20.84, -10.19] | ✗ |
| PLACE_random | 604 | 27.3% | -11.09% | [-26.87, +7.56] | marjinal |

## Sanity Gates

- **Gate A** (Random ROI < 0, takeout): ✓ PASS
- **Gate B** (Public ≈ −takeout): ✓ PASS
- **Gate C** (Model ROI > 0 + > Public, CI > 0): ✗ FAIL

## VERDICT

✗ Model edge yok — public/random sane ama Model takeout'u geçemiyor. Parimütüel ölü, exchange tek umut.
