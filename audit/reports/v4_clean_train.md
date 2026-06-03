# v4 Clean Train — dead _enc DROP + perf parity

v3 fc n=86 → v4 fc n=78 (drop 8)
Dropped (audit/41 SHAP %0-1): ['mf__sire_enc', 'mf__hippodrome_enc', 'mf__trainer_enc', 'mf__distance_category_enc', 'mf__weather_condition_enc', 'mf__track_condition_enc', 'mf__sec_pace_style_enc', 'mf__sec_prev1_pace_style_enc']

| Breed | Target | AUC_v3 | AUC_v4 | ΔAUC | Brier_v3 | Brier_v4 |
|---|---|---|---|---|---|---|
| arab | top1 | 0.6999 | 0.6999 | -0.0000 | 0.0841 | 0.0840 | ✓ |
| arab | top2 | 0.7087 | 0.7069 | -0.0018 | 0.1437 | 0.1439 | ✓ |
| arab | top3 | 0.7116 | 0.7143 | +0.0028 | 0.1845 | 0.1835 | ✓ |
| arab | top4 | 0.7218 | 0.7212 | -0.0006 | 0.2057 | 0.2061 | ✓ |
| arab | top5 | 0.7393 | 0.7397 | +0.0004 | 0.2078 | 0.2083 | ✓ |
| english | top1 | 0.7203 | 0.7233 | +0.0030 | 0.0908 | 0.0906 | ✓ |
| english | top2 | 0.7280 | 0.7282 | +0.0002 | 0.1511 | 0.1512 | ✓ |
| english | top3 | 0.7323 | 0.7331 | +0.0008 | 0.1880 | 0.1874 | ✓ |
| english | top4 | 0.7495 | 0.7497 | +0.0002 | 0.2015 | 0.2010 | ✓ |
| english | top5 | 0.7726 | 0.7727 | +0.0002 | 0.1944 | 0.1942 | ✓ |

**Max |ΔAUC| = 0.0030**. ✓ Perf esit — v4 e gec
