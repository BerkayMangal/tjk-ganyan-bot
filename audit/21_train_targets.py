#!/usr/bin/env python3
"""5 binary target × 2 breed × XGB+LGBM ensemble — bet-type'a özel kalibre modeller.

Targets:
  top1 (Ganyan)  — finish_position == 1
  top2           — finish_position <= 2
  top3 (Plase)   — finish_position <= 3
  top4 (Tabela)  — finish_position <= 4
  top5           — finish_position <= 5

Per (target × breed AR/TB) × {XGB, LGBM} = 20 base + 10 isotonic kalibratör.
Plackett-Luce ranking head: top1 modelinden race-normalize ile türetilir.

Walk-forward: train 2021-2023 (in-sample), val 2024 (kalibrasyon-tune), test 2025+ (HOLDOUT).

OUTPUT:
  model/trained_targets/{top1..top5}/{xgb,lgbm}_{arab,english}.pkl
  model/trained_targets/{top1..top5}/isotonic_{arab,english}.pkl
  model/trained_targets/scaler_{arab,english}.pkl  (paylaşılan)
  model/trained_targets/feature_columns.json
  model/trained_targets/train_meta.json
"""
from __future__ import annotations
import os, sys, json, time
import warnings
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
OUT = os.path.join(ROOT, 'model', 'trained_targets')
os.makedirs(OUT, exist_ok=True)


def log(m):
    print(f"[{datetime.now().isoformat()}] {m}", flush=True)


def build_features(df, feature_cols):
    """CSV'de olan feature'lar, eksikler 0.0 fill."""
    X = pd.DataFrame(index=df.index)
    for c in feature_cols:
        X[c] = pd.to_numeric(df[c], errors='coerce').fillna(0.0) if c in df.columns else 0.0
    return X.values


def train_one(X_train, y_train, X_val, y_val, breed_label, target_name):
    """XGB + LGBM binary, validation üzerinde isotonic fit."""
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier

    xgb = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.04,
        subsample=0.85, colsample_bytree=0.75, reg_alpha=0.1, reg_lambda=2.0,
        min_child_weight=5, random_state=42, verbosity=0,
        eval_metric='logloss', use_label_encoder=False)
    xgb.fit(X_train, y_train)

    lgbm = LGBMClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.04, num_leaves=31,
        subsample=0.85, colsample_bytree=0.75, reg_alpha=0.1, reg_lambda=2.0,
        min_child_weight=5, random_state=42, verbose=-1)
    lgbm.fit(X_train, y_train)

    # Validation prob (ensemble) → isotonic
    p_xgb = xgb.predict_proba(X_val)[:, 1]
    p_lgbm = lgbm.predict_proba(X_val)[:, 1]
    p_ens = 0.5 * p_xgb + 0.5 * p_lgbm
    iso = IsotonicRegression(out_of_bounds='clip').fit(p_ens, y_val)
    p_cal = iso.transform(p_ens)
    p_cal = np.clip(p_cal, 1e-6, 1 - 1e-6)

    metrics = {
        'auc_xgb': float(roc_auc_score(y_val, p_xgb)) if y_val.sum() > 0 else None,
        'auc_lgbm': float(roc_auc_score(y_val, p_lgbm)) if y_val.sum() > 0 else None,
        'auc_ens': float(roc_auc_score(y_val, p_ens)) if y_val.sum() > 0 else None,
        'auc_cal': float(roc_auc_score(y_val, p_cal)) if y_val.sum() > 0 else None,
        'brier_cal': float(brier_score_loss(y_val, p_cal)),
        'logloss_cal': float(log_loss(y_val, p_cal)),
        'n_train': int(len(y_train)), 'n_val': int(len(y_val)),
        'pos_rate_train': float(y_train.mean()), 'pos_rate_val': float(y_val.mean()),
    }
    log(f"    {target_name}/{breed_label}: AUC {metrics['auc_cal']:.4f} "
        f"Brier {metrics['brier_cal']:.4f} LogLoss {metrics['logloss_cal']:.4f}")
    return xgb, lgbm, iso, metrics


