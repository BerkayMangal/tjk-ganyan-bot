# Calibration Candidates — MANIFEST

Generated: 2026-06-13T06:23:22.339326Z

Phase 5.2.6 grid çıktısı. **Hiçbiri active değil** — Berkay karar verir, active.pkl yazılmadı.

| # | File | Method | Bucket | Brier | ECE | LL | MCE | Combined | n_train |
|---|---|---|---|---|---|---|---|---|---|
| 1 | `cand_01_beta_global.pkl` | beta | GLOBAL | 0.07809 | 0.01152 | 0.27916 | 0.35391 | 0.08385 | 8073 |
| 2 | `cand_02_histogram_20_global.pkl` | histogram_20 | GLOBAL | 0.07935 | 0.01401 | 0.31611 | 0.75000 | 0.08635 | 8073 |
| 3 | `cand_03_histogram_10_global.pkl` | histogram_10 | GLOBAL | 0.07882 | 0.01525 | 0.30402 | 0.53251 | 0.08645 | 8073 |

## Kullanım

**ÖNEMLİ**: Candidate pkl'leri `audit/87_calibration_grid.py`'deki calibrator class'larına bağlı. Yüklerken module import gerekiyor:

```python
import sys, pickle, importlib.util
spec = importlib.util.spec_from_file_location(
    'cal87', 'audit/87_calibration_grid.py')
mod = importlib.util.module_from_spec(spec)
sys.modules['cal87'] = mod
spec.loader.exec_module(mod)
for name in ['BetaCal','HistogramCal','IsotonicCal','PlattCal',
             'SplineCal','TemperatureCal','StackingCal','RawCalibrator']:
    setattr(sys.modules['__main__'], name, getattr(mod, name))

with open('cand_01_beta_global.pkl', 'rb') as f:
    cand = pickle.load(f)
preds = cand['model'].predict([0.05, 0.2, 0.5])
# sklearn-compatible interface: model.predict(raw_probs) → calibrated
```

**Aktivasyon yolu** (Berkay onayı ile):

```bash
# Önce backup:
cp simulation/calibrators/fitted/agf_outcome_calibrator.pkl \
   simulation/calibrators/fitted/agf_outcome_calibrator.pkl.bak
# Sonra swap:
cp simulation/calibrators/fitted/candidates/cand_01_beta_global.pkl \
   simulation/calibrators/fitted/agf_outcome_calibrator.pkl
```
