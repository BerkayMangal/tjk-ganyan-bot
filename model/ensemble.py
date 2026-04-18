"""
Ensemble Model V5 — Breed-Split + Calibrated Probability
==========================================================
2-ensemble (XGB + LGBM) — Arab ve Ingiliz icin ayri model.
Ranking model (siralama) + Probability model (ganyan value).

NOT: cb_ranker.pkl mevcut ama generic (breed-split degil, 82 feature).
Breed-split 96-feature modelleriyle dimension uyumsuzlugu var.
TODO: CB breed-split modelleri train edilince ensemble'a ekle
"""
import os
import json
import logging
import warnings
import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

# Suppress any remaining sklearn feature-name warnings
warnings.filterwarnings('ignore', message='X does not have valid feature names')
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trained')


class EnsembleRanker:
    """Breed-split 2-ensemble ranker (XGB + LGBM) + probability model.
    
    CatBoost henüz breed-split olarak train edilmediği için ensemble'da yok.
    TODO: CB breed-split modelleri train edilince ensemble'a ekle
    """

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or MODEL_DIR
        self.models = {}
        self.prob_models = {}
        self.feature_cols = None
        self.loaded = False

    def load(self):
        import joblib
        try:
            fc_path = os.path.join(self.model_dir, 'feature_columns.json')
            with open(fc_path) as f:
                self.feature_cols = json.load(f)

            for breed in ['arab', 'english']:
                xgb_path = os.path.join(self.model_dir, f'xgb_ranker_{breed}.pkl')
                lgbm_path = os.path.join(self.model_dir, f'lgbm_ranker_{breed}.pkl')
                scaler_path = os.path.join(self.model_dir, f'scaler_{breed}.pkl')

                if os.path.exists(xgb_path):
                    self.models[breed] = {
                        'xgb': joblib.load(xgb_path),
                        'lgbm': joblib.load(lgbm_path),
                        'scaler': joblib.load(scaler_path),
                    }
                    logger.info(f"  {breed} ranking model OK")

                # Probability model (ganyan value icin)
                xgb_prob_path = os.path.join(self.model_dir, f'xgb_prob_{breed}.pkl')
                lgbm_prob_path = os.path.join(self.model_dir, f'lgbm_prob_{breed}.pkl')
                scaler_prob_path = os.path.join(self.model_dir, f'scaler_prob_{breed}.pkl')

                # Fallback: breed bazli yoksa generic scaler_prob.pkl kullan
                if not os.path.exists(scaler_prob_path):
                    generic_sp = os.path.join(self.model_dir, 'scaler_prob.pkl')
                    if os.path.exists(generic_sp):
                        scaler_prob_path = generic_sp
                        logger.info(f"  {breed} scaler_prob fallback -> generic scaler_prob.pkl")

                if os.path.exists(xgb_prob_path) and os.path.exists(scaler_prob_path):
                    self.prob_models[breed] = {
                        'xgb': joblib.load(xgb_prob_path),
                        'lgbm': joblib.load(lgbm_prob_path),
                        'scaler': joblib.load(scaler_prob_path),
                    }
                    logger.info(f"  {breed} probability model OK")

            # Fallback: eski V2 model (breed-split yoksa)
            if not self.models:
                logger.info("Breed modeller yok, V2 fallback deneniyor...")
                xgb_path = os.path.join(self.model_dir, 'xgb_ranker.pkl')
                if os.path.exists(xgb_path):
                    self.models['default'] = {
                        'xgb': joblib.load(xgb_path),
                        'lgbm': joblib.load(os.path.join(self.model_dir, 'lgbm_ranker.pkl')),
                        'scaler': joblib.load(os.path.join(self.model_dir, 'scaler.pkl')),
                    }
                    logger.info("  V2 fallback model OK")

            self.loaded = bool(self.models)

            # Dimension validation
            n_fc = len(self.feature_cols)
            for breed, m in self.models.items():
                n_sc = m['scaler'].n_features_in_
                if n_sc != n_fc:
                    logger.warning(f"  {breed} scaler expects {n_sc} features, "
                                   f"feature_columns.json has {n_fc}!")

            logger.info(f"Model loaded: {len(self.feature_cols)} features, "
                       f"breeds: {list(self.models.keys())}, "
                       f"prob: {list(self.prob_models.keys())}")
            return self.loaded

        except Exception as e:
            logger.error(f"Model load failed: {e}")
            logger.exception("Model load failed — full traceback:")
            return False

    def detect_breed(self, group_name):
        g = str(group_name).lower() if group_name else ''
        if 'arap' in g:
            return 'arab'
        elif 'ngiliz' in g:
            return 'english'
        return 'default'

    def _get_model(self, breed):
        if breed in self.models:
            return self.models[breed]
        if 'english' in self.models:
            return self.models['english']
        if 'default' in self.models:
            return self.models['default']
        return None

    def _to_df(self, X_scaled):
        """Wrap scaled numpy array in DataFrame with feature names.
        Eliminates LGBM 'X does not have valid feature names' warnings."""
        if self.feature_cols and X_scaled.shape[1] == len(self.feature_cols):
            return pd.DataFrame(X_scaled, columns=self.feature_cols)
        return X_scaled

    def predict(self, feature_matrix, breed='english'):
        if not self.loaded:
            raise RuntimeError("Model not loaded!")
        m = self._get_model(breed)
        if m is None:
            raise RuntimeError(f"No model for breed: {breed}")
        X_s = m['scaler'].transform(feature_matrix)
        X_df = self._to_df(X_s)
        xgb_pred = self._norm01(m['xgb'].predict(X_df))
        lgbm_pred = self._norm01(m['lgbm'].predict(X_df))
        return 0.50 * xgb_pred + 0.50 * lgbm_pred

    def predict_proba(self, feature_matrix, breed='english'):
        if breed not in self.prob_models:
            scores = self.predict(feature_matrix, breed)
            return scores / scores.sum() if scores.sum() > 0 else scores

        m = self.prob_models[breed]
        # Dimension check — prob model eski 48-feature olabilir
        n_expected = m['scaler'].n_features_in_
        n_actual = feature_matrix.shape[1]
        if n_expected != n_actual:
            logger.warning(f"  prob scaler expects {n_expected}, got {n_actual} — ranking fallback")
            scores = self.predict(feature_matrix, breed)
            return scores / scores.sum() if scores.sum() > 0 else scores

        X_s = m['scaler'].transform(feature_matrix)
        X_df = self._to_df(X_s)
        xgb_prob = m['xgb'].predict_proba(X_df)[:, 1]
        lgbm_prob = m['lgbm'].predict_proba(X_df)[:, 1]
        return 0.50 * xgb_prob + 0.50 * lgbm_prob

    def predict_individual(self, feature_matrix, breed='english'):
        if not self.loaded:
            return {}
        m = self._get_model(breed)
        if m is None:
            return {}
        X_s = m['scaler'].transform(feature_matrix)
        X_df = self._to_df(X_s)
        return {
            'xgb_top_idx': int(np.argmax(m['xgb'].predict(X_df))),
            'lgbm_top_idx': int(np.argmax(m['lgbm'].predict(X_df))),
        }

    @staticmethod
    def _norm01(arr):
        mn, mx = arr.min(), arr.max()
        if mx - mn < 1e-8:
            return np.full_like(arr, 0.5)
        return (arr - mn) / (mx - mn)
