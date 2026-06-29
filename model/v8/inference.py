"""V8 Inference pipeline — production-ready prediction.

Tek atın V8 tahminini üretir. NEVER raises. Eksik model graceful.

Workflow:
  1) Feature build (v7 + forecast)
  2) Model load (cached)
  3) Predict 4 heads
  4) Race-relative normalization (opsiyonel)

API
---
- `predict_race(horses, history_lookup, race_context=None,
                 model_path=None)` → list of {horse_no, p_top1..4}
- `V8Inferencer.predict(features)` → 4-head dict
"""
from __future__ import annotations

import logging
import os
import threading
from typing import Callable, Iterable, Mapping, Optional

from .feature_builder import build_race_matrix
from .model import V8Model

logger = logging.getLogger(__name__)

# Singleton cache
_MODEL_CACHE: Optional[V8Model] = None
_MODEL_LOCK = threading.Lock()

DEFAULT_MODEL_PATH = os.path.join(
    os.path.dirname(__file__), "trained", "v8_active.json"
)


def load_model(path: Optional[str] = None,
                force: bool = False) -> Optional[V8Model]:
    """Load V8 model from disk (cached). NEVER raises."""
    global _MODEL_CACHE
    if not force and _MODEL_CACHE is not None:
        return _MODEL_CACHE
    p = path or DEFAULT_MODEL_PATH
    if not os.path.exists(p):
        logger.warning(f"V8 model not found at {p}")
        return None
    with _MODEL_LOCK:
        try:
            _MODEL_CACHE = V8Model.load(p)
            if _MODEL_CACHE:
                logger.info(f"V8 model loaded from {p} "
                            f"(n_features={len(_MODEL_CACHE.feature_keys)}, "
                            f"fit_n={_MODEL_CACHE.fit_n})")
        except Exception as exc:
            logger.warning(f"V8 model load fail: {exc}")
            _MODEL_CACHE = None
    return _MODEL_CACHE


def predict_race(
    horses: Iterable[Mapping],
    history_lookup: Callable[[str], list],
    race_context: Optional[Mapping] = None,
    glicko_ledger=None,
    ref_date: Optional[str] = None,
    model_path: Optional[str] = None,
) -> list[dict]:
    """Bir yarışın tüm atları için V8 tahmin.

    Öncelik chain (Phase 2026-06-27):
      1. v8_real.json XGBoost (varsa) — GERÇEK backfill ile eğitilmiş
      2. v8_active.json bootstrap (fallback)
      3. Uniform graceful degrade

    Returns: list of {horse_no, horse_name, p_top1..4, model_loaded}.
    """
    horses = list(horses)
    # Öncelik chain: V9 ensemble → V8.6/8.5 XGB → V8 bootstrap
    # 1) V9 ENSEMBLE (XGB + LGBM + CatBoost)
    try:
        from model.v9.inference_v9 import predict_race_v9
        v9_out = predict_race_v9(
            horses=horses, history_lookup=history_lookup,
            ref_date=ref_date,
        )
        if v9_out is not None and len(v9_out) == len(horses):
            return v9_out
    except Exception as exc:
        logger.debug(f"V9 ensemble skip: {exc}")
    # 2) V8.6/8.5 XGBoost real
    try:
        from model.v8.inference_xgb import predict_race_xgb
        xgb_out = predict_race_xgb(
            horses=horses, history_lookup=history_lookup,
            ref_date=ref_date,
        )
        if xgb_out is not None and len(xgb_out) == len(horses):
            return xgb_out
    except Exception as exc:
        logger.debug(f"V8 XGBoost path skip: {exc}")

    # 2) Eski bootstrap fallback
    model = load_model(model_path)
    feature_matrix = build_race_matrix(
        horses,
        history_lookup=history_lookup,
        race_context=race_context,
        glicko_ledger=glicko_ledger,
        ref_date=ref_date,
    )
    if model is None:
        # Graceful degrade: return uniform probabilities
        n = len(feature_matrix)
        return [
            {
                "horse_no": h.get("horse_no"),
                "horse_name": h.get("horse_name"),
                "p_top1": 1.0 / max(n, 1),
                "p_top2": 2.0 / max(n, 1),
                "p_top3": 3.0 / max(n, 1),
                "p_top4": 4.0 / max(n, 1),
                "model_loaded": False,
            }
            for h in feature_matrix
        ]
    out = []
    for h in feature_matrix:
        try:
            preds = model.predict(h)
            out.append({
                "horse_no": h.get("horse_no"),
                "horse_name": h.get("horse_name"),
                **preds,
                "model_loaded": True,
            })
        except Exception as exc:
            logger.debug(f"predict fail for {h.get('horse_name')}: {exc}")
            out.append({
                "horse_no": h.get("horse_no"),
                "horse_name": h.get("horse_name"),
                "p_top1": None, "p_top2": None,
                "p_top3": None, "p_top4": None,
                "error": repr(exc)[:200],
            })
    return out


class V8Inferencer:
    """Stateful inferencer for hot-loop production."""

    def __init__(self, model_path: Optional[str] = None):
        self.model_path = model_path or DEFAULT_MODEL_PATH
        self.model = load_model(self.model_path)

    @property
    def loaded(self) -> bool:
        return self.model is not None

    def predict(self, features: Mapping) -> dict:
        if self.model is None:
            return {"p_top1": None, "p_top2": None,
                    "p_top3": None, "p_top4": None}
        return self.model.predict(features)

    def reload(self) -> bool:
        self.model = load_model(self.model_path, force=True)
        return self.loaded
