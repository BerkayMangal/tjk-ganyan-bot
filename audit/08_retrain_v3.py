#!/usr/bin/env python3
"""ADIM 4 — TRAIN V3: XGB + LGBM (+ CatBoost) breed-split walk-forward ensemble.

retrain_v2.py'nin breed-split + temporal walk-forward sürümü.
Yeni feature seti = 96 base (CSV'de yoksa 0.0 fill) + DB whitelist (mf__/hsf__).

Çıktı: model/trained_v3/
  xgb_ranker_{arab,english}.pkl
  lgbm_ranker_{arab,english}.pkl
  cb_ranker_{arab,english}.pkl (varsa)
  xgb_prob_{arab,english}.pkl
  lgbm_prob_{arab,english}.pkl
  scaler_{arab,english}.pkl, scaler_prob_{arab,english}.pkl
  feature_columns.json
  train_meta_v3.json

Kullanım:
  python audit/08_retrain_v3.py
  python audit/08_retrain_v3.py --test-ratio 0.20 --agf-noise 0.05
"""
from __future__ import annotations
import sys
import os
import argparse
import json
import joblib
import logging
import warnings
from datetime import datetime

import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler
from sklearn.metrics import ndcg_score

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

warnings.filterwarnings('ignore', category=UserWarning)
logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV_IN = os.path.join(REPO, 'data', 'training_v3', 'races_v3.csv')
FC_IN = os.path.join(REPO, 'data', 'training_v3', 'feature_columns_v3.json')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v3')

AGF_FEATURES = [
    'f_agf_log', 'f_agf_implied_prob', 'f_agf_rank', 'f_agf_fav_margin',
    'f_race_odds_cv', 'f_odds_entropy', 'f_avg_winner_odds', 'f_fav1v2_gap',
    'f_X_surprise_agf', 'f_X_agf_form', 'f_X_agf_jockey',
]


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    if 'arap' in g:
        return 'arab'
    if 'ngiliz' in g:
        return 'english'
    return 'unknown'


def build_features(df, feature_cols):
    """CSV'de olan feature'lar olduğu gibi, eksikler 0.0 fill."""
    X = pd.DataFrame(index=df.index)
    for col in feature_cols:
        if col in df.columns:
            X[col] = pd.to_numeric(df[col], errors='coerce').fillna(0.0)
        else:
            X[col] = 0.0
    return X.values


def build_labels(df, method='exponential'):
    pos = df['finish_position'].values
    if method == 'exponential':
        return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)
    elif method == 'v1_compat':
        y = np.zeros(len(df))
        y[pos == 1] = 5
        y[pos == 2] = 3
        y[pos == 3] = 2
        y[pos == 4] = 1
        return y
    elif method == 'binary':
        return (pos == 1).astype(float)
    raise ValueError(method)


def temporal_split(df, test_ratio=0.20):
    dates = pd.Series(pd.to_datetime(df['race_date'])).sort_values().unique()
    idx = int(len(dates) * (1 - test_ratio))
    split_date = dates[idx]
    df['_rd'] = pd.to_datetime(df['race_date'])
    train = df[df['_rd'] < split_date].drop(columns='_rd').copy()
    test = df[df['_rd'] >= split_date].drop(columns='_rd').copy()
    return train, test, str(pd.Timestamp(split_date).date())


def train_xgb(X, y, groups, **kw):
    from xgboost import XGBRanker
    m = XGBRanker(
        objective='rank:pairwise', n_estimators=600, max_depth=5,
        learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
        min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbosity=0, **kw)
    m.fit(X, y, group=groups, verbose=False)
    return m


def train_lgbm(X, y, **kw):
    from lightgbm import LGBMRegressor
    m = LGBMRegressor(
        objective='regression_l2', n_estimators=600, max_depth=5,
        learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
        min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbose=-1, **kw)
    m.fit(X, y)
    return m


def train_catboost(X, y, groups):
    try:
        from catboost import CatBoostRanker, Pool
        group_ids = np.repeat(np.arange(len(groups)), groups)
        pool = Pool(data=X, label=y, group_id=group_ids)
        m = CatBoostRanker(
            iterations=500, depth=5, learning_rate=0.04,
            random_seed=42, verbose=0, loss_function='PairLogit',
            l2_leaf_reg=3.0)
        m.fit(pool)
        return m
    except Exception as e:
        logger.warning(f"CatBoost failed: {e}")
        return None


