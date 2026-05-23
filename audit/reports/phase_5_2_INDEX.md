# Phase 5.2 — INDEX

Mod: read-only + shadow (1 prod dokunuş, no-op). Tüm raporlar.

| Rapor | Konu | Sonuç |
|---|---|---|
| `phase_5_2_backfill_pull_report.md` | AGF + sonuç backfill | AGF ✅ / sonuç ❌ BLOKE |
| `phase_5_2_dataset_join_report.md` | dataset + cross-check | Pearson 0.9996 ✅ (agftahmin=gerçek AGF) |
| `phase_5_2_model_replay_report.md` | replay path | FALLBACK (agf_implied) |
| `phase_5_2_calibration_analysis.md` | kalibrasyon fit | ⏸ BLOCKED (no outcome labels) |
| `phase_5_2_shadow_integration.md` | shadow prod | PATCH_5_2_CALIBRATION (no-op) |
| `phase_5_2_backtest_validation.md` | backtest | ⏸ BLOCKED (no model_prob+outcome) |
| `phase_5_2_FINAL_REPORT.md` | bitiş | — |

## Kod (yeni)
- `simulation/backfill_agf_external.py` (at-level) + `backfill_results.py` (retro wrap)
- `simulation/build_calibration_dataset.py` (+ cross_check) + `horse_matcher.py` + `model_replay.py`
- `dashboard/calibration_loader.py` (shadow loader)
- smoke: `smoke_phase_5_2_shadow.py`

## Kod (değişen)
- `dashboard/yerli_engine.py` — +9 satır shadow calibrated_prob (PATCH_5_2_CALIBRATION, no-op)

## En kritik sonuç
🟢 **agftahmin geçmiş AGF = gerçek TJK AGF (Pearson 0.9996)** — backfill kaynağı kanıtlı.
🔴 **Tarihsel outcome erişilemez** → kalibrasyon FIT + backtest forward'a (bet_diary). H1 açık.

## Berkay aksiyon (önem)
1. **Migration apply (m3+m4)** — bet_diary forward outcome → kalibrasyon kapısı (P0).
2. (karar) TJK JS-render outcome için Playwright/AJAX araştırması (FAST outcome alternatifi).
