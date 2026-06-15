"""V7 Live (Phase 5.8.28) — 225 feature inference.

V6 (210) + 15 race-relative (rr__) = V7 (225). v6_live.py kardeşi.
ENV TJK_V7_SHADOW=1 (default), TJK_V7_LIVE=0.

Bundle: model/trained_v7_225/. Mevcut v6_live'ın _build_matrix mantığı yeniden
kullanılır + rr__ feature'lar feature_compute_v7 ile üretilir.

Never-raises; hata → None → yerli_engine V3 fallback.
"""
from __future__ import annotations

import json
import logging
import os
from typing import Optional

import joblib
import numpy as np

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINED_V7_DIR = os.path.join(REPO, 'model', 'trained_v7_225')

_BUNDLE: Optional[dict] = None


def is_shadow_enabled() -> bool:
    return os.environ.get('TJK_V7_SHADOW', '1') == '1'


def is_live_enabled() -> bool:
    return os.environ.get('TJK_V7_LIVE', '0') == '1'


def _load_bundle() -> dict:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    bundle = {'feature_cols': [], 'breeds': {}}
    try:
        fc_path = os.path.join(TRAINED_V7_DIR, 'feature_columns.json')
        if not os.path.exists(fc_path):
            _BUNDLE = bundle
            return bundle
        with open(fc_path) as f:
            bundle['feature_cols'] = json.load(f)
        for breed in ('arab', 'english'):
            b = {}
            for key, pat in [
                ('xgb', 'xgb_ranker_{b}.pkl'),
                ('lgbm', 'lgbm_ranker_{b}.pkl'),
                ('cb', 'cb_ranker_{b}.pkl'),
                ('xgb_prob', 'xgb_prob_{b}.pkl'),
                ('lgbm_prob', 'lgbm_prob_{b}.pkl'),
                ('scaler', 'scaler_{b}.pkl'),
                ('scaler_prob', 'scaler_prob_{b}.pkl'),
            ]:
                p = os.path.join(TRAINED_V7_DIR, pat.format(b=breed))
                if os.path.exists(p):
                    try:
                        b[key] = joblib.load(p)
                    except Exception as e:
                        logger.warning(f'v7_live: {breed}/{key} load fail: {e!r}')
            if 'scaler' in b and 'xgb' in b and 'lgbm' in b:
                bundle['breeds'][breed] = b
        _BUNDLE = bundle
        if bundle['breeds']:
            logger.info(f"v7_live: bundle OK ({list(bundle['breeds'].keys())}, "
                        f"{len(bundle['feature_cols'])} feat)")
    except Exception as e:
        logger.warning(f'v7_live: bundle load fail: {e!r}')
        _BUNDLE = bundle
    return _BUNDLE


def is_ready() -> bool:
    return bool(_load_bundle()['breeds'])


