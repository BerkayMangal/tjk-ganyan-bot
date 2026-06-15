#!/usr/bin/env python3
"""V5 retrain — 78 (v4) + 3 jokey conditional = 81 feature.

Berkay (2026-06-15): "retrain — model kalitesini artıracağını çok net düşünüyorum".

Compare vs v4 (paired AUC + Brier + ECE) on hold-out test set.
- Train: <2024-01-01
- Val:   2024-01-01 .. 2025-01-01 (isotonic calibration)
- Test:  >=2025-01-01 (paired metrics)

5 target (top1..top5) × 2 breed (arab/english) = 10 ensemble.
XGB + LGBM (audit/42 ile aynı hyperparam, sadece feature set genişler).

OUTPUT:
  model/trained_targets_v5/{feature_columns.json, scaler_*.pkl, top*/xgb|lgbm|isotonic_*.pkl}
  audit/reports/phase_5_8_10_v5_train.md  (v4 vs v5 karşılaştırma)
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
CSV_IN = os.path.join(ROOT, 'data', 'training_v5', 'races_v5.csv')
FORM_CSV = os.path.join(ROOT, 'data', 'form', 'horse_form_pit.csv')
V4 = os.path.join(ROOT, 'model', 'trained_targets_v4')
V5 = os.path.join(ROOT, 'model', 'trained_targets_v5')
REP = os.path.join(ROOT, 'audit', 'reports', 'phase_5_8_10_v5_train.md')

NEW_FEATURES = ['mf__jockey_cond_top4', 'mf__jockey_cond_win', 'mf__jockey_cond_n']


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
    return (xgb, lgbm, iso,
            float(roc_auc_score(y_te, p_cal)),
            float(brier_score_loss(y_te, p_cal)),
            ece(y_te, p_cal), p_cal)


def main():
    os.makedirs(V5, exist_ok=True)
    log("Loading v4 fc...")
    with open(os.path.join(V4, 'feature_columns.json')) as f:
        fc_v4 = json.load(f)
    fc_v5 = fc_v4 + NEW_FEATURES
    log(f"  v4 fc n={len(fc_v4)} → v5 fc n={len(fc_v5)} (+{len(NEW_FEATURES)} jokey cond)")

    log(f"Loading {CSV_IN} (188 MB, 30-60s) ...")
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                            np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    log(f"  rows: {len(df):,} | arab: {(df.breed=='arab').sum():,} | english: {(df.breed=='english').sum():,}")

    log("Form merge...")
    form = pd.read_csv(FORM_CSV, parse_dates=['race_date'])
    form_cols = ['last_race_finish','avg_finish_last3','avg_finish_last5','avg_finish_last10',
                 'win_rate_last10','top3_rate_last10','days_since_last_race','races_in_last_180d']
    df = df.merge(form[['race_horse_id']+form_cols], on='race_horse_id', how='left')
    df[form_cols] = df[form_cols].fillna(0.0)

    train = df[df['race_date'] < '2024-01-01']
    val   = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test  = df[df['race_date'] >= '2025-01-01']
    log(f"  splits — train: {len(train):,} | val: {len(val):,} | test: {len(test):,}")

    targets = {'top1':1, 'top2':2, 'top3':3, 'top4':4, 'top5':5}
    rows = []

    for breed in ['arab', 'english']:
        log(f"\n=== breed={breed} ===")
        tr_b = train[train['breed']==breed]
        va_b = val[val['breed']==breed]
        te_b = test[test['breed']==breed]
        log(f"  train={len(tr_b):,} val={len(va_b):,} test={len(te_b):,}")

        sc_v5 = StandardScaler().fit(build_X(tr_b, fc_v5))
        joblib.dump(sc_v5, os.path.join(V5, f'scaler_{breed}.pkl'))
        X_tr_v5 = sc_v5.transform(build_X(tr_b, fc_v5))
        X_va_v5 = sc_v5.transform(build_X(va_b, fc_v5))
        X_te_v5 = sc_v5.transform(build_X(te_b, fc_v5))

        sc_v4 = joblib.load(os.path.join(V4, f'scaler_{breed}.pkl'))
        X_te_v4 = sc_v4.transform(build_X(te_b, fc_v4))

        for tname, k in targets.items():
            tdir = os.path.join(V5, tname); os.makedirs(tdir, exist_ok=True)
            y_tr = (tr_b['finish_position'].values <= k).astype(int)
            y_va = (va_b['finish_position'].values <= k).astype(int)
            y_te = (te_b['finish_position'].values <= k).astype(int)

            log(f"  fit {tname}...")
            xgb_v5, lgbm_v5, iso_v5, auc_v5, br_v5, ece_v5, p_v5 = fit_eval(
                X_tr_v5, y_tr, X_va_v5, y_va, X_te_v5, y_te)
            joblib.dump(xgb_v5, os.path.join(tdir, f'xgb_{breed}.pkl'))
            joblib.dump(lgbm_v5, os.path.join(tdir, f'lgbm_{breed}.pkl'))
            joblib.dump(iso_v5, os.path.join(tdir, f'isotonic_{breed}.pkl'))

            # v4 paired (aynı test set)
            xgb_v4 = joblib.load(os.path.join(V4, tname, f'xgb_{breed}.pkl'))
            lgbm_v4 = joblib.load(os.path.join(V4, tname, f'lgbm_{breed}.pkl'))
            iso_v4 = joblib.load(os.path.join(V4, tname, f'isotonic_{breed}.pkl'))
            p4 = 0.5*xgb_v4.predict_proba(X_te_v4)[:,1] + 0.5*lgbm_v4.predict_proba(X_te_v4)[:,1]
            p4_cal = np.clip(iso_v4.transform(p4), 1e-6, 1-1e-6)
            auc_v4 = float(roc_auc_score(y_te, p4_cal))
            br_v4 = float(brier_score_loss(y_te, p4_cal))
            ece_v4 = ece(y_te, p4_cal)

            rows.append({
                'breed': breed, 'target': tname,
                'auc_v4': auc_v4, 'auc_v5': auc_v5, 'd_auc': auc_v5 - auc_v4,
                'brier_v4': br_v4, 'brier_v5': br_v5, 'd_brier': br_v5 - br_v4,
                'ece_v4': ece_v4, 'ece_v5': ece_v5, 'd_ece': ece_v5 - ece_v4,
                'n_test': int(len(y_te)),
            })
            sign_auc = '✓' if auc_v5 > auc_v4 else '✗'
            log(f"    {sign_auc} v5 AUC={auc_v5:.4f} (v4 {auc_v4:.4f}, Δ {auc_v5-auc_v4:+.4f}) | "
                f"Brier {br_v5:.4f} (v4 {br_v4:.4f}, Δ {br_v5-br_v4:+.4f}) | "
                f"ECE {ece_v5:.4f} (v4 {ece_v4:.4f}, Δ {ece_v5-ece_v4:+.4f})")

    # Save artifacts
    with open(os.path.join(V5, 'feature_columns.json'), 'w') as f:
        json.dump(fc_v5, f, indent=2, ensure_ascii=False)
    with open(os.path.join(V5, 'train_meta.json'), 'w') as f:
        json.dump({
            'trained_at': datetime.utcnow().isoformat(),
            'n_features': len(fc_v5),
            'new_features': NEW_FEATURES,
            'compare_vs': 'v4',
            'comparison': rows,
        }, f, indent=2, default=str, ensure_ascii=False)

    # Report
    mean_d_auc = sum(r['d_auc'] for r in rows) / len(rows)
    mean_d_brier = sum(r['d_brier'] for r in rows) / len(rows)
    mean_d_ece = sum(r['d_ece'] for r in rows) / len(rows)
    won_auc = sum(1 for r in rows if r['d_auc'] > 0)
    won_brier = sum(1 for r in rows if r['d_brier'] < 0)
    won_ece = sum(1 for r in rows if r['d_ece'] < 0)

    with open(REP, 'w', encoding='utf-8') as f:
        f.write("# Phase 5.8.10 — V5 Retrain Raporu (jokey conditional)\n\n")
        f.write(f"_Tarih: {datetime.utcnow().isoformat()}Z_\n\n")
        f.write(f"## Özet\n\n")
        f.write(f"- Feature: v4 {len(fc_v4)} → v5 {len(fc_v5)} (+{len(NEW_FEATURES)} jokey conditional)\n")
        f.write(f"- Train: <2024 ({len(train):,} satır) | Val: 2024 ({len(val):,}) | Test: >=2025 ({len(test):,})\n")
        f.write(f"- Ortalama ΔAUC: **{mean_d_auc:+.4f}** ({won_auc}/{len(rows)} v5 üstün)\n")
        f.write(f"- Ortalama ΔBrier: **{mean_d_brier:+.4f}** ({won_brier}/{len(rows)} v5 üstün)\n")
        f.write(f"- Ortalama ΔECE: **{mean_d_ece:+.4f}** ({won_ece}/{len(rows)} v5 üstün)\n\n")
        f.write("## Per-target paired metrikler (v4 vs v5, test set ≥2025)\n\n")
        f.write("| Breed | Target | AUC_v4 | AUC_v5 | ΔAUC | Brier_v4 | Brier_v5 | ΔBrier | ECE_v4 | ECE_v5 | ΔECE | n_test |\n")
        f.write("|---|---|---|---|---|---|---|---|---|---|---|---|\n")
        for r in rows:
            f.write(f"| {r['breed']} | {r['target']} | "
                    f"{r['auc_v4']:.4f} | {r['auc_v5']:.4f} | {r['d_auc']:+.4f} | "
                    f"{r['brier_v4']:.4f} | {r['brier_v5']:.4f} | {r['d_brier']:+.4f} | "
                    f"{r['ece_v4']:.4f} | {r['ece_v5']:.4f} | {r['d_ece']:+.4f} | "
                    f"{r['n_test']:,} |\n")
        f.write("\n## Karar\n\n")
        if mean_d_auc > 0.001 and mean_d_brier < 0:
            f.write("**✓ v5 v4'ten ÜSTÜN** — shadow deploy + paired forward 2 hafta.\n")
        elif mean_d_auc > -0.001:
            f.write("**⚠ v5 v4 ile EŞDEĞER** — ekstra feature kazanç vermedi, shadow gözlem önerilir.\n")
        else:
            f.write("**✗ v5 v4'ten KÖTÜ** — feature seti yeniden değerlendirilmeli.\n")
        f.write(f"\nv5 artifactlar: `{V5}/`\n")
    log(f"\n✓ {V5}/")
    log(f"✓ {REP}")


if __name__ == '__main__':
    main()
