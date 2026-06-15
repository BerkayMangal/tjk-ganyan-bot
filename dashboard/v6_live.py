"""V6 Live (Phase 5.8.22) — prod-time 210 feature inference.

V3 LIVE (180 feature) ile paralel çalışır. v3_live._build_matrix 180 feature
üretir; bu modül +30 yeni feature (cf__/rc__/ix__/pf__) ekleyip V6 modeline
inference yapar.

Mode:
  TJK_V6_SHADOW=1 (default): her tahminde V6 SHADOW hesabı, log + audit
  TJK_V6_LIVE=1: V6 prediction'ı V3 yerine kullan (gelecek aşama)

Bundle yolu: model/trained_v6_210/

V6'nın 30 yeni feature'ı:
  cf__career_* (14) — JSON snapshot lookup (data/horse_career_stats.json)
  rc__race_* (7)    — yarış-bazlı aggregate
  ix__* (6)         — interaction terms
  pf__* (3)         — polynomial squared

Never-raises; hata → None (yerli_engine V3 fallback).
"""
from __future__ import annotations

import json
import logging
import os
from datetime import date
from typing import Optional

import joblib
import numpy as np

logger = logging.getLogger(__name__)

REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TRAINED_V6_DIR = os.path.join(REPO, 'model', 'trained_v6_210')

_BUNDLE: Optional[dict] = None


def is_shadow_enabled() -> bool:
    return os.environ.get('TJK_V6_SHADOW', '1') == '1'


def is_live_enabled() -> bool:
    return os.environ.get('TJK_V6_LIVE', '0') == '1'


def _load_bundle() -> dict:
    global _BUNDLE
    if _BUNDLE is not None:
        return _BUNDLE
    bundle = {'feature_cols': [], 'breeds': {}}
    try:
        fc_path = os.path.join(TRAINED_V6_DIR, 'feature_columns.json')
        if not os.path.exists(fc_path):
            logger.warning('v6_live: trained_v6_210/ yok')
            _BUNDLE = bundle
            return bundle
        with open(fc_path) as f:
            bundle['feature_cols'] = json.load(f)
        artifacts = [
            ('xgb', 'xgb_ranker_{b}.pkl'),
            ('lgbm', 'lgbm_ranker_{b}.pkl'),
            ('cb', 'cb_ranker_{b}.pkl'),
            ('xgb_prob', 'xgb_prob_{b}.pkl'),
            ('lgbm_prob', 'lgbm_prob_{b}.pkl'),
            ('scaler', 'scaler_{b}.pkl'),
            ('scaler_prob', 'scaler_prob_{b}.pkl'),
            ('isotonic', 'isotonic_prob_{b}.pkl'),
            ('beta', 'beta_prob_{b}.pkl'),
        ]
        for breed in ('arab', 'english'):
            b = {}
            for key, pat in artifacts:
                p = os.path.join(TRAINED_V6_DIR, pat.format(b=breed))
                if os.path.exists(p):
                    try:
                        b[key] = joblib.load(p)
                    except Exception as e:
                        logger.warning(f'v6_live: {breed}/{key} load fail: {e!r}')
            # calib_best
            cb_path = os.path.join(TRAINED_V6_DIR, f'calib_best_{breed}.txt')
            calib_best = 'raw'   # V6 default
            if os.path.exists(cb_path):
                try:
                    with open(cb_path) as f: calib_best = f.read().strip()
                except Exception:
                    pass
            b['calib_best'] = calib_best
            if 'scaler' in b and 'xgb' in b and 'lgbm' in b:
                bundle['breeds'][breed] = b
        _BUNDLE = bundle
        if bundle['breeds']:
            logger.info(f"v6_live: bundle OK ({list(bundle['breeds'].keys())}, "
                        f"{len(bundle['feature_cols'])} feat)")
    except Exception as e:
        logger.warning(f'v6_live: bundle load fail: {e!r}')
        _BUNDLE = bundle
    return _BUNDLE


def is_ready() -> bool:
    return bool(_load_bundle()['breeds'])


def _normalize(p):
    p = np.asarray(p, dtype=float)
    mn, mx = p.min(), p.max()
    return np.full_like(p, 0.5) if (mx - mn) <= 1e-12 else (p - mn) / (mx - mn)


