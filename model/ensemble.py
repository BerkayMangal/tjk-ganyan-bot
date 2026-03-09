"""
Ensemble Model — 3-Model Ranker (XGB + LGBM + CatBoost)
=========================================================
Railway'deki pkl dosyalarını yükle, 82 feature al, sıralama skoru döndür.
"""
import os
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trained')
WEIGHTS = (0.40, 0.35, 0.25)  # XGB, LGBM, CB


class EnsembleRanker:
    """3-model ensemble ranker for TJK horse racing."""

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or MODEL_DIR
        self.xgb = None
        self.lgbm = None
        self.cb = None
        self.scaler = None
        self.feature_cols = None
        self.loaded = False

    def load(self):
        """Load all model files from disk."""
        import joblib

        try:
            self.xgb = joblib.load(os.path.join(self.model_dir, 'xgb_ranker.pkl'))
            self.lgbm = joblib.load(os.path.join(self.model_dir, 'lgbm_ranker.pkl'))
            self.scaler = joblib.load(os.path.join(self.model_dir, 'scaler.pkl'))

            # Feature columns
            json_path = os.path.join(self.model_dir, 'feature_columns.json')
            if os.path.exists(json_path):
                with open(json_path) as f:
                    self.feature_cols = json.load(f)
            else:
                self.feature_cols = joblib.load(
                    os.path.join(self.model_dir, 'feature_cols.pkl')
                )

            # CatBoost optional
            cb_path = os.path.join(self.model_dir, 'cb_ranker.pkl')
            if os.path.exists(cb_path):
                self.cb = joblib.load(cb_path)

            self.loaded = True
            logger.info(
                f"Model loaded: {len(self.feature_cols)} features, "
                f"CB={'OK' if self.cb else 'MISSING'}"
            )
            return True

        except Exception as e:
            logger.error(f"Model load failed: {e}")
            self.loaded = False
            return False

    def predict(self, feature_matrix):
        """
        Ensemble predict: returns normalized 0-1 scores.

        Args:
            feature_matrix: numpy array (n_horses, n_features) in correct column order

        Returns:
            numpy array of scores (higher = better)
        """
        if not self.loaded:
            raise RuntimeError("Model not loaded! Call load() first.")

        X_s = self.scaler.transform(feature_matrix)

        xgb_raw = self.xgb.predict(X_s)
        lgbm_raw = self.lgbm.predict(X_s)

        xgb_n = self._norm01(xgb_raw)
        lgbm_n = self._norm01(lgbm_raw)

        if self.cb is not None:
            cb_raw = self.cb.predict(X_s)
            cb_n = self._norm01(cb_raw)
            scores = (WEIGHTS[0] * xgb_n +
                      WEIGHTS[1] * lgbm_n +
                      WEIGHTS[2] * cb_n)
        else:
            w_total = WEIGHTS[0] + WEIGHTS[1]
            scores = (WEIGHTS[0] * xgb_n + WEIGHTS[1] * lgbm_n) / w_total

        return scores

    def predict_individual(self, feature_matrix):
        """
        Her modelin ayrı ayrı top-1 seçimini döndür (model agreement için).

        Returns: dict with top indices per model
        """
        if not self.loaded:
            return {}

        X_s = self.scaler.transform(feature_matrix)

        result = {
            'xgb_top_idx': int(np.argmax(self.xgb.predict(X_s))),
            'lgbm_top_idx': int(np.argmax(self.lgbm.predict(X_s))),
        }
        if self.cb is not None:
            result['cb_top_idx'] = int(np.argmax(self.cb.predict(X_s)))

        return result

    @staticmethod
    def _norm01(arr):
        """Normalize array to 0-1 range."""
        mn, mx = arr.min(), arr.max()
        if mx - mn < 1e-8:
            return np.full_like(arr, 0.5)
        return (arr - mn) / (mx - mn)
