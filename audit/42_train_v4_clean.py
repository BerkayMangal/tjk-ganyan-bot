#!/usr/bin/env python3
"""İŞ 1 (devam) — v4 retrain: dead _enc DROP + v3 ile perf karşılaştırma.

v3 fc n=86. v4 = v3 - 8 dead _enc = 78. Perf değişmemeli (max |ΔAUC|<0.003).

OUTPUT:
  model/trained_targets_v4/...
  audit/reports/v4_clean_train.md
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
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
V3 = os.path.join(ROOT, 'model', 'trained_targets_v3')
V4 = os.path.join(ROOT, 'model', 'trained_targets_v4')
REP = os.path.join(ROOT, 'audit', 'reports', 'v4_clean_train.md')

# audit/41 enc_shap_audit sonucu: max SHAP < %1 olan _enc'ler
DROP_ENC = ['mf__sire_enc', 'mf__hippodrome_enc', 'mf__trainer_enc',
            'mf__distance_category_enc', 'mf__weather_condition_enc',
            'mf__track_condition_enc', 'mf__sec_pace_style_enc',
            'mf__sec_prev1_pace_style_enc']


def log(m): print(f"[{datetime.now().isoformat()}] {m}", flush=True)


def build_X(d, fc):
    X = pd.DataFrame(index=d.index)
    for c in fc:
        X[c] = pd.to_numeric(d[c], errors='coerce').fillna(0.0) if c in d.columns else 0.0
    return X.values


def fit_eval(X_tr, y_tr, X_va, y_va, X_te, y_te):
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
    p_va = 0.5*xgb.predict_proba(X_va)[:,1] + 0.5*lgbm.predict_proba(X_va)[:,1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    p_te = 0.5*xgb.predict_proba(X_te)[:,1] + 0.5*lgbm.predict_proba(X_te)[:,1]
    p_cal = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
    return xgb, lgbm, iso, float(roc_auc_score(y_te, p_cal)), float(brier_score_loss(y_te, p_cal))


def main():
    os.makedirs(V4, exist_ok=True)
    log("Loading...")
    with open(os.path.join(V3, 'feature_columns.json')) as f: fc_v3 = json.load(f)
    fc_v4 = [c for c in fc_v3 if c not in DROP_ENC]
    log(f"  v3 fc n={len(fc_v3)} → v4 fc n={len(fc_v4)} ({len(DROP_ENC)} dropped)")

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

    train = df[df['race_date'] < '2024-01-01']
    val = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test = df[df['race_date'] >= '2025-01-01']
    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    rows = []

    for breed in ['arab', 'english']:
        tr_b = train[train['breed']==breed]; va_b = val[val['breed']==breed]; te_b = test[test['breed']==breed]
        sc_v4 = StandardScaler().fit(build_X(tr_b, fc_v4))
        joblib.dump(sc_v4, os.path.join(V4, f'scaler_{breed}.pkl'))
        X_tr = sc_v4.transform(build_X(tr_b, fc_v4))
        X_va = sc_v4.transform(build_X(va_b, fc_v4))
        X_te = sc_v4.transform(build_X(te_b, fc_v4))
        sc_v3 = joblib.load(os.path.join(V3, f'scaler_{breed}.pkl'))
        X_te_v3 = sc_v3.transform(build_X(te_b, fc_v3))
        for tname, k in targets.items():
            tdir = os.path.join(V4, tname); os.makedirs(tdir, exist_ok=True)
            y_tr = (tr_b['finish_position'].values <= k).astype(int)
            y_va = (va_b['finish_position'].values <= k).astype(int)
            y_te = (te_b['finish_position'].values <= k).astype(int)
            xgb_v4, lgbm_v4, iso_v4, auc_v4, br_v4 = fit_eval(X_tr, y_tr, X_va, y_va, X_te, y_te)
            joblib.dump(xgb_v4, os.path.join(tdir, f'xgb_{breed}.pkl'))
            joblib.dump(lgbm_v4, os.path.join(tdir, f'lgbm_{breed}.pkl'))
            joblib.dump(iso_v4, os.path.join(tdir, f'isotonic_{breed}.pkl'))
            # v3 perf
            xgb_v3 = joblib.load(os.path.join(V3, tname, f'xgb_{breed}.pkl'))
            lgbm_v3 = joblib.load(os.path.join(V3, tname, f'lgbm_{breed}.pkl'))
            iso_v3 = joblib.load(os.path.join(V3, tname, f'isotonic_{breed}.pkl'))
            p3 = 0.5*xgb_v3.predict_proba(X_te_v3)[:,1] + 0.5*lgbm_v3.predict_proba(X_te_v3)[:,1]
            p3_cal = np.clip(iso_v3.transform(p3), 1e-6, 1-1e-6)
            auc_v3 = float(roc_auc_score(y_te, p3_cal))
            br_v3 = float(brier_score_loss(y_te, p3_cal))
            d = auc_v4 - auc_v3
            rows.append({'breed':breed,'target':tname,'auc_v3':auc_v3,'auc_v4':auc_v4,
                          'd_auc':d,'brier_v3':br_v3,'brier_v4':br_v4})
            log(f"  {breed}/{tname}: v4 AUC={auc_v4:.4f} (v3 {auc_v3:.4f}, Δ {d:+.4f}) "
                f"Brier {br_v4:.4f} (v3 {br_v3:.4f})")

    with open(os.path.join(V4, 'feature_columns.json'), 'w') as f: json.dump(fc_v4, f, indent=2)
    with open(os.path.join(V4, 'train_meta.json'), 'w') as f:
        json.dump({'trained_at': datetime.utcnow().isoformat(),
                    'n_features': len(fc_v4), 'dropped': DROP_ENC,
                    'comparison_vs_v3': rows}, f, indent=2, default=str)

    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# v4 Clean Train — dead _enc DROP + perf parity\n\n")
        f.write(f"v3 fc n={len(fc_v3)} → v4 fc n={len(fc_v4)} (drop {len(DROP_ENC)})\n")
        f.write(f"Dropped (audit/41 SHAP %0-1): {DROP_ENC}\n\n")
        f.write("| Breed | Target | AUC_v3 | AUC_v4 | ΔAUC | Brier_v3 | Brier_v4 |\n")
        f.write("|---|---|---|---|---|---|---|\n")
        for r in rows:
            sig = '✓' if abs(r['d_auc']) < 0.003 else '⚠'
            f.write(f"| {r['breed']} | {r['target']} | {r['auc_v3']:.4f} | {r['auc_v4']:.4f} | "
                    f"{r['d_auc']:+.4f} | {r['brier_v3']:.4f} | {r['brier_v4']:.4f} | {sig} |\n")
        max_d = max(abs(r['d_auc']) for r in rows)
        verdict = '✓ Perf esit — v4 e gec' if max_d < 0.003 else '⚠ Δ buyuk — incele'
        f.write(f"\n**Max |ΔAUC| = {max_d:.4f}**. {verdict}\n")


if __name__ == '__main__':
    main()
