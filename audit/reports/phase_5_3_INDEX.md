# Phase 5.3 — ÜÇTEN BİRE — INDEX

**KARAR: KEEP V5.1_dar (interim tek-kupon) / RETIRE V7 / DEFER smart_genis → v8. Güven ORTA.**

| PART | Rapor | Konu |
|---|---|---|
| A | [smart_genis_replay](phase_5_3_smart_genis_replay.md) | state-wrapper PASS (replay edilebilir) |
| B | [full_backtest](phase_5_3_full_backtest.md) | DAR sanity (%0=beklenen) + 3×2+baseline tablo |
| C | [kupon_behavior_analysis](phase_5_3_kupon_behavior_analysis.md) | width/TEK/divergence pattern |
| D | [flb_signal_validation](phase_5_3_flb_signal_validation.md) | favori-overbet DOĞRULANDI (Phase 5.5) |
| E | [decision](phase_5_3_decision.md) | karar + emeklilik planı + Phase 5.3.5 taslağı |
| F | [banner_update](phase_5_3_banner_update.md) | Telegram banner V5.1_DAR (prod, text-only) |
| G | [FINAL_REPORT](phase_5_3_FINAL_REPORT.md) | 14-maddelik bitiş |

## Yeni kod
- `simulation/snapshot_builder.py` — AGF complete.csv → prod-şekilli result snapshot (raw/calibrated)
- `simulation/run_backtest_phase53.py` — 3×2+baseline backtest (bootstrap CI, drawdown)
- `simulation/strategies/smart_genis_strategy.py` — dar-injection bridge (replay fix)
- `simulation/altili_simulator.py` — prob_field param (PART A öncesi)
- `dashboard/user_warnings.py` — banner V5.1_DAR (PART F)
- `audit/smoke_phase_5_3_banner.py` — banner smoke (7/7 PASS)

## Üç caveat (tüm sayıları çerçeveler)
1. payout = PROXY (gerçek TJK dividend yok) → mutlak ROI yorumlanamaz.
2. model_prob = AGF-fallback (value-edge yok) → strateji yapısı ölçülür, prod-edge değil.
3. n=122 → CI geniş. Karar cost+faithfulness'e dayalı, ROI'ye değil.
