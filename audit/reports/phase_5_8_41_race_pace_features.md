# Phase 5.8.41 — V8b race-pace features (rp__)
_Tarih: 2026-06-18T08:51:33.608149Z_

V8b = V7 (225) + 10 rp__ pace features (=> 235).

## Eklenen features

- `rp__horse_sprint_top4_rate`
- `rp__horse_middle_top4_rate`
- `rp__horse_stayer_top4_rate`
- `rp__horse_optimal_dist`
- `rp__horse_recent3_top4_rate`
- `rp__horse_dist_freq`
- `rp__horse_n_distance_bands`
- `rp__race_dist_band`
- `rp__dist_match`
- `rp__field_dist_familiarity`

## Mantık

- Sprint <1400m, Middle 1400-1800m, Stayer >1800m
- Her at için walk-forward expanding window: bu satırın race_date'inden ÖNCEKİ koşular
- No-leakage: rate hesabı satır-include değil, satır-exclude
- optimal_dist: hit_rate max band (n≥2 olan)
- dist_match: at optimal == race band → 1

## Next

- audit/134 V8b train (paired vs V7)
- Beklenti: top4 +%1-3pp (yeni boyut, redundant olmamalı)
