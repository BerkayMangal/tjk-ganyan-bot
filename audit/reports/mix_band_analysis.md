# Mix-Band Profile Analizi

6 ayağın combined skorlarına göre altılı profili.

## Profile dağılımı (median payout 12K, sabit varsayım)

| Profile | n | altılı_hit | mean_cost | ROI proxy |
|---|---|---|---|---|
| ALL_TIGHT | 2 | 50.00% | 800.00 TL | +659.8% |
| MIX_LIGHT | 92 | 38.04% | 1172.57 TL | +294.4% |
| MIX_BALANCED | 548 | 32.48% | 1884.68 TL | +109.5% |
| MIX_HEAVY | 192 | 21.35% | 3354.62 TL | -22.6% |
| ALL_WILD | 16 | 18.75% | 5751.25 TL | -60.4% |

## Adjusted ROI (profile-bazlı payout heuristic)

Heuristic: ALL_TIGHT 3K, MIX_LIGHT 8K, MIX_BALANCED 15K, MIX_HEAVY 40K, ALL_WILD 100K

| Profile | n | hit | adj_payout | cost | adj_ROI |
|---|---|---|---|---|---|
| ALL_TIGHT | 2 | 50.00% | 3,000 | 800.00 TL | +87.5% |
| MIX_LIGHT | 92 | 38.04% | 8,000 | 1172.57 TL | +159.6% |
| MIX_BALANCED | 548 | 32.48% | 15,000 | 1884.68 TL | +158.5% |
| MIX_HEAVY | 192 | 21.35% | 40,000 | 3354.62 TL | +154.6% |
| ALL_WILD | 16 | 18.75% | 100,000 | 5751.25 TL | +226.0% |
