"""
Ensemble Model V5 — Breed-Split + Calibrated Probability
==========================================================
Arab ve Ingiliz icin ayri model.
Ranking model (siralama) + Probability model (ganyan value).
"""
import os
import json
import logging
import numpy as np

logger = logging.getLogger(__name__)
MODEL_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'trained')


class EnsembleRanker:
    """Breed-split ensemble ranker + probability model."""

    def __init__(self, model_dir=None):
        self.model_dir = model_dir or MODEL_DIR
        self.models = {}  # {'arab': {...}, 'english': {...}}
        self.prob_models = {}  # calibrated probability models
        self.feature_cols = None
        self.loaded = False

    def load(self):
        import joblib
        try:
            # Feature columns
            fc_path = os.path.join(self.model_dir, 'feature_columns.json')
            with open(fc_path) as f:
                self.feature_cols = json.load(f)

            # Breed bazli modeller
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

                if os.path.exists(xgb_prob_path):
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
            logger.info(f"Model loaded: {len(self.feature_cols)} features, "
                       f"breeds: {list(self.models.keys())}, "
                       f"prob: {list(self.prob_models.keys())}")
            return self.loaded

        except Exception as e:
            logger.error(f"Model load failed: {e}")
            import traceback; traceback.print_exc()
            return False

    def detect_breed(self, group_name):
        """group_name'den breed tespit et."""
        g = str(group_name).lower() if group_name else ''
        if 'arap' in g:
            return 'arab'
        elif 'ngiliz' in g:
            return 'english'
        return 'default'

    def _get_model(self, breed):
        """Breed'e gore model sec, yoksa fallback."""
        if breed in self.models:
            return self.models[breed]
        if 'english' in self.models:
            return self.models['english']  # default fallback
        if 'default' in self.models:
            return self.models['default']
        return None

    def predict(self, feature_matrix, breed='english'):
        """Ensemble ranking predict — normalized 0-1 scores."""
        if not self.loaded:
            raise RuntimeError("Model not loaded!")

        m = self._get_model(breed)
        if m is None:
            raise RuntimeError(f"No model for breed: {breed}")

        X_s = m['scaler'].transform(feature_matrix)
        xgb_pred = self._norm01(m['xgb'].predict(X_s))
        lgbm_pred = self._norm01(m['lgbm'].predict(X_s))
        scores = 0.50 * xgb_pred + 0.50 * lgbm_pred
        return scores

    def predict_proba(self, feature_matrix, breed='english'):
        """Calibrated probability predict — gercek olasilik (ganyan value icin)."""
        if breed not in self.prob_models:
            # Fallback: ranking skorunu normalize et
            scores = self.predict(feature_matrix, breed)
            return scores / scores.sum() if scores.sum() > 0 else scores

        m = self.prob_models[breed]
        X_s = m['scaler'].transform(feature_matrix)
        xgb_prob = m['xgb'].predict_proba(X_s)[:, 1]
        lgbm_prob = m['lgbm'].predict_proba(X_s)[:, 1]
        return 0.50 * xgb_prob + 0.50 * lgbm_prob

    def predict_individual(self, feature_matrix, breed='english'):
        """Her modelin ayri top-1 secimi (agreement icin)."""
        if not self.loaded:
            return {}
        m = self._get_model(breed)
        if m is None:
            return {}
        X_s = m['scaler'].transform(feature_matrix)
        return {
            'xgb_top_idx': int(np.argmax(m['xgb'].predict(X_s))),
            'lgbm_top_idx': int(np.argmax(m['lgbm'].predict(X_s))),
        }

    @staticmethod
    def _norm01(arr):
        mn, mx = arr.min(), arr.max()
        if mx - mn < 1e-8:
            return np.full_like(arr, 0.5)
        return (arr - mn) / (mx - mn)
