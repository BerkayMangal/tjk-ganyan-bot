#!/usr/bin/env python3
"""Train SUITE v2 — form-eklenmiş 5 binary target × 2 breed.

Yeni feature seti: 177 base + 8 form (point-in-time, sızıntısız).
Walk-forward: train 2021-2023, val 2024 (isotonic), test 2025+.

OUTPUT:
  model/trained_targets_v2/{top1..top5}/{xgb,lgbm,iso}_{arab,english}.pkl
  model/trained_targets_v2/scaler_{arab,english}.pkl
  model/trained_targets_v2/feature_columns.json
  model/trained_targets_v2/train_meta.json
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
from sklearn.metrics import roc_auc_score, brier_score_loss, log_loss

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(ROOT, 'data', 'training_v3', 'races_v3.csv')
FC_IN = os.path.join(ROOT, 'data', 'training_v3', 'feature_columns_v3.json')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
OUT = os.path.join(ROOT, 'model', 'trained_targets_v2')
os.makedirs(OUT, exist_ok=True)


def log(m):
    print(f"[{datetime.now().isoformat()}] {m}", flush=True)


def build_X(d, fc):
    X = pd.DataFrame(index=d.index)
    for c in fc:
        X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
    return X.values


def fit_one(X_tr, y_tr, X_va, y_va):
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                        subsample=0.85, colsample_bytree=0.75,
                        reg_alpha=0.1, reg_lambda=2.0, min_child_weight=5,
                        random_state=42, verbosity=0,
                        eval_metric='logloss', use_label_encoder=False)
    lgbm = LGBMClassifier(n_estimators=400, max_depth=5, learning_rate=0.04, num_leaves=31,
                          subsample=0.85, colsample_bytree=0.75,
                          reg_alpha=0.1, reg_lambda=2.0, min_child_weight=5,
                          random_state=42, verbose=-1)
    xgb.fit(X_tr, y_tr); lgbm.fit(X_tr, y_tr)
    p_va = 0.5 * xgb.predict_proba(X_va)[:, 1] + 0.5 * lgbm.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    return xgb, lgbm, iso


def main():
    log("Loading...")
    with open(FC_IN) as f: fc_base = json.load(f)
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
    fc = fc_base + form_cols
    log(f"  feature_cols n={len(fc)} (base {len(fc_base)} + form {len(form_cols)})")

    train = df[df['race_date'] < '2024-01-01']
    val = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test = df[df['race_date'] >= '2025-01-01']
    log(f"  train n={len(train):,}  val n={len(val):,}  test n={len(test):,}")

    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    meta = {'trained_at': datetime.utcnow().isoformat(), 'n_features': len(fc),
            'splits': {'train': len(train), 'val': len(val), 'test': len(test)},
            'form_cols': form_cols, 'metrics': {}}

    for breed in ['arab', 'english']:
        tr_b = train[train['breed']==breed]; va_b = val[val['breed']==breed]; te_b = test[test['breed']==breed]
        if min(len(tr_b), len(va_b), len(te_b)) < 1000: continue
        sc = StandardScaler().fit(build_X(tr_b, fc))
        X_tr = sc.transform(build_X(tr_b, fc))
        X_va = sc.transform(build_X(va_b, fc))
        X_te = sc.transform(build_X(te_b, fc))
        joblib.dump(sc, os.path.join(OUT, f'scaler_{breed}.pkl'))
        meta['metrics'][breed] = {}
        agf_rank = te_b['agf_rank'].fillna(99).values
        for tname, k in targets.items():
            tgt_dir = os.path.join(OUT, tname); os.makedirs(tgt_dir, exist_ok=True)
            y_tr = (tr_b['finish_position'].values <= k).astype(int)
            y_va = (va_b['finish_position'].values <= k).astype(int)
            y_te = (te_b['finish_position'].values <= k).astype(int)
            if y_tr.sum() < 10: continue
            xgb, lgbm, iso = fit_one(X_tr, y_tr, X_va, y_va)
            p_te = 0.5 * xgb.predict_proba(X_te)[:, 1] + 0.5 * lgbm.predict_proba(X_te)[:, 1]
            p_cal = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
            auc_m = float(roc_auc_score(y_te, p_cal))
            br_m = float(brier_score_loss(y_te, p_cal))
            ll_m = float(log_loss(y_te, p_cal))
            auc_agf = float(roc_auc_score(y_te, -agf_rank)) if y_te.sum() > 0 else None
            d_auc = (auc_m - auc_agf) if auc_agf else None
            joblib.dump(xgb, os.path.join(tgt_dir, f'xgb_{breed}.pkl'))
            joblib.dump(lgbm, os.path.join(tgt_dir, f'lgbm_{breed}.pkl'))
            joblib.dump(iso, os.path.join(tgt_dir, f'isotonic_{breed}.pkl'))
            meta['metrics'][breed][tname] = {'auc_test': auc_m, 'brier_test': br_m,
                                              'logloss_test': ll_m, 'auc_agf': auc_agf,
                                              'd_auc': d_auc, 'pos_rate_test': float(y_te.mean()),
                                              'n_test': int(len(y_te))}
            log(f"  {breed}/{tname}: AUC={auc_m:.4f} AUC_AGF={auc_agf:.4f} Δ={d_auc:+.4f} Brier={br_m:.4f}")

    with open(os.path.join(OUT, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)
    with open(os.path.join(OUT, 'train_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    log(f"DONE — {OUT}")


if __name__ == '__main__':
    main()
