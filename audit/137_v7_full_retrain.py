#!/usr/bin/env python3
"""V7 FULL retrain — NO test cutoff, tüm 245K satır TRAIN'e dahil.

Berkay (2026-06-19): "full data setle retrain edilmis model".

audit/116 V7 train cutoff=2025-05-24 ile yapılmıştı (test set ≥ 5-24).
Bu script TÜM datayı train'e dahil eder → production model maksimum
güçlü hale gelir. Test sonucu YOK (zaten audit/116 paired sonucu var).

Output: model/trained_v7_225/ üzerine yazılır (mevcut backup'lı).
"""
from __future__ import annotations
import sys, os, json, joblib, logging, warnings
from datetime import datetime
import numpy as np
import pandas as pd
from sklearn.preprocessing import StandardScaler

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
warnings.filterwarnings('ignore')
logging.basicConfig(level=logging.INFO, format='%(asctime)s %(message)s')
logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CSV = os.path.join(REPO, 'data', 'training_v7', 'races_v7.csv')
FC = os.path.join(REPO, 'data', 'training_v7', 'feature_columns_v7.json')
OUT_DIR = os.path.join(REPO, 'model', 'trained_v7_225')


def detect_breed(row):
    g = str(row.get('group_name', '') or '').lower()
    return 'arab' if 'arap' in g else ('english' if 'ngiliz' in g else 'unknown')


def build_X(df, cols):
    pieces = [pd.to_numeric(df[c], errors='coerce').fillna(0.0)
              if c in df.columns else pd.Series(0.0, index=df.index, name=c)
              for c in cols]
    return pd.concat(pieces, axis=1).values


def y_rank(df):
    pos = df['finish_position'].values
    return np.where(pos > 0, 1.0 / (pos ** 0.7), 0.0)


def fit_breed(df_breed, fc, breed):
    logger.info(f"\n=== {breed.upper()} FULL TRAIN n={len(df_breed):,} ===")
    X = build_X(df_breed, fc)
    y = y_rank(df_breed)
    g = df_breed.groupby('race_id').size().values

    sc = StandardScaler().fit(X)
    sc_p = StandardScaler().fit(X)
    X_s = sc.transform(X)

    # Ranker ensemble
    from xgboost import XGBRanker
    from lightgbm import LGBMRegressor
    xgb = XGBRanker(objective='rank:pairwise', n_estimators=600, max_depth=5,
                    learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                    min_child_weight=5, gamma=0.1, reg_alpha=0.1, reg_lambda=2.0,
                    random_state=42, verbosity=0)
    xgb.fit(X_s, y, group=g)
    lgbm = LGBMRegressor(objective='regression_l2', n_estimators=600, max_depth=5,
                         learning_rate=0.035, subsample=0.80, colsample_bytree=0.70,
                         min_child_weight=5, num_leaves=31, reg_alpha=0.1, reg_lambda=2.0,
                         random_state=42, verbose=-1)
    lgbm.fit(X_s, y)
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        gids = np.repeat(np.arange(len(g)), g)
        cb = CatBoostRanker(iterations=500, depth=5, learning_rate=0.04,
                             random_seed=42, verbose=0, loss_function='PairLogit',
                             l2_leaf_reg=3.0)
        cb.fit(Pool(data=X_s, label=y, group_id=gids))
    except Exception as e:
        logger.warning(f"CB skip: {e}")

    # Prob classifier
    from xgboost import XGBClassifier
    from lightgbm import LGBMClassifier
    y_b = (df_breed['finish_position'].values == 1).astype(float)
    X_sp = sc_p.transform(X)
    xgb_p = XGBClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                          subsample=0.8, colsample_bytree=0.7, reg_alpha=0.1, reg_lambda=2.0,
                          random_state=42, verbosity=0, eval_metric='logloss',
                          use_label_encoder=False)
    xgb_p.fit(X_sp, y_b)
    lgbm_p = LGBMClassifier(n_estimators=400, max_depth=5, learning_rate=0.04,
                             num_leaves=31, subsample=0.8, colsample_bytree=0.7,
                             reg_alpha=0.1, reg_lambda=2.0, random_state=42, verbose=-1)
    lgbm_p.fit(X_sp, y_b)

    # Save
    joblib.dump(xgb, os.path.join(OUT_DIR, f'xgb_ranker_{breed}.pkl'))
    joblib.dump(lgbm, os.path.join(OUT_DIR, f'lgbm_ranker_{breed}.pkl'))
    if cb is not None: joblib.dump(cb, os.path.join(OUT_DIR, f'cb_ranker_{breed}.pkl'))
    joblib.dump(xgb_p, os.path.join(OUT_DIR, f'xgb_prob_{breed}.pkl'))
    joblib.dump(lgbm_p, os.path.join(OUT_DIR, f'lgbm_prob_{breed}.pkl'))
    joblib.dump(sc, os.path.join(OUT_DIR, f'scaler_{breed}.pkl'))
    joblib.dump(sc_p, os.path.join(OUT_DIR, f'scaler_prob_{breed}.pkl'))
    logger.info(f"  ✓ {breed} 7 model dosyası kaydedildi")


def main():
    logger.info(f"Loading {CSV}...")
    df = pd.read_csv(CSV, low_memory=False)
    df = df[df['finish_position'].notna() & (df['finish_position'] > 0)].reset_index(drop=True)
    df['breed'] = df.apply(detect_breed, axis=1)
    with open(FC) as f: fc = json.load(f)
    logger.info(f"  rows={len(df):,}  fc={len(fc)}")

    os.makedirs(OUT_DIR, exist_ok=True)
    for breed in ('arab', 'english'):
        sub = df[df['breed'] == breed]
        if len(sub) < 200: continue
        fit_breed(sub, fc, breed)

    # Update meta
    meta = {
        'trained_at': datetime.now().isoformat(),
        'trained_with': 'FULL DATA — NO test cutoff (audit/137)',
        'n_total': len(df),
        'n_arab': len(df[df['breed']=='arab']),
        'n_english': len(df[df['breed']=='english']),
        'fc_count': len(fc),
        'cutoff': 'NONE (all data train)',
    }
    with open(os.path.join(OUT_DIR, 'feature_columns.json'), 'w') as f:
        json.dump(fc, f, indent=2)
    with open(os.path.join(OUT_DIR, 'train_meta.json'), 'w') as f:
        json.dump(meta, f, indent=2)
    logger.info(f"\n✓ V7 FULL retrain bitti: {OUT_DIR}")


if __name__ == '__main__':
    main()
