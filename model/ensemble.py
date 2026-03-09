"""3-Model Ensemble: XGBRanker + LGBMRanker + CatBoostRanker — V4"""
import joblib
import numpy as np
import pandas as pd
import os
import logging
from config import MODEL_DIR

logger = logging.getLogger(__name__)


class EnsembleRanker:
    """Load and predict with 3-model ensemble"""

    def __init__(self, model_dir=MODEL_DIR):
        self.model_dir = model_dir
        self.xgb = None
        self.lgbm = None
        self.cb = None
        self.scaler = None
        self.feature_cols = None
        self.weights = (0.40, 0.35, 0.25)

    def load(self):
        """Load trained models from disk"""
        logger.info(f"Loading models from {self.model_dir}")

        self.xgb = joblib.load(os.path.join(self.model_dir, 'xgb_ranker.pkl'))
        self.lgbm = joblib.load(os.path.join(self.model_dir, 'lgbm_ranker.pkl'))
        self.scaler = joblib.load(os.path.join(self.model_dir, 'scaler.pkl'))
        self.feature_cols = joblib.load(os.path.join(self.model_dir, 'feature_cols.pkl'))

        cb_path = os.path.join(self.model_dir, 'cb_ranker.pkl')
        if os.path.exists(cb_path):
            self.cb = joblib.load(cb_path)
            logger.info(f"Loaded: XGB + LGBM + CatBoost ({len(self.feature_cols)} features)")
        else:
            logger.info(f"Loaded: XGB + LGBM (no CatBoost) ({len(self.feature_cols)} features)")

    def _prepare_features(self, df):
        """
        Prepare feature matrix from DataFrame.
        Handles missing features by filling with 0.0.
        """
        # Check which features are missing
        missing = [f for f in self.feature_cols if f not in df.columns]
        if missing:
            logger.warning(f"Missing {len(missing)} features, filling with 0: {missing[:5]}{'...' if len(missing)>5 else ''}")
            for feat in missing:
                df[feat] = 0.0

        # Select features in correct order
        X = df[self.feature_cols].values.astype(np.float64)

        # Replace any NaN/inf
        X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

        return X

    def predict(self, df):
        """
        Predict ranking scores for horses in a race.
        df: DataFrame with feature columns
        Returns: np.array of ensemble scores (higher = better)
        """
        X = self._prepare_features(df)
        X_s = self.scaler.transform(X)

        # XGB and LGBM work with numpy arrays
        xgb_sc = self.xgb.predict(X_s)
        lgbm_sc = self.lgbm.predict(X_s)

        xgb_n = self._norm01(xgb_sc)
        lgbm_n = self._norm01(lgbm_sc)

        if self.cb is not None:
            # CatBoost needs DataFrame with column names
            X_s_df = pd.DataFrame(X_s, columns=self.feature_cols)
            cb_sc = self.cb.predict(X_s_df)
            cb_n = self._norm01(cb_sc)
            scores = self.weights[0] * xgb_n + self.weights[1] * lgbm_n + self.weights[2] * cb_n
        else:
            w = self.weights[0] + self.weights[1]
            scores = (self.weights[0] * xgb_n + self.weights[1] * lgbm_n) / w

        return scores

    def predict_individual(self, df):
        """Get individual model predictions (for agreement check)"""
        X = self._prepare_features(df)
        X_s = self.scaler.transform(X)

        xgb_sc = self.xgb.predict(X_s)
        lgbm_sc = self.lgbm.predict(X_s)

        result = {
            'xgb_top_idx': np.argmax(xgb_sc),
            'lgbm_top_idx': np.argmax(lgbm_sc),
        }

        if self.cb is not None:
            X_s_df = pd.DataFrame(X_s, columns=self.feature_cols)
            cb_sc = self.cb.predict(X_s_df)
            result['cb_top_idx'] = np.argmax(cb_sc)
        else:
            result['cb_top_idx'] = result['lgbm_top_idx']

        return result

    @staticmethod
    def _norm01(s):
        r = s.max() - s.min()
        return (s - s.min()) / (r + 1e-8) if r > 0 else np.full_like(s, 0.5)
