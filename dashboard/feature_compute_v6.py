"""V6 prod-time feature compute (Phase 5.8.22).

V6 model (210 feature, audit/104) 30 yeni feature kullanır:
  cf__career_*   — at history (JSON lookup'tan)
  rc__race_*     — yarış context (inline compute)
  ix__*          — interaction (career × race)
  pf__*          — polynomial (squared)

API:
  bundle = load_v6_compute()
  feats = bundle.build_features(horse, race_ctx)  # → 30 yeni feature dict

horse args (per horse, prod-time):
  horse_name, agf_pct, jockey_cond_top4, ...

race_ctx (per race, prod-time):
  agf_values (list[float], all horses)
  ages (list[int])
  weights (list[float])
  distance (int)
  group_name (str)

Hata durumunda her feature 0.0 → graceful degrade (Phase 11c-safe).
"""
from __future__ import annotations

import json
import math
import os
from typing import Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_REPO, 'data', 'horse_career_stats.json')

_cache = None
_loaded = False

# Feature names in fixed order — must match audit/103 + feature_columns_v6.json
NEW_FEATURE_NAMES = [
    # cf__ (career history, 14)
    'cf__career_n_races', 'cf__career_win_rate', 'cf__career_top3_rate',
    'cf__career_top4_rate', 'cf__career_avg_finish',
    'cf__career_recent5_top3_rate', 'cf__career_recent5_top4_rate',
    'cf__career_recent10_top3_rate', 'cf__career_recent10_top4_rate',
    'cf__career_days_since_top3',
    'cf__same_dist_top3_rate', 'cf__same_track_top3_rate',
    'cf__top3_streak', 'cf__below_streak',
    # rc__ (race-context, 7)
    'rc__field_size_class', 'rc__top1_agf', 'rc__agf_entropy',
    'rc__top1_top2_agf_gap', 'rc__top3_agf_share',
    'rc__field_avg_age', 'rc__field_avg_weight',
    # ix__ (interactions, 6)
    'ix__jockey_cond_x_top1agf', 'ix__agf_x_jockey_cond_top4',
    'ix__cond_n_x_career_top3', 'ix__breed_arap_x_distance',
    'ix__agf_x_distance', 'ix__jockey_cond_x_career_top3',
    # pf__ (polynomials, 3)
    'pf__agf_sq', 'pf__jockey_cond_top4_sq', 'pf__career_top3_rate_sq',
]


def _load_snapshot():
    global _cache, _loaded
    if _loaded:
        return _cache
    _loaded = True
    try:
        if os.path.exists(_PATH):
            with open(_PATH, encoding='utf-8') as f:
                _cache = json.load(f).get('horses') or {}
    except Exception:
        _cache = {}
    return _cache or {}


def _career_stats(horse_name):
    snap = _load_snapshot()
    rec = snap.get(horse_name) or {}
    return {
        'cf__career_n_races': float(rec.get('career_n_races') or 0),
        'cf__career_win_rate': float(rec.get('career_win_rate') or 0),
        'cf__career_top3_rate': float(rec.get('career_top3_rate') or 0),
        'cf__career_top4_rate': float(rec.get('career_top4_rate') or 0),
        'cf__career_avg_finish': float(rec.get('career_avg_finish') or 0),
        'cf__career_recent5_top3_rate': float(rec.get('career_recent5_top3_rate') or 0),
        'cf__career_recent5_top4_rate': float(rec.get('career_recent5_top4_rate') or 0),
        'cf__career_recent10_top3_rate': float(rec.get('career_recent10_top3_rate') or 0),
        'cf__career_recent10_top4_rate': float(rec.get('career_recent10_top4_rate') or 0),
        'cf__career_days_since_top3': float(rec.get('career_days_since_top3') or 365.0),
        'cf__same_dist_top3_rate': float(rec.get('same_dist_top3_rate') or 0),
        'cf__same_track_top3_rate': float(rec.get('same_track_top3_rate') or 0),
        'cf__top3_streak': float(rec.get('top3_streak') or 0),
        'cf__below_streak': float(rec.get('below_streak') or 0),
    }


