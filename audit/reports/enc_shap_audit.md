# _enc Feature SHAP Audit

trained_targets_v3 modelleri, test 2025+ sample n=3000.
Eşik: max SHAP across (breed×top3,top4) >= 1% → TUT, değilse DROP.

| _enc | arab_top3 | arab_top4 | english_top3 | english_top4 | Max % | Karar |
|---|---|---|---|---|---|---|
| mf__jockey_enc | 7.61% | 8.24% | 8.72% | 8.35% | 8.72% | ✓ TUT |
| mf__dam_enc | 2.21% | 2.83% | 2.79% | 2.61% | 2.83% | ✓ TUT |
| mf__hf_rest_category_enc | 2.10% | 1.98% | 1.10% | 0.90% | 2.10% | ✓ TUT |
| mf__group_code_enc | 0.84% | 1.63% | 0.34% | 0.42% | 1.63% | ✓ TUT |
| mf__track_type_enc | 0.39% | 0.59% | 0.97% | 1.06% | 1.06% | ✓ TUT |
| mf__sire_enc | 0.99% | 0.67% | 0.77% | 0.60% | 0.99% | ✗ DROP |
| mf__hippodrome_enc | 0.65% | 0.73% | 0.73% | 0.98% | 0.98% | ✗ DROP |
| mf__trainer_enc | 0.81% | 0.77% | 0.61% | 0.53% | 0.81% | ✗ DROP |
| mf__distance_category_enc | 0.24% | 0.23% | 0.27% | 0.28% | 0.28% | ✗ DROP |
| mf__weather_condition_enc | 0.10% | 0.10% | 0.19% | 0.14% | 0.19% | ✗ DROP |
| mf__track_condition_enc | 0.04% | 0.07% | 0.04% | 0.04% | 0.07% | ✗ DROP |
| mf__sec_pace_style_enc | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | ✗ DROP |
| mf__sec_prev1_pace_style_enc | 0.00% | 0.00% | 0.00% | 0.00% | 0.00% | ✗ DROP |

**Karar:** 5 TUT, 8 DROP

DROP adayları: ['mf__sire_enc', 'mf__hippodrome_enc', 'mf__trainer_enc', 'mf__distance_category_enc', 'mf__weather_condition_enc', 'mf__track_condition_enc', 'mf__sec_pace_style_enc', 'mf__sec_prev1_pace_style_enc']

KEEP (yüksek SHAP, encoder skew kabul — küçük integer drift ağaç model için marjinal): ['mf__jockey_enc', 'mf__dam_enc', 'mf__hf_rest_category_enc', 'mf__group_code_enc', 'mf__track_type_enc']
