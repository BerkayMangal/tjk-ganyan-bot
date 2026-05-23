# Phase 5.2.5 — INDEX

**KILIT TUR sonucu: 🟢 OUTCOME BULUNDU → Phase 5.2 kalibrasyon engeli kalktı.**

| # | Rapor | Konu |
|---|---|---|
| A | [outcome_source_hunt](phase_5_2_5_outcome_source_hunt.md) | TJK Sehir statik HTML (page-driven Era) = HIZLI YOL |
| B | (kod) `simulation/backfill_outcomes.py` | 30/30 gün outcome (S=1 kazanan + at_no seti) |
| C | [calibration_fit_report](phase_5_2_5_calibration_fit_report.md) | join %100 + ilk gerçek fit (AGF→outcome) |
| D | [backtest_agf_report](phase_5_2_5_backtest_agf_report.md) | DAR altılı %0, coverage, FLB sinyali |
| E | [FINAL_REPORT](phase_5_2_5_FINAL_REPORT.md) | özet + dürüstlük + Phase 5.3 geçiş |

## Yeni kod
- `simulation/backfill_outcomes.py` — TJK Sehir outcome scraper (politeness 2s)
- `simulation/join_outcomes.py` — ayak↔koşu at-seti Jaccard join → won_flag
- `simulation/fit_calibrator.py` — walk-forward isotonic/platt fit (AGF→outcome)
- `simulation/backtest_agf.py` — coverage + altılı-hit + reliability
- `simulation/altili_simulator.py` — `prob_field` param (forward)
- `simulation/calibrators/fitted/agf_outcome_calibrator.pkl` — fit artifact

## Tek cümle
AGF/piyasa kalibrasyonu GERÇEKTEN fit edildi (ECE -%40); model kalibrasyonu (active.pkl)
forward bekliyor — sahte model-kalibratörü üretilmedi.
