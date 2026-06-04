# Bütçe Küçültme Backtest

**Median payout (audit/61):** 12,157 TL · ROI proxy formula = (hit_rate × median_payout − mean_cost) / mean_cost

| Variant | n | altılı_hit | mean_cost | total_cost | total_hits | ROI proxy |
|---|---|---|---|---|---|---|
| V0 baseline (audit/57) | 850 | 33.41% | 2,914.98 TL | 2,477,732 TL | 284 | +39.3% |
| V1 medium 1k-2k TL | 850 | 22.71% | 1,341.47 TL | 1,140,248 TL | 193 | +105.8% |
| V2 small 500-1k TL | 850 | 17.76% | 655.75 TL | 557,390 TL | 151 | +229.3% |
| V3 micro 200-400 TL | 850 | 12.71% | 270.16 TL | 229,636 TL | 108 | +471.8% |

## Verdict

En iyi ROI proxy: **V3 micro 200-400 TL** (hit %12.71, cost 270.16 TL)
