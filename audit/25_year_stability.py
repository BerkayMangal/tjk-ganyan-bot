#!/usr/bin/env python3
"""YIL-YIL STABİLİTE — top-4/5 edge gerçek mi 2026-fluke mu?

3 walk-forward pencere:
  A: train 2021-2022, val 2023, test 2024
  B: train 2021-2023, val 2024, test 2025
  C: train 2021-2024, val 2025, test 2026 (parça)

Her pencere için: 5 target × 2 breed × XGB+LGBM ensemble + isotonic kalibrasyon.
Metric: AUC vs AGF baseline, ΔAUC her hedefte.

OUTPUT:
  audit/sib_logs/year_stability.jsonl
  audit/reports/year_stability.md
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
CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FC_IN = os.path.join(ROOT, 'data', 'training_v3', 'feature_columns_v3.json')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'year_stability.jsonl')
REP = os.path.join(ROOT, 'audit', 'reports', 'year_stability.md')


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def build_X(d, fc):
    X = pd.DataFrame(index=d.index)
    for c in fc:
        X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
    return X.values


def fit_predict(X_tr, y_tr, X_va, y_va, X_te, y_te):
    """XGB+LGBM ensemble + isotonic (val), test prob."""
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb = XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                        subsample=0.85, colsample_bytree=0.75, reg_alpha=0.1, reg_lambda=2.0,
                        min_child_weight=5, random_state=42, verbosity=0,
                        eval_metric='logloss', use_label_encoder=False)
    lgbm = LGBMClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, num_leaves=31,
                          subsample=0.85, colsample_bytree=0.75, reg_alpha=0.1, reg_lambda=2.0,
                          min_child_weight=5, random_state=42, verbose=-1)
    xgb.fit(X_tr, y_tr); lgbm.fit(X_tr, y_tr)
    p_va = 0.5 * xgb.predict_proba(X_va)[:, 1] + 0.5 * lgbm.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    p_te = 0.5 * xgb.predict_proba(X_te)[:, 1] + 0.5 * lgbm.predict_proba(X_te)[:, 1]
    p_cal = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
    return p_cal


def main():
    os.makedirs(os.path.dirname(LOG), exist_ok=True)
    open(LOG, 'w').close()
    with open(FC_IN) as f:
        fc = json.load(f)
    print(f"Loading dataset...", flush=True)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))

    windows = [
        ('A_2024test', '2023-01-01', '2024-01-01', '2025-01-01'),
        ('B_2025test', '2024-01-01', '2025-01-01', '2026-01-01'),
        ('C_2026test', '2025-01-01', '2026-01-01', '2027-01-01'),
    ]
    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    summary = []

    for wname, val_start, test_start, test_end in windows:
        tr = df[df['race_date'] < val_start]
        va = df[(df['race_date'] >= val_start) & (df['race_date'] < test_start)]
        te = df[(df['race_date'] >= test_start) & (df['race_date'] < test_end)]
        print(f"\n=== {wname}: train {len(tr):,} | val {len(va):,} | test {len(te):,} ===", flush=True)

        for breed in ['arab', 'english']:
            tr_b = tr[tr['breed']==breed]; va_b = va[va['breed']==breed]; te_b = te[te['breed']==breed]
            if min(len(tr_b), len(va_b), len(te_b)) < 1000:
                print(f"  {breed}: sample too small, skip", flush=True); continue
            sc = StandardScaler().fit(build_X(tr_b, fc))
            X_tr = sc.transform(build_X(tr_b, fc))
            X_va = sc.transform(build_X(va_b, fc))
            X_te = sc.transform(build_X(te_b, fc))
            # AGF baseline
            agf_te = (te_b['agf_pct'].fillna(0).values / 100.0) if 'agf_pct' in te_b.columns else None
            agf_rank_te = te_b['agf_rank'].fillna(99).values if 'agf_rank' in te_b.columns else None
            for tname, k in targets.items():
                y_tr = (tr_b['finish_position'].values <= k).astype(int)
                y_va = (va_b['finish_position'].values <= k).astype(int)
                y_te = (te_b['finish_position'].values <= k).astype(int)
                if y_tr.sum() < 10 or y_va.sum() < 10 or y_te.sum() < 10:
                    continue
                p_cal = fit_predict(X_tr, y_tr, X_va, y_va, X_te, y_te)
                try:
                    auc_m = float(roc_auc_score(y_te, p_cal))
                    br_m = float(brier_score_loss(y_te, p_cal))
                except Exception:
                    continue
                # AGF baseline AUC (rank-based)
                auc_agf = None
                if agf_rank_te is not None and y_te.sum() > 0:
                    try:
                        auc_agf = float(roc_auc_score(y_te, -agf_rank_te))
                    except Exception: pass
                d_auc = (auc_m - auc_agf) if auc_agf else None
                summary.append({'window': wname, 'breed': breed, 'target': tname,
                                'n_test': int(len(te_b)),
                                'pos_rate': float(y_te.mean()),
                                'auc_model': auc_m, 'auc_agf': auc_agf, 'd_auc': d_auc,
                                'brier_model': br_m})
                log(summary[-1])
                sig = '✓' if (d_auc and d_auc > 0) else '✗'
                print(f"  {breed} {tname}: N={len(te_b):,} AUC_M={auc_m:.4f} "
                      f"AUC_AGF={auc_agf or 0:.4f} Δ={d_auc:+.4f} {sig}", flush=True)

    # Stabilite analizi: top-4/5 her pencerede +ΔAUC mı?
    print("\n=== STABİLİTE ANALİZİ ===", flush=True)
    for tname in ['top1', 'top4', 'top5']:
        for breed in ['arab', 'english']:
            rows = [r for r in summary if r['target']==tname and r['breed']==breed]
            d_aucs = [r['d_auc'] for r in rows if r['d_auc'] is not None]
            if not d_aucs: continue
            n_pos = sum(1 for d in d_aucs if d > 0)
            print(f"  {tname}/{breed}: {n_pos}/{len(d_aucs)} pencere +ΔAUC | "
                  f"mean ΔAUC = {np.mean(d_aucs):+.4f}", flush=True)

    # Rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# YIL-YIL STABİLİTE — Top-4/5 Edge Gerçek mi 2026-fluke mu?\n\n")
        f.write("3 walk-forward pencere, her birinde 5 hedef × 2 breed.\n\n")
        f.write("## ΔAUC = AUC_Model − AUC_AGF (test setinde)\n\n")
        f.write("| Window | Breed | Target | N_test | PosRate | AUC_M | AUC_AGF | ΔAUC | Sig |\n")
        f.write("|---|---|---|---|---|---|---|---|---|\n")
        for r in summary:
            sig = '✓' if (r['d_auc'] and r['d_auc']>0) else '✗'
            f.write(f"| {r['window']} | {r['breed']} | {r['target']} | {r['n_test']:,} | "
                    f"{r['pos_rate']*100:.1f}% | {r['auc_model']:.4f} | "
                    f"{r['auc_agf'] or 0:.4f} | {r['d_auc'] or 0:+.4f} | {sig} |\n")
        f.write("\n## Stabilite verdict\n\n")
        for tname in ['top1', 'top4', 'top5']:
            for breed in ['arab', 'english']:
                rows = [r for r in summary if r['target']==tname and r['breed']==breed]
                d_aucs = [r['d_auc'] for r in rows if r['d_auc'] is not None]
                if not d_aucs: continue
                n_pos = sum(1 for d in d_aucs if d > 0)
                mean_d = np.mean(d_aucs)
                stable = '**STABİL**' if (n_pos == len(d_aucs) and mean_d > 0.01) else \
                         ('marjinal' if n_pos > 0 and mean_d > 0 else '**STABİL DEĞİL**')
                f.write(f"- **{tname}/{breed}**: {n_pos}/{len(d_aucs)} pencere +ΔAUC, "
                        f"mean Δ = {mean_d:+.4f} → {stable}\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
