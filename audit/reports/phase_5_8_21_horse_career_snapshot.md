# Phase 5.8.21 — Horse Career Stats Snapshot
_Tarih: 2026-06-15T10:58:04.286506Z_

## Özet

- Unique horses: **17,975**
- Data tarih aralığı: 2021-04-04 → 2026-06-02
- JSON boyut: 8.0 MB
- Format: `{horse_name: career_stats}`

## Field'lar (per horse)

- `career_n_races`, `career_win_rate`, `career_top3_rate`, `career_top4_rate`
- `career_avg_finish`, `career_recent5_top3/4`, `career_recent10_top3/4`
- `career_days_since_top3`, `same_dist_top3_rate`, `same_track_top3_rate`
- `top3_streak`, `below_streak`
- `last_race_date`, `last_finish_position`

## Sonraki adım

audit/107: yerli_engine.py'a prod-time feature compute. Her at için:
1. `horse_career_stats.json` lookup → cf__ feature'lar
2. Yarış-bazlı (rc__) inline hesap (field_size, agf entropy vs)
3. Interactions (ix__) cf + agf'den compute
4. Polynomials (pf__) agf'den compute
5. V6 model (210 feature) prediction