def eval_ranker(model, X, y, groups, scaler=None, name='Model'):
    if scaler is not None:
        X = scaler.transform(X)
    p = model.predict(X)
    n1, n3, t1, t3, n = [], [], 0, 0, 0
    o = 0
    for g in groups:
        g = int(g)
        if g < 2:
            o += g
            continue
        yg, pg = y[o:o+g], p[o:o+g]
        try:
            n1.append(ndcg_score([yg], [pg], k=1))
            n3.append(ndcg_score([yg], [pg], k=3))
        except Exception:
            pass
        widx = np.argmax(yg)
        rk = np.argsort(-pg)
        if rk[0] == widx:
            t1 += 1
        if widx in rk[:3]:
            t3 += 1
        n += 1
        o += g
    return {
        'ndcg1': float(np.mean(n1) if n1 else 0),
        'ndcg3': float(np.mean(n3) if n3 else 0),
        'top1_accuracy': t1 / max(n, 1),
        'top3_accuracy': t3 / max(n, 1),
        'n_races': n,
    }


def train_breed(df_breed, feature_cols, breed_label, label_method, test_ratio):
    logger.info(f"\n{'='*60}\nBREED: {breed_label} (n={len(df_breed)})\n{'='*60}")
    train_df, test_df, split_date = temporal_split(df_breed, test_ratio)
    y_train = build_labels(train_df, label_method)
    y_test = build_labels(test_df, label_method)

    X_train = build_features(train_df, feature_cols)
    X_test = build_features(test_df, feature_cols)

    groups_train = train_df.groupby('race_id').size().values
    groups_test = test_df.groupby('race_id').size().values

    sc = StandardScaler()
    X_train_s = sc.fit_transform(X_train)
    X_test_s = sc.transform(X_test)

    xgb = train_xgb(X_train_s, y_train, groups_train)
    lgbm = train_lgbm(X_train_s, y_train)
    cb = train_catboost(X_train_s, y_train, groups_train)

    # Binary prob model (kazanan vs gerisi) — ganyan value için
    y_bin_train = (train_df['finish_position'].values == 1).astype(float)
    sc_prob = StandardScaler()
    X_train_sp = sc_prob.fit_transform(X_train)
    X_test_sp = sc_prob.transform(X_test)

    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    xgb_prob = XGBClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.04,
        subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbosity=0, eval_metric='logloss',
        use_label_encoder=False,
    )
    xgb_prob.fit(X_train_sp, y_bin_train)
    lgbm_prob = LGBMClassifier(
        n_estimators=400, max_depth=5, learning_rate=0.04, num_leaves=31,
        subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
        random_state=42, verbose=-1)
    lgbm_prob.fit(X_train_sp, y_bin_train)

    e_xgb = eval_ranker(xgb, X_test_s, y_test, groups_test, name='XGB')
    e_lgbm = eval_ranker(lgbm, X_test_s, y_test, groups_test, name='LGBM')
    e_cb = eval_ranker(cb, X_test_s, y_test, groups_test, name='CB') if cb is not None else None

    def ensemble_predict(X_s):
        p1 = xgb.predict(X_s)
        p2 = lgbm.predict(X_s)
        n1 = (p1 - p1.min()) / (p1.max() - p1.min() + 1e-10)
        n2 = (p2 - p2.min()) / (p2.max() - p2.min() + 1e-10)
        if cb is not None:
            p3 = cb.predict(X_s)
            n3 = (p3 - p3.min()) / (p3.max() - p3.min() + 1e-10)
            return 0.40 * n1 + 0.35 * n2 + 0.25 * n3
        return 0.53 * n1 + 0.47 * n2

    class Proxy:
        def predict(self, X): return ensemble_predict(X)

    e_ens = eval_ranker(Proxy(), X_test_s, y_test, groups_test, name='ENSEMBLE')

    logger.info(f"  {breed_label} XGB:  ndcg@1={e_xgb['ndcg1']:.3f} top1={e_xgb['top1_accuracy']:.1%} top3={e_xgb['top3_accuracy']:.1%}")
    logger.info(f"  {breed_label} LGBM: ndcg@1={e_lgbm['ndcg1']:.3f} top1={e_lgbm['top1_accuracy']:.1%} top3={e_lgbm['top3_accuracy']:.1%}")
    if e_cb:
        logger.info(f"  {breed_label} CB:   ndcg@1={e_cb['ndcg1']:.3f} top1={e_cb['top1_accuracy']:.1%} top3={e_cb['top3_accuracy']:.1%}")
    logger.info(f"  {breed_label} ENS:  ndcg@1={e_ens['ndcg1']:.3f} top1={e_ens['top1_accuracy']:.1%} top3={e_ens['top3_accuracy']:.1%}")

    return {
        'breed': breed_label,
        'split_date': split_date,
        'train_records': len(train_df),
        'test_records': len(test_df),
        'eval': {'xgb': e_xgb, 'lgbm': e_lgbm, 'cb': e_cb, 'ensemble': e_ens},
        'models': {'xgb': xgb, 'lgbm': lgbm, 'cb': cb,
                   'xgb_prob': xgb_prob, 'lgbm_prob': lgbm_prob,
                   'scaler': sc, 'scaler_prob': sc_prob},
    }


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test-ratio', type=float, default=0.20)
    parser.add_argument('--label', default='exponential',
                        choices=['exponential', 'v1_compat', 'binary'])
    args = parser.parse_args()

    if not os.path.exists(CSV_IN):
        logger.error(f"CSV yok: {CSV_IN}")
        logger.error("Önce `python audit/07_dataset_pull.py` koşturun.")
        sys.exit(2)
    with open(FC_IN, 'r') as f:
        feature_cols = json.load(f)

    logger.info(f"Loading {CSV_IN}...")
    df = pd.read_csv(CSV_IN, low_memory=False)
    logger.info(f"  {len(df):,} satır, {df['race_id'].nunique():,} yarış")
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    logger.info(f"  Breed: arab={int((df['breed']=='arab').sum())} "
                f"english={int((df['breed']=='english').sum())} "
                f"unknown={int((df['breed']=='unknown').sum())}")

    os.makedirs(OUT_DIR, exist_ok=True)
    all_results = {}
    for breed_label in ('arab', 'english'):
        sub = df[df['breed'] == breed_label].copy()
        if len(sub) < 200:
            logger.warning(f"{breed_label}: only {len(sub)} rows — skip")
            continue
        res = train_breed(sub, feature_cols, breed_label, args.label, args.test_ratio)
        m = res['models']
        joblib.dump(m['xgb'], os.path.join(OUT_DIR, f'xgb_ranker_{breed_label}.pkl'))
        joblib.dump(m['lgbm'], os.path.join(OUT_DIR, f'lgbm_ranker_{breed_label}.pkl'))
        if m['cb'] is not None:
            joblib.dump(m['cb'], os.path.join(OUT_DIR, f'cb_ranker_{breed_label}.pkl'))
        joblib.dump(m['xgb_prob'], os.path.join(OUT_DIR, f'xgb_prob_{breed_label}.pkl'))
        joblib.dump(m['lgbm_prob'], os.path.join(OUT_DIR, f'lgbm_prob_{breed_label}.pkl'))
        joblib.dump(m['scaler'], os.path.join(OUT_DIR, f'scaler_{breed_label}.pkl'))
        joblib.dump(m['scaler_prob'], os.path.join(OUT_DIR, f'scaler_prob_{breed_label}.pkl'))
        all_results[breed_label] = {
            'split_date': res['split_date'],
            'train_records': res['train_records'],
            'test_records': res['test_records'],
            'eval': res['eval'],
        }

    with open(os.path.join(OUT_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(feature_cols, f, indent=2)
    meta = {
        'trained_at': datetime.now().isoformat(),
        'version': 'v3',
        'label_method': args.label,
        'test_ratio': args.test_ratio,
        'n_features': len(feature_cols),
        'breeds': all_results,
        'csv_source': CSV_IN,
    }
    with open(os.path.join(OUT_DIR, 'train_meta_v3.json'), 'w') as f:
        json.dump(meta, f, indent=2, default=str)
    logger.info(f"\n✅ trained_v3/ kaydedildi → {OUT_DIR}")
    logger.info(json.dumps(meta, indent=2, default=str)[:2000])


if __name__ == '__main__':
    main()
