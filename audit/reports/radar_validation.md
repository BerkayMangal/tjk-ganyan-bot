# RADAR FLAG VALIDATION — Tarihsel hit-rate vs baseline

Top-5 modelinin AGF-implied'tan ayrıldığı atlar gerçekten daha sık top-5'te mi?
Test: 2025+ holdout (model/trained_targets/top5/).

**Lift** = flag verince top-5 hit-rate − baseline top-5 hit-rate.
Lift > 0 → flag bilgi taşıyor. Lift > 0.05 → güçlü sinyal.

| Breed | Threshold | N | HitRate | Baseline | Lift (pp) | Sig |
|---|---|---|---|---|---|---|
| arab | -0.05 | 29,680 | 40.2% | 48.6% | -8.45 | ✗ |
| arab | +0.00 | 27,584 | 39.2% | 48.6% | -9.44 | ✗ |
| arab | +0.05 | 25,017 | 39.5% | 48.6% | -9.10 | ✗ |
| arab | +0.10 | 21,768 | 40.6% | 48.6% | -8.09 | ✗ |
| arab | +0.15 | 18,511 | 41.8% | 48.6% | -6.80 | ✗ |
| arab | +0.20 | 15,459 | 43.4% | 48.6% | -5.28 | ✗ |
| arab | +0.30 | 10,003 | 48.2% | 48.6% | -0.45 | ✗ |
| arab | +0.40 | 5,803 | 54.1% | 48.6% | +5.41 | ✓✓ |
| english | -0.05 | 32,953 | 46.3% | 54.1% | -7.77 | ✗ |
| english | +0.00 | 30,553 | 44.6% | 54.1% | -9.47 | ✗ |
| english | +0.05 | 28,162 | 44.8% | 54.1% | -9.33 | ✗ |
| english | +0.10 | 25,201 | 45.3% | 54.1% | -8.74 | ✗ |
| english | +0.15 | 21,710 | 47.4% | 54.1% | -6.71 | ✗ |
| english | +0.20 | 18,462 | 49.2% | 54.1% | -4.85 | ✗ |
| english | +0.30 | 12,883 | 53.5% | 54.1% | -0.60 | ✗ |
| english | +0.40 | 8,004 | 61.8% | 54.1% | +7.76 | ✓✓ |

## Verdict

✓✓ **GÜÇLÜ SİNYAL** — 2 bantta lift > 5pp. Radar flag bilgi taşıyor.
