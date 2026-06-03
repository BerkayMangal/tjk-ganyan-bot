# Radar Eşik Sweep — divergence threshold lift validation

Form-served model (audit İŞ1) + exact AGF Harville baseline (audit İŞ2).
Test set 2025+ (n=87,573).
Baseline: top-3 hit-rate 31.0%, top-4 41.3%.

| Target | Threshold | N flagged | Hit rate flagged | Hit non-flag | Lift (pp) |
|---|---|---|---|---|---|
| top3 | 0.05 | 33,954 | 22.50% | 36.35% | -13.85 ✗ |
| top3 | 0.10 | 23,328 | 25.05% | 33.14% | -8.09 ✗ |
| top3 | 0.15 | 15,674 | 28.18% | 31.59% | -3.41 ✗ |
| top3 | 0.20 | 10,985 | 31.68% | 30.88% | +0.80 ~ |
| top3 | 0.25 | 7,790 | 35.98% | 30.49% | +5.49 ✓✓ STRONG |
| top3 | 0.30 | 5,160 | 41.26% | 30.34% | +10.92 ✓✓ STRONG |
| top3 | 0.40 | 2,683 | 52.14% | 30.31% | +21.83 ✓✓ STRONG |
| top4 | 0.05 | 34,515 | 29.60% | 48.91% | -19.31 ✗ |
| top4 | 0.10 | 25,689 | 31.85% | 45.22% | -13.37 ✗ |
| top4 | 0.15 | 19,014 | 34.66% | 43.14% | -8.48 ✗ |
| top4 | 0.20 | 13,741 | 38.08% | 41.90% | -3.82 ✗ |
| top4 | 0.25 | 10,094 | 41.97% | 41.21% | +0.76 ~ |
| top4 | 0.30 | 7,697 | 46.17% | 40.83% | +5.35 ✓✓ STRONG |
| top4 | 0.40 | 4,569 | 56.20% | 40.48% | +15.73 ✓✓ STRONG |

## Best Threshold (target başına lift maximizing)

- **top3**: best threshold = **0.40** (lift +21.83pp, n_flagged 2,683)
- **top4**: best threshold = **0.40** (lift +15.73pp, n_flagged 4,569)
