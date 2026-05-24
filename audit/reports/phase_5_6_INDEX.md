# Phase 5.6 — 9-LAYER + 3 STRATEJİ ROUTER + KALİBRASYON — INDEX

**Sistem bot DEĞİL — Berkay karar verici. Prod değişmez (env off). payout=PROXY, model_prob=AGF-fallback.**

| PART | Rapor | Konu |
|---|---|---|
| 1 | [carryover_detection](phase_5_6_carryover_detection.md) | L1 — manuel env (oto-tespit viyabil değil) |
| 2 | [l2_l3_design](phase_5_6_l2_l3_design.md) | L2 surprise (entropy) + L3 Benter (collinear caveat) |
| 3 | [layer_integration](phase_5_6_layer_integration.md) | L4-L8 aggregator, çift-sayım önlendi |
| 4 | [v9_profile_sanity](phase_5_6_v9_profile_sanity.md) | 5 senaryo (prob vs value) |
| 5 | [strategy_router_design](phase_5_6_strategy_router_design.md) | Kangal>FY>TamSistem>Pas (veri-türevli) |
| 6 | [kupon_builders](phase_5_6_kupon_builders.md) | 3 builder + mock gallery |
| 7 | [shadow_integration](phase_5_6_shadow_integration.md) | PATCH_5_6_V9_SHADOW (env off, Telegram dokunulmaz) |
| 8 | [v9_backtest](phase_5_6_v9_backtest.md) | V9≈V5.1; ablation L4+L5+/L6− |
| 9 | weekly_calibration_report.py + 2026-W21.md | sinyal doğrulama döngüsü |
| 10 | audit/cli/log_play.py + README | Berkay feedback protokolü |
| 11 | [FINAL_REPORT](phase_5_6_FINAL_REPORT.md) | bitiş + kademeli aktivasyon |

## Yeni kod
`simulation/v9/` (carryover_detector, surprise_layer, benter_combiner, layer_aggregator,
strategy_router, pipeline, builders/, backtest_v9), `dashboard/calibration_loader.py` (get_v9_pipeline),
`dashboard/yerli_engine.py` (PATCH_5_6_V9_SHADOW), `audit/weekly_calibration_report.py`,
`audit/cli/log_play.py`, `audit/smoke_phase_5_6_v9_shadow.py`.

## Tek cümle
9-layer altyapı + 3 strateji router shadow'da kuruldu; backtest V9'u V5.1'den ayırt edemedi (n
küçük, proxy) ama ablation L4(FLB)+L5(skill)'i value çekirdek olarak işaret etti; karar 4-hafta
gözlem + Berkay'a bırakıldı (sistem bot değil).
