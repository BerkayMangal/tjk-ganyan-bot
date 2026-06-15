"""Phase 5.8.8 — At idman dereceleri özet ve cache.

simulation/scrapers/tjk_horse_idman.fetch_horse_idman(at_adi) → 50+ idman kaydı
döner; biz bunu cache'e koyup feature özeti üretiriz.

Public API:
    fetch_summary(at_adi, target_distance, force_refresh=False) → dict
      {
        'n_30d': 12,
        'days_since_last': 3,
        'best_speed_at_dist': 14.06,    # m/s, target_distance için
        'avg_speed_at_dist': 13.42,
        'has_recent_fast_work': True,    # son 14 gün idman_tur='Fast Work'?
        'jokey_son_idman': 'HACİ ALTUNBAŞ',
        ...
      }

Cache: data/idman_cache/<YYYY-MM-DD>/<slug>.json — günlük (24h stale).
Politeness: çağıran satır 2s sleep yapsın (toplu çekimde).
"""
from __future__ import annotations

import json
import os
import re
import time
from datetime import date, timedelta
from typing import Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_REPO, 'data', 'idman_cache')

# Hız bantları: yarış mesafesine göre idman'da hangi geçiş zamanını sorgularız
DIST_NEAREST = [200, 400, 600, 800, 1000, 1200, 1400]


def _slug(name):
    if not name:
        return '_empty'
    s = name.lower().translate(str.maketrans('İıÇçĞğÖöŞşÜü', 'iiccggoossuu'))
    s = re.sub(r'[^a-z0-9]+', '_', s).strip('_')
    return s or '_empty'


def _cache_path(at_adi, day):
    d = day if isinstance(day, str) else day.isoformat()
    return os.path.join(CACHE_DIR, d, _slug(at_adi) + '.json')


def _load_cache(at_adi, day):
    p = _cache_path(at_adi, day)
    if not os.path.exists(p):
        return None
    try:
        with open(p, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _save_cache(at_adi, day, recs):
    p = _cache_path(at_adi, day)
    os.makedirs(os.path.dirname(p), exist_ok=True)
    try:
        with open(p, 'w', encoding='utf-8') as f:
            json.dump(recs, f, ensure_ascii=False, separators=(',', ':'))
    except Exception:
        pass


def fetch_idman(at_adi, day=None, force_refresh=False, politeness=0.0):
    """Cache veya canlı çek (politeness saniye)."""
    if not at_adi:
        return []
    if day is None:
        day = date.today()
    if not force_refresh:
        cached = _load_cache(at_adi, day)
        if cached is not None:
            return cached
    if politeness > 0:
        time.sleep(politeness)
    try:
        from simulation.scrapers.tjk_horse_idman import fetch_horse_idman
        recs = fetch_horse_idman(at_adi)
        _save_cache(at_adi, day, recs)
        return recs
    except Exception:
        return []


def _nearest_dist(target):
    if not target:
        return 600
    return min(DIST_NEAREST, key=lambda d: abs(d - target))


def summarize(recs, target_distance, window_days=30):
    """Feature özet üret."""
    if not recs:
        return None
    today_iso = date.today().isoformat()
    cutoff = (date.today() - timedelta(days=window_days)).isoformat()
    recent = [r for r in recs if (r.get('idman_date') or '') >= cutoff]
    n = len(recent)
    # En yakın mesafe bandı (hedef yarış mesafesi → ona en yakın idman geçiş alanı)
    nd = _nearest_dist(int(target_distance) if target_distance else 600)
    key = f"t_{nd}"
    speeds = [nd / r[key] for r in recent if r.get(key) and r[key] > 0]
    # FALLBACK: hedef mesafede speed yoksa, idmanlarda en sık dolu mesafeyi bul
    if not speeds:
        candidates = [200, 400, 600, 800, 1000, 1200, 1400]
        candidates.sort(key=lambda x: abs(x - nd))   # hedef mesafeye yakınlık önceliği
        for fb in candidates:
            fb_speeds = [fb / r[f"t_{fb}"] for r in recent
                          if r.get(f"t_{fb}") and r[f"t_{fb}"] > 0]
            if fb_speeds:
                nd, speeds = fb, fb_speeds
                break
    best = max(speeds) if speeds else None
    avg = (sum(speeds) / len(speeds)) if speeds else None
    # Son idman tarihi
    dates = sorted([r.get('idman_date') for r in recs if r.get('idman_date')], reverse=True)
    last_date = dates[0] if dates else None
    days_since = None
    if last_date:
        try:
            days_since = (date.today() - date.fromisoformat(last_date)).days
        except Exception:
            pass
    # Fast work?
    fast_recent = [r for r in recent if 'HIZLI' in str(r.get('idman_tur') or '').upper()
                    or 'FAST' in str(r.get('idman_tur') or '').upper()]
    # Son jokey
    last_jokey = ''
    if recs:
        last_jokey = recs[0].get('jokey') or ''
    return {
        'n_window': n,
        'window_days': window_days,
        'nearest_dist': nd,
        'target_distance': target_distance,
        'best_speed': round(best, 2) if best else None,
        'avg_speed': round(avg, 2) if avg else None,
        'last_idman_date': last_date,
        'days_since_last': days_since,
        'fast_work_count_window': len(fast_recent),
        'last_idman_jokey': last_jokey,
    }


def fetch_summary(at_adi, target_distance, force_refresh=False, politeness=2.0):
    """Tek çağrı: cache/canlı + özet. Çağıran 60+ at için sıraya koysun."""
    recs = fetch_idman(at_adi, force_refresh=force_refresh, politeness=politeness)
    return summarize(recs, target_distance)
