# Phase 5.8.27 — Race-Relative Features (rr__)
_Tarih: 2026-06-15T15:03:59.318882Z_  ·  _Kaynak: races_v6.csv (245K satır)_

## Eklenen 15 feature


### RANK (7)

- `rr__career_top4_rate_rank` ← cf__career_top4_rate
- `rr__career_top3_rate_rank` ← cf__career_top3_rate
- `rr__career_avg_finish_rank` ← cf__career_avg_finish
- `rr__jockey_cond_top4_rank` ← mf__jockey_cond_top4
- `rr__career_recent5_top4_rank` ← cf__career_recent5_top4_rate
- `rr__same_dist_top3_rate_rank` ← cf__same_dist_top3_rate
- `rr__agf_rank` ← agf_pct

### ZSCORE (3)

- `rr__career_top4_rate_zscore` ← cf__career_top4_rate
- `rr__career_top3_rate_zscore` ← cf__career_top3_rate
- `rr__jockey_cond_top4_zscore` ← mf__jockey_cond_top4

### GAP-from-top1 (3)

- `rr__career_top4_rate_gap_top1` ← cf__career_top4_rate
- `rr__agf_gap_top1` ← agf_pct
- `rr__career_recent5_top4_gap_top1` ← cf__career_recent5_top4_rate

### ABOVE-FIELD-MEAN (2)

- `rr__career_top4_above_field_mean` ← cf__career_top4_rate
- `rr__jockey_cond_above_field_mean` ← mf__jockey_cond_top4

## Output

- `data/training_v7/races_v7.csv` (272 MB, 225 feature)
