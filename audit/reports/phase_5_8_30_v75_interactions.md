# Phase 5.8.30 — V7.5 Interaction Layer (ix2__)
_Tarih: 2026-06-16T06:26:11.538994Z_

## 10 yeni 2nd-order interaction

- `ix2__career_top4_x_zscore` ← `cf__career_top4_rate` × `rr__career_top4_rate_zscore`
- `ix2__career_top3_x_rank` ← `cf__career_top3_rate` × `rr__career_top3_rate_rank`
- `ix2__recent5_top4_x_rank` ← `cf__career_recent5_top4_rate` × `rr__career_recent5_top4_rank`
- `ix2__career_x_jockey_cond` ← `cf__career_top4_rate` × `mf__jockey_cond_top4`
- `ix2__recent5_x_jockey_cond` ← `cf__career_recent5_top4_rate` × `mf__jockey_cond_top4`
- `ix2__agf_x_career_top4` ← `agf_pct` × `cf__career_top4_rate`
- `ix2__agf_x_career_top3` ← `agf_pct` × `cf__career_top3_rate`
- `ix2__field_size_x_career_top4` ← `rc__field_size_class` × `cf__career_top4_rate`
- `ix2__recent_x_avg_finish` ← `cf__career_recent5_top4_rate` × `cf__career_avg_finish`
- `ix2__career_rank_x_agf` ← `rr__career_top4_rate_rank` × `agf_pct`

## Output

- `data/training_v7_5/races_v7_5.csv` (297 MB, 235 feature)
