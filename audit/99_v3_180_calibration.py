#!/usr/bin/env python3
"""Phase 5.8.14 — V3 NEW (180) için isotonic + beta calibration fit.

Test set'i (≥2025) ikiye böl:
  - 2025-01 → 2025-06 (ilk yarı): calibration validation
  - 2025-07 → 2025-12 (ikinci yarı): final test (calibration karşılaştırması)

V3 NEW model_v3_180/ artefaktları zaten audit/98 ile fit edildi (train <2025).
Bu script:
  - test (≥2025) yarısı 1'i val olarak isotonic + beta fit
  - yarısı 2'de raw / isotonic / beta karşılaştır (ECE + Brier)
  - en iyisi → `isotonic_prob_{b}.pkl` (v3_live çağıracak) + beta_prob_{b}.pkl

OUTPUT:
  model/trained_v3_180/isotonic_prob_{arab,english}.pkl
  model/trained_v3_180/beta_prob_{arab,english}.pkl
  model/trained_v3_180/calib_best_{arab,english}.txt   ('isotonic'|'beta')
  audit/reports/phase_5_8_14_v3_180_calib.md
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_V5 = os.path.join(REPO, 'data', 'training_v5', 'races_v5.csv')
NEW_DIR = os.path.join(REPO, 'model', 'trained_v3_180')
REP = os.path.join(REPO, 'audit', 'reports', 'phase_5_8_14_v3_180_calib.md')

from simulation.calibrators.beta import BetaCalibrator


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns
              else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1); e = 0.0; n = len(y)
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i+1] if i < n_bins-1 else p <= edges[i+1])
        if not m.any(): continue
        e += (m.sum()/n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def main():
    with open(os.path.join(NEW_DIR, 'feature_columns.json')) as f:
        fc = json.load(f)
    logger.info(f"V3 NEW fc={len(fc)}")
    logger.info(f"Loading {CSV_V5}...")
    df = pd.read_csv(CSV_V5, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    df['_rd'] = pd.to_datetime(df['race_date'])

    VAL_LO = '2025-01-01'; VAL_HI = '2025-07-01'
    test = df[df['_rd'] >= VAL_LO]
    cal = test[(test['_rd'] >= VAL_LO) & (test['_rd'] < VAL_HI)]
    final = test[test['_rd'] >= VAL_HI]
    logger.info(f"  cal: {len(cal):,} (2025-01..2025-06)   final: {len(final):,} (2025-07+)")

    summary = {}
    for breed in ('arab', 'english'):
        cal_b = cal[cal['breed'] == breed].copy()
        fin_b = final[final['breed'] == breed].copy()
        logger.info(f"\n=== {breed} cal={len(cal_b):,} final={len(fin_b):,} ===")

        sc_p = joblib.load(os.path.join(NEW_DIR, f'scaler_prob_{breed}.pkl'))
        xgb_p = joblib.load(os.path.join(NEW_DIR, f'xgb_prob_{breed}.pkl'))
        lgbm_p = joblib.load(os.path.join(NEW_DIR, f'lgbm_prob_{breed}.pkl'))

        X_cal = sc_p.transform(build_X(cal_b, fc))
        X_fin = sc_p.transform(build_X(fin_b, fc))
        y_cal = (cal_b['finish_position'].values == 1).astype(float)
        y_fin = (fin_b['finish_position'].values == 1).astype(float)

        p_cal = 0.5*xgb_p.predict_proba(X_cal)[:,1] + 0.5*lgbm_p.predict_proba(X_cal)[:,1]
        p_fin = 0.5*xgb_p.predict_proba(X_fin)[:,1] + 0.5*lgbm_p.predict_proba(X_fin)[:,1]

        # Raw
        p_raw = np.clip(p_fin, 1e-6, 1-1e-6)
        m_raw = {
            'auc': roc_auc_score(y_fin, p_raw),
            'brier': brier_score_loss(y_fin, p_raw),
            'ece': ece(y_fin, p_raw),
            'log_loss': log_loss(y_fin, p_raw),
        }

        # Isotonic
        iso = IsotonicRegression(out_of_bounds='clip').fit(p_cal, y_cal)
        p_iso = np.clip(iso.transform(p_fin), 1e-6, 1-1e-6)
        m_iso = {
            'auc': roc_auc_score(y_fin, p_iso),
            'brier': brier_score_loss(y_fin, p_iso),
            'ece': ece(y_fin, p_iso),
            'log_loss': log_loss(y_fin, p_iso),
        }

        # Beta
        beta = BetaCalibrator().fit(p_cal, y_cal)
        p_beta = np.clip(beta.predict(p_fin), 1e-6, 1-1e-6)
        m_beta = {
            'auc': roc_auc_score(y_fin, p_beta),
            'brier': brier_score_loss(y_fin, p_beta),
            'ece': ece(y_fin, p_beta),
            'log_loss': log_loss(y_fin, p_beta),
        }

        # Best: ECE + Brier (lower better)
        candidates = {
            'raw': m_raw['ece'] + m_raw['brier'],
            'isotonic': m_iso['ece'] + m_iso['brier'],
            'beta': m_beta['ece'] + m_beta['brier'],
        }
        best = min(candidates, key=candidates.get)

        # Persist
        joblib.dump(iso, os.path.join(NEW_DIR, f'isotonic_prob_{breed}.pkl'))
        joblib.dump(beta, os.path.join(NEW_DIR, f'beta_prob_{breed}.pkl'))
        with open(os.path.join(NEW_DIR, f'calib_best_{breed}.txt'), 'w') as f:
            f.write(best + '\n')

        summary[breed] = {
            'cal_n': int(len(cal_b)), 'final_n': int(len(fin_b)),
            'raw': m_raw, 'isotonic': m_iso, 'beta': m_beta, 'best': best,
        }
        logger.info(f"  raw      ECE={m_raw['ece']:.4f} Brier={m_raw['brier']:.4f} AUC={m_raw['auc']:.4f}")
        logger.info(f"  isotonic ECE={m_iso['ece']:.4f} Brier={m_iso['brier']:.4f} AUC={m_iso['auc']:.4f}")
        logger.info(f"  beta     ECE={m_beta['ece']:.4f} Brier={m_beta['brier']:.4f} AUC={m_beta['auc']:.4f}")
        logger.info(f"  BEST → {best}")

    # Markdown raporu
    lines = ["# Phase 5.8.14 — V3 NEW (180) Calibration Fit (isotonic + beta)\n\n",
             f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n",
             "Val: 2025-01..06 (calibration fit) | Final: 2025-07+ (kıyas)\n\n"]
    for breed, s in summary.items():
        lines.append(f"### {breed.upper()} (cal={s['cal_n']:,}, final={s['final_n']:,})\n\n"
                     f"| Method | AUC | Brier | ECE | LogLoss |\n|---|---|---|---|---|\n"
                     f"| raw      | {s['raw']['auc']:.4f} | {s['raw']['brier']:.4f} | {s['raw']['ece']:.4f} | {s['raw']['log_loss']:.4f} |\n"
                     f"| isotonic | {s['isotonic']['auc']:.4f} | {s['isotonic']['brier']:.4f} | {s['isotonic']['ece']:.4f} | {s['isotonic']['log_loss']:.4f} |\n"
                     f"| beta     | {s['beta']['auc']:.4f} | {s['beta']['brier']:.4f} | {s['beta']['ece']:.4f} | {s['beta']['log_loss']:.4f} |\n\n"
                     f"**BEST: `{s['best']}`** (ECE+Brier combined)\n\n")
    with open(REP, 'w', encoding='utf-8') as f:
        f.write(''.join(lines))
    logger.info(f"\n✓ {REP}")
    logger.info(f"v3_live.py 'isotonic_prob_{{b}}.pkl' yükleyecek → V3 NEW kalibre olur.")


if __name__ == '__main__':
    main()