def predict_v6(horse_meta_list, breed: str, hippo: str, race_no: Optional[int],
               target_date) -> Optional[dict]:
    """V6 prediction (210 feature).

    horse_meta_list: list of dict per horse, fields:
      horse_name, horse_number, agf_pct, jockey_cond_top4 (optional),
      age (optional), weight (optional), distance, group_name

    Returns: {scores, probs, top1_idx, n_horses, calib_used}
    """
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
        # V3 LIVE 180 base matrix (mf__ + f_/f_X_ → DB lookup)
        try:
            from dashboard.v3_live import _build_matrix as _v3_build
        except ImportError:
            from v3_live import _build_matrix as _v3_build
        horse_numbers = [h.get('horse_number') for h in horse_meta_list]
        X_180 = _v3_build(n, horse_numbers, hippo, race_no or 0, target_date)
        # X_180 dim = 177 (V3 LIVE fc) → V6 ilk 180'i farklı sırada. Sıraya göre eşleştir.
        # Asıl çözüm: V6 fc'sinin sırasını V3 fc'siyle eşleştir.
        try:
            from dashboard.v3_live import _load_bundle as _v3_bundle
        except ImportError:
            from v3_live import _load_bundle as _v3_bundle
        v3_bundle = _v3_bundle()
        fc_180 = v3_bundle.get('feature_cols') or []
        # V6 fc içinde V3 fc'sinde olan kolonların indeks haritası
        fc_180_set = set(fc_180)
        # V6 fc = V3 fc (177) + ek mf__jockey_cond_* (3) + ek 30 yeni → ama
        # build_X eğitimde df.columns'a göre alıyor. Burada V3 _build_matrix sadece
        # 177 V3 LIVE feature üretir → V6 fc'sinde 177'sini aynı pozisyonda doldur,
        # geri kalanı (mf__jockey_cond_* + cf__/rc__/ix__/pf__) compute_v6 ile.
        X = np.zeros((n, len(fc)), dtype=float)
        for i, col in enumerate(fc):
            if col in fc_180_set:
                v3_idx = fc_180.index(col)
                X[:, i] = X_180[:, v3_idx]

        # V6 ek feature'lar (30 + 3 mf__jockey_cond_*)
        try:
            from dashboard.feature_compute_v6 import compute_horse, compute_race_context
            from dashboard.jockey_lookup import cond_top4 as _jck_t4, cond_win as _jck_w, overall as _jck_ov
        except ImportError:
            from feature_compute_v6 import compute_horse, compute_race_context
            from jockey_lookup import cond_top4 as _jck_t4, cond_win as _jck_w, overall as _jck_ov

        # Race context (yarış-bazlı aggregate)
        race_ctx = compute_race_context(horse_meta_list)

        # mf__jockey_cond_* indeks
        idx_map = {col: i for i, col in enumerate(fc)}
        for hi, h in enumerate(horse_meta_list):
            # Jokey conditional (mf__ ama compute_v6 değil — direkt jokey_lookup)
            jck_name = h.get('jockey_name') or ''
            dist = h.get('distance') or 1400
            track = h.get('track_type') or ''
            jct4 = _jck_t4(jck_name, dist, track)
            jcw = _jck_w(jck_name, dist, track)
            ov = _jck_ov(jck_name)
            jcn = (ov or {}).get('n', 0) if jct4 is not None else (-1 if ov else 0)
            for col, val in [
                ('mf__jockey_cond_top4', jct4 or 0),
                ('mf__jockey_cond_win', jcw or 0),
                ('mf__jockey_cond_n', float(jcn)),
            ]:
                if col in idx_map:
                    X[hi, idx_map[col]] = float(val)

            # 30 yeni feature
            feats = compute_horse(
                horse_name=h.get('horse_name', ''),
                agf_pct=h.get('agf_pct', 0),
                jockey_cond_top4=jct4 or 0,
                distance=dist,
                group_name=h.get('group_name', ''),
                race_ctx=race_ctx,
            )
            for col, val in feats.items():
                if col in idx_map:
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
        probs = 0.5 * p1 + 0.5 * p2
        calib_used = b.get('calib_best', 'raw')
        if calib_used == 'beta' and 'beta' in b:
            try: probs = b['beta'].predict(probs)
            except Exception: pass
        elif calib_used == 'isotonic' and 'isotonic' in b:
            try: probs = b['isotonic'].transform(probs)
            except Exception: pass
        probs = np.clip(probs, 1e-6, 1 - 1e-6)
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
            'calib_used': calib_used,
            'mode': 'live' if is_live_enabled() else 'shadow',
        }
    except Exception as e:
        logger.debug(f'v6_live predict fail: {e!r}')
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