def _field_size_class(n):
    if n < 6: return 1
    if n < 9: return 2
    if n < 13: return 3
    if n < 16: return 4
    return 5


def _race_context(agf_values, ages, weights):
    """Yarış-bazlı aggregate (cross-section, leak-free)."""
    agfs = [float(a or 0) for a in agf_values]
    if not agfs:
        return {
            'rc__field_size_class': 1, 'rc__top1_agf': 0.0, 'rc__agf_entropy': 0.0,
            'rc__top1_top2_agf_gap': 0.0, 'rc__top3_agf_share': 0.0,
            'rc__field_avg_age': 0.0, 'rc__field_avg_weight': 0.0,
        }
    sorted_desc = sorted(agfs, reverse=True)
    top1 = sorted_desc[0]
    top2 = sorted_desc[1] if len(sorted_desc) >= 2 else 0.0
    top3_share = sum(sorted_desc[:3]) / 100.0
    # Entropy
    total = sum(agfs) or 1.0
    probs = [max(a, 1e-9) / total for a in agfs]
    entropy = -sum(p * math.log(p) for p in probs)
    avg_age = sum(a or 0 for a in ages) / len(ages) if ages else 0.0
    avg_w = sum(w or 0 for w in weights) / len(weights) if weights else 0.0
    return {
        'rc__field_size_class': _field_size_class(len(agfs)),
        'rc__top1_agf': float(top1),
        'rc__agf_entropy': float(entropy),
        'rc__top1_top2_agf_gap': float(top1 - top2),
        'rc__top3_agf_share': float(top3_share),
        'rc__field_avg_age': float(avg_age),
        'rc__field_avg_weight': float(avg_w),
    }


def _interactions(career, rc, agf_pct, jockey_cond_top4, distance, is_arap):
    """Career × Race interactions."""
    agf01 = float(agf_pct or 0) / 100.0
    dist_k = float(distance or 1400) / 1000.0
    jck = float(jockey_cond_top4 or 0)
    return {
        'ix__jockey_cond_x_top1agf': jck * (rc.get('rc__top1_agf', 0) / 100.0),
        'ix__agf_x_jockey_cond_top4': agf01 * jck,
        'ix__cond_n_x_career_top3': 0.0,   # career_n_races field değiştirilmedi şu an, placeholder
        'ix__breed_arap_x_distance': (1.0 if is_arap else 0.0) * dist_k,
        'ix__agf_x_distance': agf01 * dist_k,
        'ix__jockey_cond_x_career_top3': jck * career.get('cf__career_top3_rate', 0),
    }


def _polynomials(agf_pct, jockey_cond_top4, career_top3_rate):
    agf01 = float(agf_pct or 0) / 100.0
    jck = float(jockey_cond_top4 or 0)
    ctr = float(career_top3_rate or 0)
    return {
        'pf__agf_sq': agf01 ** 2,
        'pf__jockey_cond_top4_sq': jck ** 2,
        'pf__career_top3_rate_sq': ctr ** 2,
    }


def compute_horse(horse_name, agf_pct, jockey_cond_top4, distance, group_name, race_ctx):
    """Tüm 30 yeni feature için dict döner."""
    career = _career_stats(horse_name)
    rc = race_ctx
    is_arap = 'arap' in (group_name or '').lower()
    ix = _interactions(career, rc, agf_pct, jockey_cond_top4, distance, is_arap)
    pf = _polynomials(agf_pct, jockey_cond_top4, career.get('cf__career_top3_rate', 0))
    out = {}
    out.update(career)
    out.update(rc)
    out.update(ix)
    out.update(pf)
    return out


def compute_race_context(horses_meta):
    """horses_meta: list of dicts with agf_pct, age, weight.
    Returns 7 rc__ feature dict.
    """
    return _race_context(
        agf_values=[h.get('agf_pct') for h in horses_meta],
        ages=[h.get('age') for h in horses_meta],
        weights=[h.get('weight') for h in horses_meta],
    )


def get_v6_feature_names():
    return list(NEW_FEATURE_NAMES)


def stats():
    snap = _load_snapshot()
    return {'loaded': bool(snap), 'n_horses': len(snap)}
