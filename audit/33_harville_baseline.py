#!/usr/bin/env python3
"""Harville baseline — AGF top-k PROPER implied (kaba 5×agf yerine ranking_head ile).

Per-yarış: AGF/sum → ayak içi prob → Plackett-Luce top-k membership.
Bu DOĞRU baseline. ΔAUC model vs Harville-AGF her hedef × yıl.

OUTPUT: audit/reports/harville_baseline.md + jsonl
"""
from __future__ import annotations
import os, sys, json, warnings
warnings.filterwarnings('ignore')
import numpy as np
import pandas as pd
import joblib
from sklearn.metrics import roc_auc_score, brier_score_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)
from dashboard.ranking_head import top_k_membership_probs

CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
MODELS = os.path.join(ROOT, 'model', 'trained_targets_v2')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'harville_baseline.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'harville_baseline.md')


def main():
    print("Loading...", flush=True)
    with open(os.path.join(MODELS, 'feature_columns.json')) as f: fc = json.load(f)
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

    # Per-yarış AGF Harville top-k membership
    print("Computing Harville AGF baseline (per-yarış top-k membership)...", flush=True)
    agf_col = 'agf_pct' if 'agf_pct' in df.columns else ('agf_value' if 'agf_value' in df.columns else None)
    if not agf_col:
        print("FAIL: no agf column"); sys.exit(2)
    df['agf_p'] = df[agf_col].fillna(0) / 100.0
    df['agf_harville_top1'] = 0.0
    df['agf_harville_top3'] = 0.0
    df['agf_harville_top5'] = 0.0
    for rid, idx in df.groupby('race_id').indices.items():
        sub = df.iloc[idx]
        agf = sub['agf_p'].values
        if agf.sum() <= 0:
            continue
        for k, col in [(1, 'agf_harville_top1'), (3, 'agf_harville_top3'),
                        (5, 'agf_harville_top5')]:
            try:
                mem = top_k_membership_probs(agf, k=k)
                df.loc[df.index[idx], col] = mem
            except Exception:
                pass

    test = df[df['race_date'] >= '2025-01-01'].copy()
    test['_yr'] = test['race_date'].dt.year
    print(f"  test n={len(test):,}", flush=True)

    def build_X(d, fc):
        X = pd.DataFrame(index=d.index)
        for c in fc:
            X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
        return X.values

    targets = {'top1':1, 'top3':3, 'top5':5}
    rows = []
    print(f"\n{'Year':>5} {'Breed':>8} {'Target':>6} {'AUC_M':>8} {'AUC_AGF_raw':>12} {'AUC_AGF_Harville':>16} {'Δ_M_vs_H':>10}", flush=True)
    for yr in [2025, 2026]:
        for breed in ['arab', 'english']:
            sub = test[(test['_yr']==yr) & (test['breed']==breed)]
            if len(sub) < 1000: continue
            sc = joblib.load(os.path.join(MODELS, f'scaler_{breed}.pkl'))
            X = sc.transform(build_X(sub, fc))
            for tname, k in targets.items():
                try:
                    xgb = joblib.load(os.path.join(MODELS, tname, f'xgb_{breed}.pkl'))
                    lgbm = joblib.load(os.path.join(MODELS, tname, f'lgbm_{breed}.pkl'))
                    iso = joblib.load(os.path.join(MODELS, tname, f'isotonic_{breed}.pkl'))
                except Exception: continue
                p = 0.5*xgb.predict_proba(X)[:,1] + 0.5*lgbm.predict_proba(X)[:,1]
                p_cal = np.clip(iso.transform(p), 1e-6, 1-1e-6)
                y = (sub['finish_position'].values <= k).astype(int)
                if y.sum() == 0: continue
                auc_m = float(roc_auc_score(y, p_cal))
                # AGF raw (rank)
                auc_agf_raw = float(roc_auc_score(y, -sub['agf_rank'].fillna(99).values))
                # AGF Harville top-k
                col = f'agf_harville_top{k}'
                if col not in sub.columns:
                    auc_agf_h = None
                else:
                    auc_agf_h = float(roc_auc_score(y, sub[col].values))
                d_h = (auc_m - auc_agf_h) if auc_agf_h is not None else None
                rows.append({'year': yr, 'breed': breed, 'target': tname,
                             'auc_model': auc_m, 'auc_agf_raw': auc_agf_raw,
                             'auc_agf_harville': auc_agf_h, 'd_vs_harville': d_h,
                             'n': len(sub)})
                os.makedirs(os.path.dirname(LOG), exist_ok=True)
                with open(LOG, 'a') as f: f.write(json.dumps(rows[-1])+'\n')
                print(f"  {yr:>5} {breed:>8} {tname:>6} {auc_m:>7.4f} "
                      f"{auc_agf_raw:>11.4f} {auc_agf_h if auc_agf_h else 0:>15.4f} "
                      f"{d_h if d_h else 0:>+9.4f}", flush=True)

    # Markdown
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Harville AGF Baseline — DÜZGÜN ΔAUC\n\n")
        f.write("Eski kaba proxy: `AGF_topk_implied = min(k × agf_p, 1)`. Yanlış.\n")
        f.write("Yeni: ranking_head.top_k_membership_probs(AGF/sum) — PL marginal.\n\n")
        f.write("| Year | Breed | Target | AUC_Model | AUC_AGF_raw | AUC_AGF_Harville | Δ_vs_Harville |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['year']} | {r['breed']} | {r['target']} | {r['auc_model']:.4f} | "
                    f"{r['auc_agf_raw']:.4f} | {r['auc_agf_harville']:.4f} | {r['d_vs_harville']:+.4f} |\n")


if __name__ == '__main__':
    main()
