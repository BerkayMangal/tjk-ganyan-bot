# SKEW ÖZETİ — ADIM 2

**Tarih:** 2026-06-02
**Test günü:** yarın (2026-06-03) entry'leri — henüz koşulmamış, gerçek "canlı" durum
**Ground truth:** 2026-05-31 (geçmiş, tamamen koşulmuş)

## ml_features tablosu — 471 kolon, sınıflandırma

| Sınıf | Kolon | Yorum |
|---|---|---|
| **PRE-RACE SAFE** (yarın ≥%95 dolu) | **88** | ID'leri çıkarınca ~78 anlamlı feature → training'e UYGUN |
| **POST-RACE ONLY** (yarın %0, geçmiş ≥%95) | **69** | Yarış sonrası doluyor → training'e ALMA (skew kaynağı) |
| **DEAD** (her zaman boş) | **52** | HAYALET kolonlar — Berkay'ın "52 hazır" listesi bunlar ❌ |
| PARTIAL (yarın 0<x<%95) | 262 | Güvenilmez, training'e alma |

## En önemli bulgu: "52 hazır feature" HAYALET

Berkay'ın bahsettiği "52 hazır feature" listesinin **çoğu hiç hesaplanmamış**. DEAD kolonlar:

```
jockey_total_races, jockey_win_rate, jockey_top3_rate
jockey_races_180d, jockey_win_rate_180d, jockey_top3_rate_180d
jockey_win_rate_track, jockey_win_rate_surface, jockey_win_rate_distance
trainer_total_races, trainer_win_rate, trainer_top3_rate
trainer_races_180d, trainer_win_rate_180d, trainer_top3_rate_180d
trainer_win_rate_track, trainer_win_rate_surface, trainer_win_rate_distance
jockey_trainer_races, jockey_trainer_win_rate
jockey_horse_races, jockey_horse_win_rate
... (+30 daha — toplam 52)
```

Hem geçmişte hem yarın için %0. Kolon var, değer YOK.

## POST-RACE ONLY (training'e ALMAYACAĞIM — SKEW önlemi)

Yarın için 0%, geçmiş için ≥%95 → yarış-sonrası rolling pipeline'ı dolduruyor:

```
finish_position, avg_finish_last1/3/5/10, best_finish_last5, worst_finish_last5
form_consistency, win_rate_all, top3_rate_all, total_races, races_last_365d
speed_last, avg_speed_last3/5, best_speed_last5
beaten_pct_last, avg_beaten_pct_last5
hf_days_since_last_race, hf_rest_category         ← Berkay'ın umduğu kolonlar, AMA POST-RACE
temperature, humidity, agf_rank, agf_value, odds
sec_speed_*, sec_pace_style, sec_finish_kick, sec_*_zscore  ← CURRENT race sectional, post-race
ma_prev1_finish_pos, ma_prev1_speed, ma_prev1_odds, ...
ma_jockey_last5_wins, ma_trainer_last5_avg_finish
```

## PRE-RACE SAFE (training'e ALACAĞIM — 78 anlamlı feature)

**Pedigree (22):** sire/dam x win_rate/top3_rate x turf/dirt x short/mid/long; sire_sire/dam_dam/sire_dam/dam_sire win rates

**Race attrs (14):** race_distance, distance_category, track_type, group_code, race_class_prize, field_size, hippodrome_id, weather_condition, track_condition, race_month, race_dow, season, race_number, ground_condition

**Horse (13):** horse_age, horse_gender, horse_breed, is_foreign, carried_weight, net_weight, handicap_value, weight_per_distance, gate_number, gate_position, horse_total_earnings, horse_avg_earnings, horse_earnings_last5

**Equipment (9):** has_blinkers, has_tongue_tie, has_ear_plugs, has_noseband, has_shadow_roll, equipment_count, has_blinkers_change, has_tongue_tie_change, equipment_change

**Status (4):** is_favorite, is_apprentice, rest_category, hippodrome_name

**Momentum türevleri (3):** horse_wr_momentum, jockey_wr_momentum, earnings_vs_field

**Encoded categoricals (13):** hippodrome_enc, track_type_enc, track_condition_enc, weather_condition_enc, group_code_enc, distance_category_enc, hf_rest_category_enc, sire_enc, dam_enc, jockey_enc, trainer_enc, sec_pace_style_enc, sec_prev1_pace_style_enc

**Train fitness (4):** train_n_14d, train_n_fast_work_14d, train_n_working_14d, train_has_fast_work_14d

## Karar

- **DEVAM ediyorum** — 78 pre-race feature yeterli (Berkay kuralı: "çok azsa dur" → 78 az değil)
- POST-RACE (69) + DEAD (52) + PARTIAL (262) hariç tutulur → strict skew-free
- horse_sectional_features tablosu **tamamen dışarda** (race_horse_id yok, sec_* zaten ml_features içinde)
- 07_dataset_pull.py bu kararla güncellendi → ml_features PRE-RACE 88 (ID'siz 78) + 96-base feature listesi birleştirilecek

## Yan ürün

- `audit/reports/skew_2026-06-02_prerace_whitelist.json` — 07 girdisi
- `audit/reports/skew_2026-06-02.md` — ham şema dump (ERR'li çünkü hsf join key bug; bilgi 07'de gerek değil)
