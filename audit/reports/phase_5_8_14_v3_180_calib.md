# Phase 5.8.14 — V3 NEW (180) Calibration Fit (isotonic + beta)

_Tarih: 2026-06-15T09:19:15.259621Z_

Val: 2025-01..06 (calibration fit) | Final: 2025-07+ (kıyas)

### ARAB (cal=14,559, final=27,441)

| Method | AUC | Brier | ECE | LogLoss |
|---|---|---|---|---|
| raw      | 0.7244 | 0.0829 | 0.0114 | 0.2910 |
| isotonic | 0.7229 | 0.0830 | 0.0100 | 0.2934 |
| beta     | 0.7244 | 0.0828 | 0.0087 | 0.2905 |

**BEST: `beta`** (ECE+Brier combined)

### ENGLISH (cal=15,839, final=29,734)

| Method | AUC | Brier | ECE | LogLoss |
|---|---|---|---|---|
| raw      | 0.7340 | 0.0907 | 0.0082 | 0.3100 |
| isotonic | 0.7336 | 0.0910 | 0.0096 | 0.3127 |
| beta     | 0.7340 | 0.0908 | 0.0087 | 0.3100 |

**BEST: `raw`** (ECE+Brier combined)

