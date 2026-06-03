#!/usr/bin/env python3
"""İŞ 4 — Dead feature drop (f_* + status %0 SHAP) → v3 retrain.

v2 feature seti: 185 (96 base f_* + 81 mf__ + 8 form)
v3 feature seti: 89 (96 base ATILDI + 81 mf__ + 8 form)
   - f_* (96 base): SHAP %0 (CSV'de 0-fill), tamamen dead
   - status (mf__is_favorite, mf__is_apprentice, mf__rest_category, mf__hippodrome_name): SHAP %0

Beklenti: AUC/ECE aynı, model ~%50 küçük + hızlı.

OUTPUT:
  model/trained_targets_v3/{top1..top5}/{xgb,lgbm,iso}_{arab,english}.pkl
  audit/reports/dead_drop_v3.md
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
V2_DIR = os.path.join(ROOT, 'model', 'trained_targets_v2')
V3_DIR = os.path.join(ROOT, 'model', 'trained_targets_v3')
REP = os.path.join(ROOT, 'audit', 'reports', 'dead_drop_v3.md')

DEAD_PATTERNS = ('f_',)   # 96 base feature
DEAD_NAMES = {'mf__is_favorite', 'mf__is_apprentice', 'mf__rest_category',
              'mf__hippodrome_name'}


def log(m):
    print(f"[{datetime.now().isoformat()}] {m}", flush=True)


def filter_features(fc):
    keep, dropped = [], []
    for c in fc:
        if any(c.startswith(p) for p in DEAD_PATTERNS) or c in DEAD_NAMES:
            dropped.append(c)
        else:
            keep.append(c)
    return keep, dropped


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
    p_va = 0.5 * xgb.predict_proba(X_va)[:, 1] + 0.5 * lgbm.predict_proba(X_va)[:, 1]
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_va, y_va)
    p_te = 0.5 * xgb.predict_proba(X_te)[:, 1] + 0.5 * lgbm.predict_proba(X_te)[:, 1]
    p_cal = np.clip(iso.transform(p_te), 1e-6, 1-1e-6)
    return xgb, lgbm, iso, float(roc_auc_score(y_te, p_cal)), float(brier_score_loss(y_te, p_cal))


def main():
    os.makedirs(V3_DIR, exist_ok=True)
    log("Loading...")
    with open(os.path.join(V2_DIR, 'feature_columns.json')) as f: fc_v2 = json.load(f)
    fc_v3, dropped = filter_features(fc_v2)
    log(f"  v2 fc n={len(fc_v2)} → v3 fc n={len(fc_v3)} ({len(dropped)} dropped)")
    log(f"  dropped (first 10): {dropped[:10]}")

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
    comparison = []

    for breed in ['arab', 'english']:
        tr_b = train[train['breed']==breed]; va_b = val[val['breed']==breed]; te_b = test[test['breed']==breed]
        if min(len(tr_b), len(va_b), len(te_b)) < 1000: continue
        sc = StandardScaler().fit(build_X(tr_b, fc_v3))
        joblib.dump(sc, os.path.join(V3_DIR, f'scaler_{breed}.pkl'))
        X_tr = sc.transform(build_X(tr_b, fc_v3))
        X_va = sc.transform(build_X(va_b, fc_v3))
        X_te = sc.transform(build_X(te_b, fc_v3))
        # v2 modellerini reload — karşılaştırma
        sc_v2 = joblib.load(os.path.join(V2_DIR, f'scaler_{breed}.pkl'))
        with open(os.path.join(V2_DIR, 'feature_columns.json')) as f: fc_v2_local = json.load(f)
        X_te_v2 = sc_v2.transform(build_X(te_b, fc_v2_local))

        for tname, k in targets.items():
            tgt_dir = os.path.join(V3_DIR, tname); os.makedirs(tgt_dir, exist_ok=True)
            y_tr = (tr_b['finish_position'].values <= k).astype(int)
            y_va = (va_b['finish_position'].values <= k).astype(int)
            y_te = (te_b['finish_position'].values <= k).astype(int)
            xgb_v3, lgbm_v3, iso_v3, auc_v3, br_v3 = fit_eval(X_tr, y_tr, X_va, y_va, X_te, y_te)
            joblib.dump(xgb_v3, os.path.join(tgt_dir, f'xgb_{breed}.pkl'))
            joblib.dump(lgbm_v3, os.path.join(tgt_dir, f'lgbm_{breed}.pkl'))
            joblib.dump(iso_v3, os.path.join(tgt_dir, f'isotonic_{breed}.pkl'))
            # v2 metric
            xgb_v2 = joblib.load(os.path.join(V2_DIR, tname, f'xgb_{breed}.pkl'))
            lgbm_v2 = joblib.load(os.path.join(V2_DIR, tname, f'lgbm_{breed}.pkl'))
            iso_v2 = joblib.load(os.path.join(V2_DIR, tname, f'isotonic_{breed}.pkl'))
            p_v2 = 0.5*xgb_v2.predict_proba(X_te_v2)[:,1] + 0.5*lgbm_v2.predict_proba(X_te_v2)[:,1]
            p_v2_cal = np.clip(iso_v2.transform(p_v2), 1e-6, 1-1e-6)
            auc_v2 = float(roc_auc_score(y_te, p_v2_cal))
            br_v2 = float(brier_score_loss(y_te, p_v2_cal))
            comparison.append({'breed':breed, 'target':tname,
                                'auc_v2':auc_v2,'auc_v3':auc_v3,'d_auc':auc_v3-auc_v2,
                                'brier_v2':br_v2,'brier_v3':br_v3,'d_brier':br_v3-br_v2})
            log(f"  {breed}/{tname}: v3 AUC={auc_v3:.4f} (v2 {auc_v2:.4f}, Δ {auc_v3-auc_v2:+.4f}) "
                f"Brier {br_v3:.4f} (v2 {br_v2:.4f}, Δ {br_v3-br_v2:+.4f})")

    with open(os.path.join(V3_DIR, 'feature_columns.json'), 'w') as f: json.dump(fc_v3, f, indent=2)
    with open(os.path.join(V3_DIR, 'train_meta.json'), 'w') as f:
        json.dump({'trained_at': datetime.utcnow().isoformat(),
                    'n_features': len(fc_v3), 'dropped_count': len(dropped),
                    'dropped_features': dropped,
                    'comparison_vs_v2': comparison}, f, indent=2, default=str)

    # Rapor
    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Dead Feature Drop → v3 vs v2\n\n")
        f.write(f"v2 fc n={len(fc_v2)} → v3 fc n={len(fc_v3)} (drop {len(dropped)})\n")
        f.write(f"Dropped: f_* (96 base, SHAP %0) + status grubu (4 feature)\n\n")
        f.write("## AUC + Brier karşılaştırma (test 2025+)\n\n")
        f.write("| Breed | Target | AUC_v2 | AUC_v3 | ΔAUC | Brier_v2 | Brier_v3 | ΔBrier |\n")
        f.write("|---|---|---|---|---|---|---|---|\n")
        for c in comparison:
            sig = '✓' if abs(c['d_auc']) < 0.003 else ('✓ iyi' if c['d_auc'] > 0 else '✗ kötü')
            f.write(f"| {c['breed']} | {c['target']} | {c['auc_v2']:.4f} | {c['auc_v3']:.4f} | "
                    f"{c['d_auc']:+.4f} | {c['brier_v2']:.4f} | {c['brier_v3']:.4f} | "
                    f"{c['d_brier']:+.4f} | {sig} |\n")
        # Verdict
        f.write("\n## Verdict\n\n")
        avg_d = np.mean([c['d_auc'] for c in comparison])
        keep_v3 = abs(avg_d) < 0.003
        f.write(f"- Mean ΔAUC = {avg_d:+.5f}\n")
        if keep_v3:
            f.write(f"- ✓ **v3'e geç** — performans v2 ile EŞIT (~%50 daha az feature, hızlı).\n")
        else:
            f.write(f"- ✗ **v2'de kal** — drop performansı bozdu.\n")

    print(f"\nRapor: {REP}", flush=True)


if __name__ == '__main__':
    main()
