"""V8 XGBoost production inference adapter.

train_real.py'ın ürettiği v8_real.json'u yükler ve aynı predict_race
API'sını sağlar. Bootstrap V8Model'in (pure-Python) yerine geçer.

Öncelik chain'i:
  1. Eğer model/v8/trained/v8_real.json varsa → XGBoost
  2. Yoksa → V8Model bootstrap (eski yol)

Env override:
  TJK_V8_FORCE_BOOTSTRAP=1 → XGBoost yoksayılır, bootstrap kullanılır
"""
from __future__ import annotations

import json
import logging
import os
import threading
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

REAL_MODEL_PATH = Path(__file__).resolve().parent / "trained" / "v8_real.json"

# Singleton cache
_XGB_CACHE: Optional[dict] = None
_XGB_LOCK = threading.Lock()


def _force_bootstrap() -> bool:
    return os.environ.get("TJK_V8_FORCE_BOOTSTRAP", "0") == "1"


def load_xgb_model(force: bool = False) -> Optional[dict]:
    """v8_real.json → {feature_cols, heads (xgb.Booster), metrics}.

    NEVER raises. Bootstrap istenirse None döndürür.
    """
    global _XGB_CACHE
    if not force and _XGB_CACHE is not None:
        return _XGB_CACHE
    if _force_bootstrap():
        return None
    if not REAL_MODEL_PATH.exists():
        return None
    with _XGB_LOCK:
        try:
            import xgboost as xgb
            with open(REAL_MODEL_PATH) as f:
                d = json.load(f)
            heads = {}
            for head, hex_str in (d.get("heads") or {}).items():
                booster = xgb.Booster()
                booster.load_model(bytearray.fromhex(hex_str))
                heads[head] = booster
            _XGB_CACHE = {
                "feature_cols": d.get("feature_cols") or [],
                "heads": heads,
                "metrics": d.get("metrics") or {},
                "feature_importance_pct": d.get("feature_importance_pct") or {},
                "version": d.get("version"),
            }
            logger.info(f"V8 XGBoost loaded: n_features="
                        f"{len(_XGB_CACHE['feature_cols'])}, "
                        f"heads={list(heads.keys())}")
            return _XGB_CACHE
        except Exception as exc:
            logger.warning(f"V8 XGBoost load fail: {exc}")
            return None


def _build_xgb_features(horse: Mapping, history: list, ref_date: str,
                        n_horses_in_race: int) -> Optional[dict]:
    """train_real._build_features_for_horse'un canlı versiyonu."""
    try:
        from model.v8.train_real import _build_features_for_horse
        # train_real history_map yapısını bekliyor: {name: [hist...]}
        nm = horse.get("horse_name") or horse.get("name") or ""
        history_map = {nm: history or []}
        return _build_features_for_horse(
            name=nm, ref_date=ref_date or "9999-12-31",
            history_map=history_map,
            n_horses_in_race=n_horses_in_race,
        )
    except Exception as exc:
        logger.debug(f"xgb feat build fail: {exc}")
        return None


def predict_race_xgb(
    horses: Iterable[Mapping],
    history_lookup: Optional[Callable[[str], list]] = None,
    ref_date: Optional[str] = None,
) -> Optional[list[dict]]:
    """XGBoost ile bir yarışın tahminleri. None döner → bootstrap fallback.

    Returns: list of {horse_no, horse_name, p_top1..4, model_loaded=True}
    """
    bundle = load_xgb_model()
    if bundle is None:
        return None
    import numpy as np
    import xgboost as xgb

    horses = list(horses)
    if not horses:
        return []

    feature_cols = bundle["feature_cols"]
    heads = bundle["heads"]

    # her at için feature vector
    rows = []
    for h in horses:
        nm = h.get("horse_name") or h.get("name") or ""
        hist = []
        if history_lookup is not None and nm:
            try:
                hist = history_lookup(nm) or []
            except Exception:
                hist = []
        feat = _build_xgb_features(h, hist, ref_date, len(horses))
        rows.append((h, feat))

    # Yetersiz feature olanlara default 0
    X = np.array([
        [float(r[1].get(c, 0) or 0) if r[1] else 0.0 for c in feature_cols]
        for r in rows
    ])
    dtest = xgb.DMatrix(X)

    out = []
    for i, (h, _feat) in enumerate(rows):
        preds_raw = {}
        for head_name in ("top1", "top2", "top3", "top4"):
            if head_name in heads:
                try:
                    p = float(heads[head_name].predict(dtest)[i])
                    preds_raw[f"p_{head_name}"] = max(0.0, min(1.0, p))
                except Exception:
                    preds_raw[f"p_{head_name}"] = None
            else:
                preds_raw[f"p_{head_name}"] = None
        # Monotonicity: p_topN >= p_top(N-1)
        if all(preds_raw.get(f"p_top{k}") is not None for k in (1, 2, 3, 4)):
            preds_raw["p_top2"] = max(preds_raw["p_top1"],
                                       preds_raw["p_top2"])
            preds_raw["p_top3"] = max(preds_raw["p_top2"],
                                       preds_raw["p_top3"])
            preds_raw["p_top4"] = max(preds_raw["p_top3"],
                                       preds_raw["p_top4"])
        out.append({
            "horse_no": h.get("horse_no") or h.get("horse_number"),
            "horse_name": h.get("horse_name") or h.get("name"),
            **preds_raw,
            "model_loaded": True,
            "model_kind": "xgboost_real",
        })
    return out
