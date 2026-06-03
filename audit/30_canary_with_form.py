#!/usr/bin/env python3
"""SIZINTI KANARYASI — form-eklenmiş top-1 AUC vs form'suz baseline.

Eğer form ile top-1 AGF'yi BÜYÜK farkla geçerse (AUC > 0.78 veya ΔAUC > +0.05) → SIZINTI ALARMI.
AGF'ye YAKLAŞMA bekleniyor (form public bilginin alt-kümesi: pari ve AGF'de zaten gömülü).

Form feature seti: data/form/horse_form_pit.csv (point-in-time, strictly-prior).
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
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
LOG = os.path.join(ROOT, 'audit', 'sib_logs', 'form_canary.jsonl')


def log(rec):
    with open(LOG, 'a') as f:
        f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')


def build_X(d, fc):
    X = pd.DataFrame(index=d.index)
    for c in fc:
        X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
    return X.values


def fit_and_eval(X_tr, y_tr, X_va, y_va, X_te, y_te):
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb = XGBClassifier(n_estimators=300, max_depth=5, learning_rate=0.05,
                        subsample=0.85, colsample_bytree=0.75,
                        reg_alpha=0.1, reg_lambda=2.0, min_child_weight=5,
                        random_state=42, verbosity=0,
                        eval_metric='logloss', use_label_encoder=False)
    lgbm = LGBMClassifier(n_estimators=300, max_depth=5, learning_rate=0.05, num_leaves=31,
                          subsample=0.85, colsample_bytree=0.75,
                          reg_alpha=0.1, reg_lambda=2.0, min_child_weight=5,
                          random_state=42, verbose=-1)
    xgb.fit(X_tr, y_tr); lgbm.fit(X_tr, y_tr)
    p_va = 0.5 * xgb.predict_proba(X_va)[:, 1] + 0.5 * lgbm.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    p_te = 0.5 * xgb.predict_proba(X_te)[:, 1] + 0.5 * lgbm.predict_proba(X_te)[:, 1]
    p_cal = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
    return {
        'auc': float(roc_auc_score(y_te, p_cal)),
        'brier': float(brier_score_loss(y_te, p_cal)),
        'top1_pred': p_cal,
    }


def main():
    print("Loading datasets...", flush=True)
    with open(FC_IN) as f: fc_base = json.load(f)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    print(f"  base CSV: {len(df):,}", flush=True)
    form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
    print(f"  form: {len(form):,}", flush=True)
    # Merge (race_horse_id ile)
    form_cols = ['race_horse_id', 'last_race_finish', 'avg_finish_last3',
                 'avg_finish_last5', 'avg_finish_last10', 'win_rate_last10',
                 'top3_rate_last10', 'days_since_last_race', 'races_in_last_180d']
    df = df.merge(form[form_cols], on='race_horse_id', how='left')
    print(f"  merged: {len(df):,}, form match rate: "
          f"{df['avg_finish_last5'].notna().sum()/len(df)*100:.1f}%", flush=True)
    # Fill NaN form (new horse, 1st race) → median değil; 0 fill (treated as missing)
    new_form_cols = [c for c in form_cols if c != 'race_horse_id']
    df[new_form_cols] = df[new_form_cols].fillna(0.0)
    # Walk-forward: train 2021-2023, val 2024, test 2025+
    train = df[df['race_date'] < '2024-01-01']
    val = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test = df[df['race_date'] >= '2025-01-01']
    print(f"  split: train n={len(train):,}, val n={len(val):,}, test n={len(test):,}", flush=True)

    # 2 versiyon: form'suz (baseline 177) + form-eklenmiş (177+7)
    fc_with_form = fc_base + new_form_cols
    print(f"  fc_base n={len(fc_base)}, fc_with_form n={len(fc_with_form)}", flush=True)

    print("\n=== KANARYA: top-1 AUC karşılaştırma (form'suz vs formlu) ===", flush=True)
    for breed in ['arab', 'english']:
        tr_b = train[train['breed']==breed]; va_b = val[val['breed']==breed]; te_b = test[test['breed']==breed]
        if min(len(tr_b), len(va_b), len(te_b)) < 1000:
            continue
        # AGF baseline AUC (rank-based)
        y_te = (te_b['finish_position'].values == 1).astype(int)
        agf_rank = te_b['agf_rank'].fillna(99).values
        auc_agf = float(roc_auc_score(y_te, -agf_rank))

        # Form'suz
        X_tr0 = build_X(tr_b, fc_base); X_va0 = build_X(va_b, fc_base); X_te0 = build_X(te_b, fc_base)
        sc0 = StandardScaler().fit(X_tr0)
        X_tr0s = sc0.transform(X_tr0); X_va0s = sc0.transform(X_va0); X_te0s = sc0.transform(X_te0)
        y_tr = (tr_b['finish_position'].values == 1).astype(int)
        y_va = (va_b['finish_position'].values == 1).astype(int)
        res0 = fit_and_eval(X_tr0s, y_tr, X_va0s, y_va, X_te0s, y_te)
        # Form'lu
        X_tr1 = build_X(tr_b, fc_with_form); X_va1 = build_X(va_b, fc_with_form); X_te1 = build_X(te_b, fc_with_form)
        sc1 = StandardScaler().fit(X_tr1)
        X_tr1s = sc1.transform(X_tr1); X_va1s = sc1.transform(X_va1); X_te1s = sc1.transform(X_te1)
        res1 = fit_and_eval(X_tr1s, y_tr, X_va1s, y_va, X_te1s, y_te)

        d_form = res1['auc'] - res0['auc']
        d_vs_agf_baseline = res0['auc'] - auc_agf
        d_vs_agf_with_form = res1['auc'] - auc_agf

        if d_vs_agf_with_form > 0.05:
            canary = 'SIZINTI ALARM!'
        elif d_vs_agf_with_form < -0.02:
            canary = 'AGF ustun (form edge vermedi)'
        elif d_form > 0:
            canary = 'OK (form AGF ye yaklastirdi)'
        else:
            canary = 'OK (form etkisi notr)'
        print(f"\n  {breed} top-1:", flush=True)
        print(f"    AUC_AGF                    = {auc_agf:.4f} (baseline)", flush=True)
        print(f"    AUC_model_baseline (177f)  = {res0['auc']:.4f}  Δ_vs_AGF = {d_vs_agf_baseline:+.4f}", flush=True)
        print(f"    AUC_model_with_form (184f) = {res1['auc']:.4f}  Δ_vs_AGF = {d_vs_agf_with_form:+.4f}", flush=True)
        print(f"    Δ form etkisi              = {d_form:+.4f}", flush=True)
        print(f"    🚨 KANARYA: {canary}", flush=True)
        log({'breed': breed, 'target': 'top1',
             'auc_agf': auc_agf,
             'auc_model_baseline': res0['auc'],
             'auc_model_with_form': res1['auc'],
             'delta_form': d_form,
             'delta_vs_agf_baseline': d_vs_agf_baseline,
             'delta_vs_agf_with_form': d_vs_agf_with_form,
             'verdict': canary})


if __name__ == '__main__':
    main()
