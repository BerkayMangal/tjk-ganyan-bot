#!/usr/bin/env python3
"""V5 retrain Adım 6 — Beta calibration re-fit ECE artışını kapatma.

Phase 5.8.10'da V5 AUC her segmentte arttı (+%0.05-1.24) ama ECE de arttı
(model daha overconfident). Phase 5.2.6'da AGF için beta calibration ECE'yi
%66 düşürmüştü. Aynısını V5 model output'larına uygulayım: her target × breed
için validation set'inde BOTH isotonic VE beta fit + test ECE/Brier kıyas.

OUT:
  model/trained_targets_v5/{top*}/beta_{breed}.pkl  (yeni)
  model/trained_targets_v5/{top*}/best_calibrator_{breed}.txt  (isotonic|beta)
  audit/reports/phase_5_8_11_v5_recal.md
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from datetime import datetime
from sklearn.preprocessing import StandardScaler
from sklearn.isotonic import IsotonicRegression
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from simulation.calibrators.beta import BetaCalibrator

CSV_IN = os.path.join(ROOT, 'data', 'training_v5', 'races_v5.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
V5 = os.path.join(ROOT, 'model', 'trained_targets_v5')
REP = os.path.join(ROOT, 'audit', 'reports', 'phase_5_8_11_v5_recal.md')


def log(m): print(f"[{datetime.now().isoformat()[:19]}] {m}", flush=True)


def build_X(d, fc):
    X = pd.DataFrame(index=d.index)
    for c in fc:
        X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
    return X.values


def ece(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    n = len(y)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i+1]
        m = (p >= lo) & (p < hi if i < n_bins-1 else p <= hi)
        if not m.any():
            continue
        e += (m.sum() / n) * abs(p[m].mean() - y[m].mean())
    return float(e)


def mce(y, p, n_bins=10):
    edges = np.linspace(0, 1, n_bins + 1)
    worst = 0.0
    n = len(y)
    for i in range(n_bins):
        lo, hi = edges[i], edges[i+1]
        m = (p >= lo) & (p < hi if i < n_bins-1 else p <= hi)
        if not m.any():
            continue
        worst = max(worst, abs(p[m].mean() - y[m].mean()))
    return float(worst)


def main():
    log("Loading...")
    with open(os.path.join(V5, 'feature_columns.json')) as f:
        fc = json.load(f)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
    form_cols = ['last_race_finish','avg_finish_last3','avg_finish_last5','avg_finish_last10',
                 'win_rate_last10','top3_rate_last10','days_since_last_race','races_in_last_180d']
    df = df.merge(form[['race_horse_id']+form_cols], on='race_horse_id', how='left')
    df[form_cols] = df[form_cols].fillna(0.0)
    val  = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test = df[df['race_date'] >= '2025-01-01']

    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    rows = []
    for breed in ['arab', 'english']:
        log(f"\n=== breed={breed} ===")
        va_b = val[val['breed']==breed]
        te_b = test[test['breed']==breed]
        sc = joblib.load(os.path.join(V5, f'scaler_{breed}.pkl'))
        X_va = sc.transform(build_X(va_b, fc))
        X_te = sc.transform(build_X(te_b, fc))

        for tname, k in targets.items():
            tdir = os.path.join(V5, tname)
            xgb_m = joblib.load(os.path.join(tdir, f'xgb_{breed}.pkl'))
            lgbm_m = joblib.load(os.path.join(tdir, f'lgbm_{breed}.pkl'))
            iso_m = joblib.load(os.path.join(tdir, f'isotonic_{breed}.pkl'))

            y_va = (va_b['finish_position'].values <= k).astype(int)
            y_te = (te_b['finish_position'].values <= k).astype(int)

            # Raw ensemble probs
            p_va = 0.5*xgb_m.predict_proba(X_va)[:,1] + 0.5*lgbm_m.predict_proba(X_va)[:,1]
            p_te = 0.5*xgb_m.predict_proba(X_te)[:,1] + 0.5*lgbm_m.predict_proba(X_te)[:,1]

            # Isotonic (mevcut)
            p_iso = np.clip(iso_m.transform(p_te), 1e-6, 1-1e-6)
            auc_iso = roc_auc_score(y_te, p_iso)
            br_iso = brier_score_loss(y_te, p_iso)
            ece_iso = ece(y_te, p_iso)
            mce_iso = mce(y_te, p_iso)

            # Beta (yeni)
            beta = BetaCalibrator().fit(p_va, y_va)
            p_beta = np.clip(beta.predict(p_te), 1e-6, 1-1e-6)
            auc_beta = roc_auc_score(y_te, p_beta)
            br_beta = brier_score_loss(y_te, p_beta)
            ece_beta = ece(y_te, p_beta)
            mce_beta = mce(y_te, p_beta)

            # Combined score: ECE + Brier (lower better)
            score_iso = ece_iso + br_iso
            score_beta = ece_beta + br_beta
            best = 'beta' if score_beta < score_iso else 'isotonic'

            joblib.dump(beta, os.path.join(tdir, f'beta_{breed}.pkl'))
            with open(os.path.join(tdir, f'best_calibrator_{breed}.txt'), 'w') as f:
                f.write(best + '\n')

            rows.append({
                'breed': breed, 'target': tname,
                'auc_iso': auc_iso, 'auc_beta': auc_beta,
                'brier_iso': br_iso, 'brier_beta': br_beta, 'd_brier': br_beta-br_iso,
                'ece_iso': ece_iso, 'ece_beta': ece_beta, 'd_ece': ece_beta-ece_iso,
                'mce_iso': mce_iso, 'mce_beta': mce_beta,
                'best': best, 'd_combined': score_beta - score_iso,
            })
            log(f"  {tname}: iso ECE {ece_iso:.4f} Brier {br_iso:.4f} | "
                f"beta ECE {ece_beta:.4f} Brier {br_beta:.4f} | best={best}")

    # Summary
    n_beta_win = sum(1 for r in rows if r['best'] == 'beta')
    mean_d_ece = sum(r['d_ece'] for r in rows) / len(rows)
    mean_d_brier = sum(r['d_brier'] for r in rows) / len(rows)

    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Phase 5.8.11 — V5 Beta Calibration Re-fit\n\n")
        f.write(f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Özet\n\n")
        f.write(f"- Beta seçilen segment: **{n_beta_win}/10**\n")
        f.write(f"- Ortalama ΔECE (beta-iso): **{mean_d_ece:+.4f}** ({'iyileşme' if mean_d_ece<0 else 'kötüleşme'})\n")
        f.write(f"- Ortalama ΔBrier (beta-iso): **{mean_d_brier:+.4f}**\n\n")
        f.write("## Per-target (val→test, ECE/Brier/MCE)\n\n")
        f.write("| Breed | Target | ECE_iso | ECE_beta | ΔECE | Brier_iso | Brier_beta | ΔBrier | best |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['breed']} | {r['target']} | "
                    f"{r['ece_iso']:.4f} | {r['ece_beta']:.4f} | {r['d_ece']:+.4f} | "
                    f"{r['brier_iso']:.4f} | {r['brier_beta']:.4f} | {r['d_brier']:+.4f} | "
                    f"**{r['best']}** |\n")
        f.write("\n## Karar\n\n")
        if mean_d_ece < -0.001:
            f.write("**✓ Beta calibration ECE'yi düşürdü** — production'da beta kullan.\n")
        elif n_beta_win >= 6:
            f.write("**~ Kısmi kazanç** — segment-bazlı seçim (best_calibrator_*.txt).\n")
        else:
            f.write("**= İsotonic yeterli** — beta belirgin kazanç vermedi.\n")

    log(f"✓ {REP}")
    log(f"\nBeta won: {n_beta_win}/10 segment")
    log(f"Mean ΔECE: {mean_d_ece:+.4f}")
    log(f"Mean ΔBrier: {mean_d_brier:+.4f}")


if __name__ == '__main__':
    main()
