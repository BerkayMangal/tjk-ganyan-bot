"""
Ensemble Model — 4-Model Ranker (XGB + LGBM + CatBoost + AGF-Ablated)
========================================================================
Railway'deki pkl dosyalarını yükle, 82 feature al, sıralama skoru döndür.

V2: AGF-ablated model eklendi (4. ensemble üyesi, opsiyonel).
    Ablated model sadece non-AGF feature'larla çalışır.
    AGF verisi yoksa/güvenilmezse ablated modele daha çok ağırlık verilir.
"""
import os
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)

MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trained')

# Ağırlıklar: normal mod (AGF var) vs AGF-güvenilmez mod
WEIGHTS_NORMAL = (0.35, 0.30, 0.20, 0.15)  # XGB, LGBM, CB, Ablated
WEIGHTS_NO_CB = (0.40, 0.35, 0.0, 0.25)     # CB yokken
WEIGHTS_NO_ABL = (0.40, 0.35, 0.25, 0.0)    # Ablated yokken (V1 compat)

# AGF-related features (ablated modelden çıkarılanlar)
AGF_RELATED_FEATURES = {
    'f_agf_log', 'f_agf_implied_prob', 'f_agf_rank', 'f_agf_fav_margin',
    'f_race_odds_cv', 'f_odds_entropy', 'f_avg_winner_odds', 'f_fav1v2_gap',
    'f_X_surprise_agf', 'f_X_agf_form', 'f_X_agf_jockey',
}


class EnsembleRanker:
    """4-model ensemble ranker for TJK horse racing."""

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or MODEL_DIR
        self.xgb = None
        self.lgbm = None
        self.cb = None
        self.ablated = None
        self.scaler = None
        self.feature_cols = None
        self.ablated_cols = None
        self.ablated_indices = None  # mapping: ablated feature → full feature matrix index
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

            # AGF-Ablated model optional (V2)
            abl_path = os.path.join(self.model_dir, 'ablated_ranker.pkl')
            abl_cols_path = os.path.join(self.model_dir, 'ablated_columns.json')
            if os.path.exists(abl_path) and os.path.exists(abl_cols_path):
                self.ablated = joblib.load(abl_path)
                with open(abl_cols_path) as f:
                    self.ablated_cols = json.load(f)
                # Pre-compute index mapping
                self.ablated_indices = [
                    self.feature_cols.index(c)
                    for c in self.ablated_cols
                    if c in self.feature_cols
                ]

            self.loaded = True
            logger.info(
                f"Model loaded: {len(self.feature_cols)} features, "
                f"CB={'OK' if self.cb else 'YOK'}, "
                f"Ablated={'OK' if self.ablated else 'YOK'}"
            )
            return True

        except Exception as e:
            logger.error(f"Model load failed: {e}")
            self.loaded = False
            return False

    def _get_weights(self):
        """Mevcut modellere göre ağırlık seç."""
        has_cb = self.cb is not None
        has_abl = self.ablated is not None

        if has_cb and has_abl:
            return WEIGHTS_NORMAL
        elif has_cb and not has_abl:
            return WEIGHTS_NO_ABL
        elif not has_cb and has_abl:
            return WEIGHTS_NO_CB
        else:
            # Sadece XGB + LGBM
            return (0.53, 0.47, 0.0, 0.0)

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
        weights = self._get_weights()

        xgb_n = self._norm01(self.xgb.predict(X_s))
        lgbm_n = self._norm01(self.lgbm.predict(X_s))

        scores = weights[0] * xgb_n + weights[1] * lgbm_n

        if self.cb is not None and weights[2] > 0:
            cb_n = self._norm01(self.cb.predict(X_s))
            scores += weights[2] * cb_n

        if self.ablated is not None and weights[3] > 0 and self.ablated_indices:
            X_abl = X_s[:, self.ablated_indices]
            abl_n = self._norm01(self.ablated.predict(X_abl))
            scores += weights[3] * abl_n

        # Renormalize
        w_total = sum(w for w in weights if w > 0)
        if w_total > 0:
            scores /= w_total

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
        if self.ablated is not None and self.ablated_indices:
            X_abl = X_s[:, self.ablated_indices]
            result['ablated_top_idx'] = int(np.argmax(self.ablated.predict(X_abl)))

        return result

    @staticmethod
    def _norm01(arr):
        """Normalize array to 0-1 range."""
        mn, mx = arr.min(), arr.max()
        if mx - mn < 1e-8:
            return np.full_like(arr, 0.5)
        return (arr - mn) / (mx - mn)
