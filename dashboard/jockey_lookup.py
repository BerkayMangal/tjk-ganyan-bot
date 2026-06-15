"""Phase 5.8.7 — Jokey × mesafe × track conditional rate lookup.

data/jockey_distance_buckets.json (audit/93 ile üretilen, 134 KB, commit'li, Railway'e
gider) yükler ve predict-time hızlı lookup sunar.

Public API:
    cond_top4(jockey, distance, track) -> Optional[float]  # 0-1
    cond_win(jockey, distance, track)  -> Optional[float]
    overall(jockey)                     -> Optional[dict]   # fallback
    enrich_horse(horse_dict)            -> in-place horse['jockey_dist_top4'] ekler

Sıralama: önce conditional (n≥20), yoksa generic. Hiç kayıt yoksa None (no-op).
Never-raises.
"""
from __future__ import annotations

import json
import os
from typing import Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_PATH = os.path.join(_REPO, 'data', 'jockey_distance_buckets.json')
_cache = None
_loaded = False
_MIN_N = 20


def _norm_track(t):
    if t is None:
        return 'unknown'
    s = str(t).strip().lower()
    s = s.replace('ı', 'i').replace('ç', 'c').replace('ğ', 'g')
    s = s.replace('ö', 'o').replace('ş', 's').replace('ü', 'u')
    if 'kum' in s or 'dirt' in s or 'sand' in s: return 'kum'
    if 'cim' in s or 'turf' in s or 'grass' in s: return 'cim'
    if 'sent' in s or 'syn' in s: return 'sentetik'
    return 'unknown'


def _dist_band(d):
    try:
        d = int(d)
    except (ValueError, TypeError):
        return 'unknown'
    if d <= 1400: return 'sprint'
    if d <= 1700: return 'mid'
    if d <= 2100: return 'long'
    return 'marathon'


def _load():
    global _cache, _loaded
    if _loaded:
        return _cache
    _loaded = True
    try:
        if os.path.exists(_PATH):
            with open(_PATH, encoding='utf-8') as f:
                _cache = json.load(f)
    except Exception:
        _cache = None
    return _cache


def _conditional(jockey, distance, track, field):
    if not jockey:
        return None
    d = _load()
    if not d:
        return None
    bucket = (d.get('jockey_buckets') or {}).get(jockey)
    if not bucket:
        return None
    key = f"{_dist_band(distance)}__{_norm_track(track)}"
    rec = bucket.get(key)
    if not rec or rec.get('n', 0) < _MIN_N:
        return None
    return float(rec.get(field) or 0)


def cond_top4(jockey, distance, track):
    return _conditional(jockey, distance, track, 'top4_rate')


def cond_win(jockey, distance, track):
    return _conditional(jockey, distance, track, 'win_rate')


def overall(jockey):
    if not jockey:
        return None
    d = _load()
    if not d:
        return None
    return (d.get('jockey_overall') or {}).get(jockey)


def enrich_horse(h):
    """horse dict üzerine in-place 'jockey_cond_top4', 'jockey_overall_top4' ekle.

    Beklenen anahtarlar: 'jockey_name' (veya 'jockey'), 'distance' (veya 'race_distance'),
    'track_type'. Yoksa None değerleri yazılır (UI fallback için).
    """
    jk = h.get('jockey_name') or h.get('jockey')
    dist = h.get('distance') or h.get('race_distance')
    track = h.get('track_type') or h.get('track')
    h['jockey_cond_top4'] = cond_top4(jk, dist, track)
    h['jockey_cond_win'] = cond_win(jk, dist, track)
    ov = overall(jk)
    h['jockey_overall_top4'] = (ov or {}).get('top4_rate')
    h['jockey_overall_n'] = (ov or {}).get('n')
    return h


def stats():
    """Lookup içeriği özet (sağlık kontrolü için)."""
    d = _load()
    if not d:
        return {'loaded': False}
    return {
        'loaded': True,
        'jockeys_with_buckets': d.get('jockeys_with_buckets'),
        'overall_fallback_jockeys': d.get('overall_fallback_jockeys'),
        'n_rows_source': d.get('n_rows'),
        'date_range': d.get('date_range'),
        'walk_forward_drift': d.get('walk_forward_drift'),
    }
