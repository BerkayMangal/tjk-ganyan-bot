# Phase 5.8.18 — V6 Feature Engineering (180 → 210)
_Tarih: 2026-06-15T10:32:03.697948Z_  ·  _Kaynak: races_v5.csv (245K satır)_

## Eklenen 30 feature


### cf__ (14) — CAREER HISTORY (atın geçmiş yarış istatistikleri, shift(1) leak-free)

- `cf__career_n_races`
- `cf__career_win_rate`
- `cf__career_top3_rate`
- `cf__career_top4_rate`
- `cf__career_avg_finish`
- `cf__career_recent5_top3_rate`
- `cf__career_recent5_top4_rate`
- `cf__career_recent10_top3_rate`
- `cf__career_recent10_top4_rate`
- `cf__career_days_since_top3`
- `cf__top3_streak`
- `cf__below_streak`
- `cf__same_dist_top3_rate`
- `cf__same_track_top3_rate`

### rc__ (7) — RACE-CONTEXT (yarış-bazlı agregat: field size, agf dağılım)

- `rc__field_size_class`
- `rc__top1_agf`
- `rc__agf_entropy`
- `rc__top1_top2_agf_gap`
- `rc__top3_agf_share`
- `rc__field_avg_age`
- `rc__field_avg_weight`

### ix__ (6) — INTERACTIONS (cross terms)

- `ix__jockey_cond_x_top1agf`
- `ix__agf_x_jockey_cond_top4`
- `ix__cond_n_x_career_top3`
- `ix__breed_arap_x_distance`
- `ix__agf_x_distance`
- `ix__jockey_cond_x_career_top3`

### pf__ (3) — POLYNOMIAL (squared)

- `pf__agf_sq`
- `pf__jockey_cond_top4_sq`
- `pf__career_top3_rate_sq`

## Sonraki adım (C)

`audit/104_train_v6.py` — 210 feature ile V6 retrain, cutoff=2025-05-24, V3 NEW_FULL ile paired karşılaştırma → top3/top4 hit ratio kazanım ölçümü.