def main():
    log("Loading dataset...")
    if not os.path.exists(FC_IN):
        log(f"FAIL: feature_columns_v3.json yok ({FC_IN})")
        sys.exit(2)
    with open(FC_IN) as f:
        feature_cols = json.load(f)
    df = pd.read_csv(CSV_IN, low_memory=False)
    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    g = df['group_name'].fillna('').str.lower()
    df['breed'] = np.where(g.str.contains('arap'), 'arab',
                           np.where(g.str.contains('ngiliz'), 'english', 'unknown'))
    log(f"  rows: {len(df):,} | breed: AR={int((df['breed']=='arab').sum()):,} "
        f"TB={int((df['breed']=='english').sum()):,}")

    # Walk-forward split
    train_df = df[df['race_date'] < '2024-01-01']
    val_df = df[(df['race_date'] >= '2024-01-01') & (df['race_date'] < '2025-01-01')]
    test_df = df[df['race_date'] >= '2025-01-01']
    log(f"  split: train n={len(train_df):,}  val n={len(val_df):,}  test n={len(test_df):,}")

    # Targets
    targets = {
        'top1': lambda y: (y == 1).astype(int),
        'top2': lambda y: (y <= 2).astype(int),
        'top3': lambda y: (y <= 3).astype(int),
        'top4': lambda y: (y <= 4).astype(int),
        'top5': lambda y: (y <= 5).astype(int),
    }

    meta = {'trained_at': datetime.utcnow().isoformat(), 'feature_n': len(feature_cols),
            'splits': {'train_n': len(train_df), 'val_n': len(val_df), 'test_n': len(test_df)},
            'metrics': {}}

    # Per breed
    for breed in ['arab', 'english']:
        tr_b = train_df[train_df['breed'] == breed]
        va_b = val_df[val_df['breed'] == breed]
        te_b = test_df[test_df['breed'] == breed]
        if len(tr_b) < 500:
            log(f"  {breed}: only {len(tr_b)} train — skip")
            continue
        log(f"  breed={breed}: train {len(tr_b):,} | val {len(va_b):,} | test {len(te_b):,}")
        # Shared scaler
        X_tr_raw = build_features(tr_b, feature_cols)
        X_va_raw = build_features(va_b, feature_cols)
        X_te_raw = build_features(te_b, feature_cols)
        scaler = StandardScaler().fit(X_tr_raw)
        X_tr = scaler.transform(X_tr_raw); X_va = scaler.transform(X_va_raw); X_te = scaler.transform(X_te_raw)
        joblib.dump(scaler, os.path.join(OUT, f'scaler_{breed}.pkl'))

        meta['metrics'][breed] = {}
        for tgt_name, tgt_fn in targets.items():
            tgt_dir = os.path.join(OUT, tgt_name)
            os.makedirs(tgt_dir, exist_ok=True)
            y_tr = tgt_fn(tr_b['finish_position'].values)
            y_va = tgt_fn(va_b['finish_position'].values)
            y_te = tgt_fn(te_b['finish_position'].values)
            log(f"  target={tgt_name} breed={breed} (pos_rate train={y_tr.mean():.3f})")
            xgb, lgbm, iso, m_val = train_one(X_tr, y_tr, X_va, y_va, breed, tgt_name)
            # Test (holdout) metric
            p_xgb_te = xgb.predict_proba(X_te)[:, 1]
            p_lgbm_te = lgbm.predict_proba(X_te)[:, 1]
            p_ens_te = 0.5 * p_xgb_te + 0.5 * p_lgbm_te
            p_cal_te = np.clip(iso.transform(p_ens_te), 1e-6, 1-1e-6)
            try:
                auc_te = float(roc_auc_score(y_te, p_cal_te))
                brier_te = float(brier_score_loss(y_te, p_cal_te))
                ll_te = float(log_loss(y_te, p_cal_te))
            except Exception:
                auc_te = brier_te = ll_te = None
            log(f"    [HOLDOUT] AUC {auc_te:.4f} Brier {brier_te:.4f}" if auc_te else "    [HOLDOUT] n/a")
            joblib.dump(xgb, os.path.join(tgt_dir, f'xgb_{breed}.pkl'))
            joblib.dump(lgbm, os.path.join(tgt_dir, f'lgbm_{breed}.pkl'))
            joblib.dump(iso, os.path.join(tgt_dir, f'isotonic_{breed}.pkl'))
            meta['metrics'][breed][tgt_name] = {
                **m_val,
                'auc_test': auc_te, 'brier_test': brier_te, 'logloss_test': ll_te,
                'n_test': int(len(y_te)), 'pos_rate_test': float(y_te.mean()),
            }

    with open(os.path.join(OUT, 'feature_columns.json'), 'w') as f:
        json.dump(feature_cols, f, indent=2)
    with open(os.path.join(OUT, 'train_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    log(f"DONE — model/trained_targets/")


if __name__ == '__main__':
    main()
