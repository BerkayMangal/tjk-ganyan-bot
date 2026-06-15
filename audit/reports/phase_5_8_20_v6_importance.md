# Phase 5.8.20 — V6 Feature Importance (XGB native gain)
_Tarih: 2026-06-15T10:56:25.617723Z_  ·  _V6 (210 feature)_

## Prefix-bazlı kazanım (%) — Hangi feature grubu daha güçlü?

| Prefix | Arab | English |
|---|---|---|
| `cf__` | 13.4% | 15.7% |
| `ix__` | 9.4% | 8.9% |
| `mf__` | 59.9% | 57.1% |
| `pf__` | 7.7% | 7.9% |
| `rc__` | 9.5% | 10.4% |

## Top-30 individual feature (combined importance)

| Rank | Feature | Combined Gain |
|---|---|---|
| 1 | ⭐ `pf__agf_sq` | 104.4 |
| 2 | ⭐ `ix__agf_x_jockey_cond_top4` | 69.8 |
| 3 | ⭐ `rc__field_size_class` | 67.7 |
| 4 | · `mf__field_size` | 59.0 |
| 5 | · `mf__horse_gender` | 53.7 |
| 6 | ⭐ `ix__agf_x_distance` | 43.5 |
| 7 | ⭐ `cf__career_recent5_top4_rate` | 41.9 |
| 8 | ⭐ `pf__jockey_cond_top4_sq` | 39.0 |
| 9 | · `mf__jockey_cond_top4` | 36.3 |
| 10 | ⭐ `cf__career_days_since_top3` | 35.2 |
| 11 | · `mf__sec_pace_style_enc` | 33.5 |
| 12 | ⭐ `rc__top3_agf_share` | 32.1 |
| 13 | ⭐ `ix__jockey_cond_x_career_top3` | 30.6 |
| 14 | ⭐ `cf__career_avg_finish` | 29.8 |
| 15 | · `mf__race_number` | 28.7 |
| 16 | ⭐ `rc__top1_agf` | 24.1 |
| 17 | · `mf__gate_number` | 23.4 |
| 18 | · `mf__earnings_vs_field` | 22.4 |
| 19 | ⭐ `ix__jockey_cond_x_top1agf` | 21.8 |
| 20 | ⭐ `cf__same_track_top3_rate` | 21.6 |
| 21 | ⭐ `rc__top1_top2_agf_gap` | 21.5 |
| 22 | ⭐ `rc__agf_entropy` | 21.4 |
| 23 | · `mf__group_code_enc` | 21.4 |
| 24 | ⭐ `rc__field_avg_age` | 20.5 |
| 25 | ⭐ `cf__below_streak` | 20.3 |
| 26 | · `mf__race_class_prize` | 20.2 |
| 27 | ⭐ `cf__top3_streak` | 19.3 |
| 28 | ⭐ `cf__career_win_rate` | 18.4 |
| 29 | ⭐ `cf__career_top4_rate` | 18.2 |
| 30 | · `mf__jockey_cond_win` | 18.1 |

## YENİ 30 feature ranking (V6 katkısı)

| Rank | New Feature | Combined Gain |
|---|---|---|
| 1 | `pf__agf_sq` | 104.40 |
| 2 | `ix__agf_x_jockey_cond_top4` | 69.76 |
| 3 | `rc__field_size_class` | 67.73 |
| 4 | `ix__agf_x_distance` | 43.52 |
| 5 | `cf__career_recent5_top4_rate` | 41.90 |
| 6 | `pf__jockey_cond_top4_sq` | 39.03 |
| 7 | `cf__career_days_since_top3` | 35.19 |
| 8 | `rc__top3_agf_share` | 32.09 |
| 9 | `ix__jockey_cond_x_career_top3` | 30.56 |
| 10 | `cf__career_avg_finish` | 29.80 |
| 11 | `rc__top1_agf` | 24.10 |
| 12 | `ix__jockey_cond_x_top1agf` | 21.83 |
| 13 | `cf__same_track_top3_rate` | 21.60 |
| 14 | `rc__top1_top2_agf_gap` | 21.45 |
| 15 | `rc__agf_entropy` | 21.41 |
| 16 | `rc__field_avg_age` | 20.47 |
| 17 | `cf__below_streak` | 20.30 |
| 18 | `cf__top3_streak` | 19.30 |
| 19 | `cf__career_win_rate` | 18.38 |
| 20 | `cf__career_top4_rate` | 18.23 |
| 21 | `cf__career_recent5_top3_rate` | 17.92 |
| 22 | `cf__career_recent10_top4_rate` | 15.66 |
| 23 | `cf__career_n_races` | 15.66 |
| 24 | `cf__career_top3_rate` | 14.72 |
| 25 | `cf__career_recent10_top3_rate` | 14.25 |
| 26 | `ix__cond_n_x_career_top3` | 13.40 |
| 27 | `pf__career_top3_rate_sq` | 13.32 |
| 28 | `rc__field_avg_weight` | 13.21 |
| 29 | `cf__same_dist_top3_rate` | 12.16 |
| 30 | `ix__breed_arap_x_distance` | 5.25 |

## Ablation adayları (low gain < 5.0)

Bu feature'lar yeniden ölçülebilir veya drop edilebilir:

