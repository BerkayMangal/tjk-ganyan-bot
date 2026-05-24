# Phase 5.5 — FLB COMPENSATION — INDEX

**Sonuç: FLB compensator hazır + shadow (env OFF). Aktivasyon SHADOW (forward bekle). TR
public-bias: jokey-skill underbet en güçlü bulgu (Phase 5.8 value).**

| PART | Rapor | Konu |
|---|---|---|
| A | [scoring_flow_map](phase_5_5_scoring_flow_map.md) | build_kupon score→ranking, enjeksiyon noktası |
| B | [flb_function_design](phase_5_5_flb_function_design.md) | multiplier=clamp(winrate/agf), CV→isotonic, sanity |
| C | [shadow_integration](phase_5_5_shadow_integration.md) | PATCH_5_5 (build_kupon + loader + meta), env OFF |
| D | [backtest_compensation](phase_5_5_backtest_compensation.md) | raw vs comp, paired test, KISMI PASS |
| E | [tr_public_bias_analysis](phase_5_5_tr_public_bias_analysis.md) | H2-H6 (jokey/yaş/mesafe/recency) |
| F | [activation_decision](phase_5_5_activation_decision.md) | SHADOW (aktive değil) + rollback |
| G | [FINAL_REPORT](phase_5_5_FINAL_REPORT.md) | 12-maddelik bitiş |

## Yeni kod
- `simulation/calibrators/flb_compensator.py` + `fitted/flb_compensator.pkl`
- `simulation/fit_flb_compensator.py`, `backtest_flb_phase55.py`
- `simulation/backfill_outcomes_rich.py` (age/jockey/distance enrichment), `tr_bias_analysis.py`
- `dashboard/calibration_loader.py` (FLB loaders), `engine/kupon.py` (PATCH_5_5), `yerli_engine.py` (meta)
- `audit/smoke_phase_5_5_shadow.py`

## Üç caveat (her sayıyı çerçeveler)
1. payout = PROXY → ROI mutlak anlamsız (Wilcoxon yön güvenilir).
2. fallback rejimi (score≈agf) → prod (model_prob) farklı; FLB-multiply value-tilt (double-count riski).
3. n=122 (backtest) / n subset'lerde küçülür (bias testleri).

## Tek cümle
TR'nin tersine-FLB'si (favori overbet) için veri-türevli compensator kuruldu ve güvenle
shadow'a alındı; sinyal pozitif ama proxy+fallback nedeniyle aktivasyon forward'a ertelendi —
sahte ROI iddiası üretilmedi.
