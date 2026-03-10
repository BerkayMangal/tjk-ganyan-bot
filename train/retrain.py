"""Weekly Model Retrain Script
Retrains 3-model ensemble on latest data.
Run: python train/retrain.py --data races_latest.csv --horses taydex_horses.csv
"""
import sys, os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import argparse
import joblib
import pandas as pd
import numpy as np
from xgboost import XGBRanker
from lightgbm import LGBMRanker
from sklearn.preprocessing import StandardScaler
import logging

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


def retrain(races_csv, horses_csv, output_dir):
    """Full retrain pipeline"""
    # Load feature columns from the trained model's JSON (same source of truth as inference)
    import json
    feat_cols_json = os.path.join(output_dir, 'feature_columns.json')
    if os.path.exists(feat_cols_json):
        with open(feat_cols_json) as f:
            FEATURE_COLUMNS = json.load(f)
        logger.info(f"Loaded {len(FEATURE_COLUMNS)} feature columns from {feat_cols_json}")
    else:
        logger.error(f"feature_columns.json not found in {output_dir}!")
        logger.error("Run initial training first (e.g. from Colab) to generate this file.")
        return

    logger.info(f"Loading {races_csv} and {horses_csv}")
    # Load and merge (same as training pipeline)
    df_races = pd.read_csv(races_csv, low_memory=False)
    df_horses = pd.read_csv(horses_csv)

    hcols = [c for c in ['name','sire_sire','sire_dam','dam_dam','total_earnings','best_time','birth_date'] if c in df_horses.columns]
    df = df_races.merge(df_horses[hcols], left_on='horse_name', right_on='name', how='left', suffixes=('','_h'))
    if 'total_earnings_h' in df.columns:
        df['total_earnings'] = df['total_earnings'].fillna(df['total_earnings_h'])

    df['race_date'] = pd.to_datetime(df['race_date'])
    df = df.sort_values(['race_date','race_id','finish_position']).reset_index(drop=True)
    df = df[df['finish_position'].notna() & (df['finish_position']>0)].reset_index(drop=True)

    logger.info(f"Training data: {len(df):,} records")

    # Build features (using the full pipeline from features.py)
    # For retrain, we need the full feature engineering — import from Colab training script
    # This is a simplified version; in production, share the exact pipeline

    # Prepare ranking labels
    y = np.zeros(len(df))
    y[df['finish_position']==1] = 5
    y[df['finish_position']==2] = 3
    y[df['finish_position']==3] = 2
    y[df['finish_position']==4] = 1
    groups = df.groupby('race_id').size().values

    # Feature columns to use (from feature selection)
    feature_cols_path = os.path.join(output_dir, 'feature_cols.pkl')
    if os.path.exists(feature_cols_path):
        feat_cols = joblib.load(feature_cols_path)
    else:
        feat_cols = [c for c in FEATURE_COLUMNS if c in df.columns]

    X = df[feat_cols].fillna(0).values
    scaler = StandardScaler()
    X_s = scaler.fit_transform(X)

    # Train XGBRanker
    logger.info("Training XGBRanker...")
    xgb = XGBRanker(
        objective='rank:pairwise', n_estimators=500, max_depth=5,
        learning_rate=0.04, subsample=0.85, colsample_bytree=0.75,
        min_child_weight=4, gamma=0.05, reg_alpha=0.05, reg_lambda=1.5,
        random_state=42, verbosity=0
    )
    xgb.fit(X_s, y, group=groups, verbose=False)

    # Train LGBMRanker
    logger.info("Training LGBMRanker...")
    lgbm = LGBMRanker(
        objective='lambdarank', n_estimators=500, max_depth=5,
        learning_rate=0.04, subsample=0.85, colsample_bytree=0.75,
        min_child_weight=4, num_leaves=31, random_state=42, verbose=-1
    )
    lgbm.fit(X_s, y, group=groups)

    # Train CatBoostRanker
    cb = None
    try:
        from catboost import CatBoostRanker, Pool
        logger.info("Training CatBoostRanker...")
        group_ids = np.repeat(np.arange(len(groups)), groups)
        cb_pool = Pool(data=X_s, label=y, group_id=group_ids)
        cb = CatBoostRanker(
            iterations=400, depth=5, learning_rate=0.05,
            random_seed=42, verbose=0, loss_function='PairLogit'
        )
        cb.fit(cb_pool)
    except Exception as e:
        logger.warning(f"CatBoost failed: {e}")

    # Save
    os.makedirs(output_dir, exist_ok=True)
    joblib.dump(xgb, os.path.join(output_dir, 'xgb_ranker.pkl'))
    joblib.dump(lgbm, os.path.join(output_dir, 'lgbm_ranker.pkl'))
    joblib.dump(scaler, os.path.join(output_dir, 'scaler.pkl'))
    joblib.dump(feat_cols, os.path.join(output_dir, 'feature_cols.pkl'))
    # Keep feature_columns.json in sync (used by inference FeatureBuilder)
    import json
    with open(os.path.join(output_dir, 'feature_columns.json'), 'w') as f:
        json.dump(feat_cols, f)
    if cb:
        joblib.dump(cb, os.path.join(output_dir, 'cb_ranker.pkl'))

    logger.info(f"Models saved to {output_dir}")
    logger.info(f"  XGB: OK | LGBM: OK | CB: {'OK' if cb else 'FAIL'}")
    logger.info(f"  Features: {len(feat_cols)} | Scaler: OK")


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data', required=True, help='Path to races CSV')
    parser.add_argument('--horses', required=True, help='Path to horses CSV')
    parser.add_argument('--output', default='model/trained', help='Output directory')
    args = parser.parse_args()

    retrain(args.data, args.horses, args.output)
