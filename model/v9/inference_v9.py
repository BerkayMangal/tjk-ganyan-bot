"""V9 Ensemble production inference adapter.

Bundle: model/v9/trained/v9_ensemble.json (XGB + LGBM + CatBoost + meta).
Predict: mean(XGB_p, LGBM_p, CAT_p) — equal weight ensemble.

Aynı API: predict_race(horses, history_lookup, ref_date) → list[dict].
"""
from __future__ import annotations

import base64
import json
import logging
import os
import tempfile
import threading
from pathlib import Path
from typing import Callable, Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

V9_PATH = (Path(__file__).resolve().parent
           / "trained" / "v9_ensemble.json")
_V9_CACHE: Optional[dict] = None
_V9_LOCK = threading.Lock()


def _force_v9_skip():
    return os.environ.get("TJK_V9_FORCE_SKIP", "0") == "1"


def load_v9_ensemble(force: bool = False) -> Optional[dict]:
    """V9 ensemble bundle yükle."""
    global _V9_CACHE
    if not force and _V9_CACHE is not None:
        return _V9_CACHE
    if _force_v9_skip() or not V9_PATH.exists():
        return None
    with _V9_LOCK:
        try:
            import xgboost as xgb
            import lightgbm as lgb
            import catboost as cb
            with open(V9_PATH) as f:
                d = json.load(f)
            heads = {}
            for head, hd in (d.get("heads") or {}).items():
                # XGB
                xgb_b = xgb.Booster()
                xgb_b.load_model(bytearray.fromhex(hd["xgb_hex"]))
                # LGBM (text)
                lgb_b = lgb.Booster(model_str=hd["lgbm_txt"])
                # CatBoost (base64 binary)
                cat_b = cb.CatBoostClassifier()
                with tempfile.NamedTemporaryFile(
                        delete=False, suffix=".cbm") as tf:
                    tf.write(base64.b64decode(hd["cat_b64"]))
                    tf_name = tf.name
                cat_b.load_model(tf_name)
                os.unlink(tf_name)
                heads[head] = {
                    "xgb": xgb_b, "lgbm": lgb_b, "cat": cat_b,
                    "metrics": {
                        "xgb": hd.get("xgb_metrics", {}),
                        "lgbm": hd.get("lgbm_metrics", {}),
                        "cat": hd.get("cat_metrics", {}),
                        "ensemble": hd.get("ensemble_metrics", {}),
                    },
                }
            _V9_CACHE = {
                "version": d.get("version"),
                "feature_cols": d.get("feature_cols") or [],
                "horse_embedding": d.get("horse_embedding") or {},
                "jockey_embedding": d.get("jockey_embedding") or {},
                "sire_embedding": d.get("sire_embedding") or {},
                "agf_history_compact": d.get("agf_history_compact") or {},
                "heads": heads,
            }
            logger.info(f"V9 ensemble loaded ({d.get('version')}): "
                        f"n_features={len(_V9_CACHE['feature_cols'])}, "
                        f"heads={list(heads.keys())}")
            return _V9_CACHE
        except Exception as exc:
            logger.warning(f"V9 ensemble load fail: {exc}")
            return None


def _build_features(horse, history, ref_date, n_horses_in_race, bundle):
    """V8.6 ile aynı feature pipeline — V8.5 enrich kullan."""
    try:
        from model.v8.inference_xgb import _build_xgb_features, _enrich_v8_5
        from forecast.feature_meta import (
            compute_field_meta, mark_top_k_glicko,
        )
        feat = _build_xgb_features(horse, history, ref_date,
                                    n_horses_in_race)
        return feat
    except Exception as exc:
        logger.debug(f"v9 feat fail: {exc}")
        return None


def predict_race_v9(
    horses: Iterable[Mapping],
    history_lookup: Optional[Callable[[str], list]] = None,
    ref_date: Optional[str] = None,
) -> Optional[list[dict]]:
    """V9 ensemble predictions. None → fallback chain.

    XGB + LGBM + CatBoost ortalama (equal weight) — mean of probabilities.
    """
    bundle = load_v9_ensemble()
    if bundle is None:
        return None
    import numpy as np
    import xgboost as xgb

    horses = list(horses)
    if not horses:
        return []

    feature_cols = bundle["feature_cols"]
    heads = bundle["heads"]

    # Per-horse base features
    rows = []
    for h in horses:
        nm = h.get("horse_name") or h.get("name") or ""
        hist = []
        if history_lookup and nm:
            try:
                hist = history_lookup(nm) or []
            except Exception:
                hist = []
        feat = _build_features(h, hist, ref_date, len(horses), bundle)
        rows.append((h, feat, hist))

    # V9 = V8.6 features → field meta + enrich gerek
    valid_feats = [f for _, f, _ in rows if f]
    if valid_feats:
        from forecast.feature_meta import (
            compute_field_meta, mark_top_k_glicko,
        )
        from model.v8.inference_xgb import _enrich_v8_5
        field_meta = compute_field_meta(valid_feats)
        mark_top_k_glicko(valid_feats, k=3)
        for h, feat, hist in rows:
            if feat is None:
                continue
            _enrich_v8_5(feat, h, hist, field_meta, bundle, ref_date)

    X = np.array([
        [float(r[1].get(c, 0) or 0) if r[1] else 0.0
         for c in feature_cols]
        for r in rows
    ])
    dtest = xgb.DMatrix(X)

    out = []
    for i, (h, _f, _hist) in enumerate(rows):
        preds_raw = {}
        for head_name in ("top1", "top2", "top3", "top4"):
            if head_name not in heads:
                preds_raw[f"p_{head_name}"] = None
                continue
            triple = heads[head_name]
            try:
                p_xgb = float(triple["xgb"].predict(dtest)[i])
                p_lgb = float(triple["lgbm"].predict(X)[i])
                p_cat = float(triple["cat"].predict_proba(X)[i, 1])
                p_ens = (p_xgb + p_lgb + p_cat) / 3.0
                preds_raw[f"p_{head_name}"] = max(0.0, min(1.0, p_ens))
            except Exception as exc:
                logger.debug(f"v9 {head_name} fail: {exc}")
                preds_raw[f"p_{head_name}"] = None
        # Monotonicity
        if all(preds_raw.get(f"p_top{k}") is not None
               for k in (1, 2, 3, 4)):
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
            "model_kind": "v9_ensemble",
        })
    return out
