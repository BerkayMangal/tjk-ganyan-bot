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
V9_5_PATH = (Path(__file__).resolve().parent
             / "trained" / "v9_5_ensemble.json")
V10_PATH = (Path(__file__).resolve().parent.parent
            / "v10" / "trained" / "v10_ensemble.json")
V11_PATH = (Path(__file__).resolve().parent.parent
            / "v11" / "trained" / "v11_ensemble.json")
_V9_CACHE: Optional[dict] = None
_V9_LOCK = threading.Lock()


def _force_v9_skip():
    return os.environ.get("TJK_V9_FORCE_SKIP", "0") == "1"


def _force_v95_skip():
    return os.environ.get("TJK_V95_SKIP", "0") == "1"


def load_v9_ensemble(force: bool = False) -> Optional[dict]:
    """V9 ensemble bundle yükle."""
    global _V9_CACHE
    if not force and _V9_CACHE is not None:
        return _V9_CACHE
    if _force_v9_skip():
        return None
    # Öncelik chain: V11 → V10 → V9.5 → V9
    force_v11_skip = os.environ.get("TJK_V11_SKIP", "0") == "1"
    force_v10_skip = os.environ.get("TJK_V10_SKIP", "0") == "1"
    if not force_v11_skip and V11_PATH.exists():
        path = V11_PATH
    elif not force_v10_skip and V10_PATH.exists():
        path = V10_PATH
    elif not _force_v95_skip() and V9_5_PATH.exists():
        path = V9_5_PATH
    elif V9_PATH.exists():
        path = V9_PATH
    else:
        return None
    with _V9_LOCK:
        try:
            import xgboost as xgb
            import lightgbm as lgb
            import catboost as cb
            with open(path) as f:
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
                # V10 stats (inference için)
                "v10_jockey_stats": d.get("v10_jockey_stats") or {},
                "v10_sire_stats": d.get("v10_sire_stats") or {},
                "v10_sire_lookup": d.get("v10_sire_lookup") or {},
                "v10_horse_weight_avg": d.get("v10_horse_weight_avg") or {},
                # V11 stats (point-in-time timelines)
                "v11_elo_final": d.get("v11_elo_final") or {},
                "v11_elo_timeline": d.get("v11_elo_timeline") or {},
                "v11_h2h_dates": d.get("v11_h2h_dates") or {},
                "v11_pace_timeline": d.get("v11_pace_timeline") or {},
                "v11_track_timeline": d.get("v11_track_timeline") or {},
                # V11 history compact (prod'da data volume yerine bundle-gömü)
                "v11_history_compact": d.get("v11_history_compact") or {},
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

    # V11: history_lookup verilmemişse bundle'daki compact'ı kullan
    _bundle_hist = bundle.get("v11_history_compact") or {}
    if history_lookup is None and _bundle_hist:
        history_lookup = lambda nm: _bundle_hist.get(nm) or []

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

        # V10 için 13 ek feature (jockey_dist, sire_dist, at_no, age...)
        is_v10 = ("v10" in (bundle.get("version") or "")
                  or "v11" in (bundle.get("version") or ""))
        is_v11 = "v11" in (bundle.get("version") or "")
        if is_v10:
            try:
                from forecast.features_v10 import build_v10_features
                for h, feat, hist in rows:
                    if feat is None:
                        continue
                    nm = h.get("horse_name") or h.get("name") or ""
                    horse_meta = {
                        "age": h.get("age"), "weight": h.get("weight"),
                        "at_no": h.get("horse_no") or h.get("horse_number"),
                        "jockey": h.get("jockey_name") or h.get("jockey"),
                        "sire": h.get("sire"),
                        "n_horses": len(rows),
                    }
                    race_context = {
                        "distance": h.get("distance") or 1600,
                        "track_type": h.get("track_type") or "Çim",
                    }
                    v10_extra = build_v10_features(
                        nm, ref_date, horse_meta, race_context,
                        hist or [],
                        bundle.get("v10_jockey_stats") or {},
                        bundle.get("v10_sire_stats") or {},
                        bundle.get("v10_horse_weight_avg") or {},
                        bundle.get("v10_sire_lookup") or {},
                    )
                    feat.update(v10_extra)
            except Exception as exc:
                logger.debug(f"V10 enrichment fail: {exc}")

        # V11 için 19 ek feature (H2H Elo + Pace + Track)
        if is_v11:
            try:
                from forecast.features_v11_h2h import build_h2h_features
                from forecast.features_v11_pace import build_pace_features
                from forecast.features_v11_track import build_track_features
                # Restore h2h_dates from string keys
                v11_h2h_str = bundle.get("v11_h2h_dates") or {}
                v11_h2h_dates = {}
                for k, v in v11_h2h_str.items():
                    if "||" in k:
                        a, b = k.split("||", 1)
                        v11_h2h_dates[(a, b)] = v
                elo_data = {
                    "final_elo": bundle.get("v11_elo_final") or {},
                    "timeline": bundle.get("v11_elo_timeline") or {},
                    "h2h_dates": v11_h2h_dates,
                }
                pace_timeline = bundle.get("v11_pace_timeline") or {}
                track_timeline = bundle.get("v11_track_timeline") or {}
                field_names = [(h.get("horse_name") or h.get("name") or "")
                                for h, _, _ in rows]
                hippo = (horses[0].get("hippodrome") or
                          horses[0].get("hippo") or "")
                distance = horses[0].get("distance") or 1600
                race_ctx = {"hippo": hippo, "distance": distance}
                rd = ref_date or "9999-12-31"
                for h, feat, hist in rows:
                    if feat is None:
                        continue
                    nm = h.get("horse_name") or h.get("name") or ""
                    field = [n for n in field_names if n and n != nm]
                    h2h = build_h2h_features(nm, rd, field, elo_data)
                    pace = build_pace_features(nm, rd, field, pace_timeline)
                    track = build_track_features(nm, rd, race_ctx,
                                                   track_timeline)
                    feat.update(h2h)
                    feat.update(pace)
                    feat.update(track)
            except Exception as exc:
                logger.debug(f"V11 enrichment fail: {exc}")

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