def _normalize(p):
    p = np.asarray(p, dtype=float)
    mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def predict_v7(horse_meta_list, breed: str, hippo: str, race_no: Optional[int],
               target_date) -> Optional[dict]:
    """V7 prediction (225 feature). horse_meta_list aynı şema v6_live ile."""
    if not is_shadow_enabled() and not is_live_enabled():
        return None
    bundle = _load_bundle()
    if breed not in bundle['breeds']:
        return None
    if len(horse_meta_list) < 2:
        return None
    b = bundle['breeds'][breed]
    fc = bundle['feature_cols']
    n = len(horse_meta_list)

    try:
        # 180 base (V3 LIVE) + 30 V6 features (feature_compute_v6)
        # Bunlar zaten v6_live.predict_v6 ile hesaplandığı için
        # önce v6 feature dict'ini alırız, sonra rr__ ekleriz
        try:
            from dashboard.v3_live import _build_matrix as _v3_build
            from dashboard.feature_compute_v6 import compute_horse, compute_race_context
            from dashboard.jockey_lookup import cond_top4 as _jct4, cond_win as _jcw, overall as _jov
            from dashboard.feature_compute_v7 import compute_race_relative
        except ImportError:
            from v3_live import _build_matrix as _v3_build
            from feature_compute_v6 import compute_horse, compute_race_context
            from jockey_lookup import cond_top4 as _jct4, cond_win as _jcw, overall as _jov
            from feature_compute_v7 import compute_race_relative

        horse_numbers = [h.get('horse_number') for h in horse_meta_list]
        X_180 = _v3_build(n, horse_numbers, hippo, race_no or 0, target_date)
        try:
            from dashboard.v3_live import _load_bundle as _v3_bundle
        except ImportError:
            from v3_live import _load_bundle as _v3_bundle
        v3_bundle = _v3_bundle()
        fc_180 = v3_bundle.get('feature_cols') or []
        fc_180_set = set(fc_180)
        X = np.zeros((n, len(fc)), dtype=float)
        for i, col in enumerate(fc):
            if col in fc_180_set:
                v3_idx = fc_180.index(col)
                X[:, i] = X_180[:, v3_idx]

        # V6 30 yeni feature
        race_ctx = compute_race_context(horse_meta_list)
        idx_map = {col: i for i, col in enumerate(fc)}
        v6_feature_dicts = []
        for hi, h in enumerate(horse_meta_list):
            jck_name = h.get('jockey_name') or ''
            dist = h.get('distance') or 1400
            track = h.get('track_type') or ''
            jct4 = _jct4(jck_name, dist, track)
            jcw = _jcw(jck_name, dist, track)
            ov = _jov(jck_name)
            jcn = (ov or {}).get('n', 0) if jct4 is not None else (-1 if ov else 0)
            mf_overrides = {
                'mf__jockey_cond_top4': jct4 or 0,
                'mf__jockey_cond_win': jcw or 0,
                'mf__jockey_cond_n': float(jcn),
            }
            for col, val in mf_overrides.items():
                if col in idx_map:
                    X[hi, idx_map[col]] = float(val)

            feats = compute_horse(
                horse_name=h.get('horse_name', ''),
                agf_pct=h.get('agf_pct', 0),
                jockey_cond_top4=jct4 or 0,
                distance=dist,
                group_name=h.get('group_name', ''),
                race_ctx=race_ctx,
            )
            # source fields lazımız rr__ için
            feats['agf_pct'] = float(h.get('agf_pct') or 0)
            v6_feature_dicts.append(feats)
            for col, val in feats.items():
                if col in idx_map:
                    X[hi, idx_map[col]] = float(val)

        # rr__ race-relative compute
        v7_feature_dicts = compute_race_relative(v6_feature_dicts)
        for hi, feats in enumerate(v7_feature_dicts):
            for col, val in feats.items():
                if col.startswith('rr__') and col in idx_map:
                    X[hi, idx_map[col]] = float(val)

        X = np.nan_to_num(X, nan=0.0, posinf=1.0, neginf=0.0)

        # Inference
        X_s = b['scaler'].transform(X)
        p_xgb = b['xgb'].predict(X_s)
        p_lgbm = b['lgbm'].predict(X_s)
        if 'cb' in b:
            p_cb = b['cb'].predict(X_s)
            if p_cb.ndim > 1: p_cb = p_cb.flatten()
            scores = 0.40 * _normalize(p_xgb) + 0.35 * _normalize(p_lgbm) + 0.25 * _normalize(p_cb)
        else:
            scores = 0.53 * _normalize(p_xgb) + 0.47 * _normalize(p_lgbm)

        # Prob
        X_sp = b['scaler_prob'].transform(X)
        p1 = b['xgb_prob'].predict_proba(X_sp)[:, 1]
        p2 = b['lgbm_prob'].predict_proba(X_sp)[:, 1]
        probs = np.clip(0.5 * p1 + 0.5 * p2, 1e-6, 1 - 1e-6)
        ps = float(probs.sum())
        pn = probs / ps if ps > 1e-12 else probs

        return {
            'scores': [float(x) for x in scores],
            'probs': [float(x) for x in pn],
            'probs_raw': [float(x) for x in probs],
            'top1_idx': int(np.argmax(pn)),
            'top3_idx': [int(i) for i in np.argsort(-scores)[:3]],
            'top4_idx': [int(i) for i in np.argsort(-scores)[:4]],
            'n_horses': n,
            'mode': 'live' if is_live_enabled() else 'shadow',
        }
    except Exception as e:
        logger.debug(f'v7_live predict fail: {e!r}')
        return None


def stats():
    bundle = _load_bundle()
    return {
        'loaded': bool(bundle['breeds']),
        'breeds': list(bundle['breeds'].keys()),
        'n_features': len(bundle['feature_cols']),
        'shadow_enabled': is_shadow_enabled(),
        'live_enabled': is_live_enabled(),
    }
