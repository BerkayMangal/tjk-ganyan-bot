"""Live AGF insider signal detection (Phase 5.8.47).

Berkay (2026-06-19): "canli AGF degisimi insider gibi dusun anomalik".

audit/139 ile keşfedilen MEGA pattern:
  - agf_open < 5% AND agf_close/agf_open <= 0.80 → win %44.4 (n=54, +9.8pp baseline)

Bu modül her pick yapılırken Taydex odds_snapshots'tan pre-race AGF time-series
çekip insider sinyalleri hesaplar. Cache'li bulk fetch — race-time'da yavaş değil.

Public API:
  fetch_insider_signals_for_date(target_date) → dict[(hippo_norm, race_no, horse_no): InsiderSignals]
  InsiderSignals: dataclass with agf_open, agf_close, drop_pct, insider_longshot_alert
"""
from __future__ import annotations
import logging
import os
import unicodedata
from dataclasses import dataclass
from datetime import date
from typing import Dict, Optional, Tuple

logger = logging.getLogger(__name__)

# Cache per date (canlı pipeline'da her gün tek bulk fetch)
_DAY_CACHE: Dict[str, Dict[Tuple[str, int, int], 'InsiderSignals']] = {}


@dataclass
class InsiderSignals:
    """Per race_horse insider analizi."""
    agf_open: float          # Yarış öncesi ilk AGF snapshot
    agf_close: float         # Yarış başlangıcına en yakın AGF
    drop_pct: float          # (agf_close - agf_open) / agf_open * 100
    n_snap: int              # Snapshot sayısı
    agf_stddev: float        # AGF volatility
    insider_longshot_alert: bool   # MEGA pattern: agf<5% AND drop_pct≤-20
    description: str         # Kısa açıklama (Telegram için)


def _norm_hippo(name: Optional[str]) -> str:
    """ASCII-fold hipodrom adı (matching için)."""
    if not name: return ''
    s = unicodedata.normalize('NFKD', name)
    s = ''.join(c for c in s if not unicodedata.combining(c))
    return s.lower().replace(' hipodromu', '').replace(' hipodrom', '').strip()


def _get_dsn() -> Optional[str]:
    """Taydex DSN."""
    try:
        from scraper.taydex_source import _dsn
        return _dsn()
    except Exception:
        try:
            import sys
            sys.path.insert(0, os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), 'scraper'))
            from taydex_source import _dsn  # type: ignore
            return _dsn()
        except Exception as e:
            logger.warning(f'insider: DSN resolve fail: {e}')
            return None


def fetch_insider_signals_for_date(target_date) -> dict:
    """O günün tüm at-yarış kombinasyonları için insider sinyallerini bulk çek."""
    key = str(target_date) if target_date else date.today().isoformat()
    if key in _DAY_CACHE:
        return _DAY_CACHE[key]
    dsn = _get_dsn()
    if not dsn:
        _DAY_CACHE[key] = {}
        return {}
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
        sql = """
WITH base AS (
  SELECT race_horse_id, race_id, agf_value, captured_at
  FROM odds_snapshots
  WHERE race_date = %s AND agf_value IS NOT NULL
),
ranked AS (
  SELECT *,
    ROW_NUMBER() OVER (PARTITION BY race_horse_id ORDER BY captured_at) AS rn_asc,
    ROW_NUMBER() OVER (PARTITION BY race_horse_id ORDER BY captured_at DESC) AS rn_desc
  FROM base
),
agg AS (
  SELECT race_horse_id, race_id,
    MAX(CASE WHEN rn_asc = 1 THEN agf_value END) AS agf_open,
    MAX(CASE WHEN rn_desc = 1 THEN agf_value END) AS agf_close,
    COUNT(*) AS n_snap,
    STDDEV(agf_value) AS agf_stddev
  FROM ranked GROUP BY race_horse_id, race_id
)
SELECT a.race_horse_id,
       a.agf_open, a.agf_close, a.n_snap, a.agf_stddev,
       h.name AS hippodrome, r.race_number, rh.horse_number
FROM agg a
JOIN race_horses rh ON rh.id = a.race_horse_id
JOIN races r ON r.id = rh.race_id
JOIN program_results pr ON pr.id = r.program_result_id
JOIN hippodromes h ON h.id = pr.hippodrome_id
WHERE a.n_snap >= 5 AND a.agf_open > 0 AND a.agf_close > 0
"""
        conn = psycopg2.connect(dsn, connect_timeout=10)
        conn.set_session(readonly=True, autocommit=True)
        cur = conn.cursor(cursor_factory=RealDictCursor)
        cur.execute(sql, (key,))
        rows = cur.fetchall()
        conn.close()
        out: Dict[Tuple[str, int, int], InsiderSignals] = {}
        for r in rows:
            agf_open = float(r['agf_open']); agf_close = float(r['agf_close'])
            drop_pct = (agf_close - agf_open) / agf_open * 100.0 if agf_open > 0 else 0.0
            # MEGA pattern: deep longshot crash
            insider_longshot = (agf_open < 5.0 and drop_pct <= -20.0)
            desc = ''
            if insider_longshot:
                desc = f'agf {agf_open:.1f}%→{agf_close:.1f}% ({drop_pct:+.0f}%)'
            sig = InsiderSignals(
                agf_open=agf_open, agf_close=agf_close,
                drop_pct=drop_pct, n_snap=int(r['n_snap']),
                agf_stddev=float(r['agf_stddev'] or 0.0),
                insider_longshot_alert=insider_longshot,
                description=desc,
            )
            k = (_norm_hippo(r['hippodrome']), int(r['race_number']), int(r['horse_number']))
            out[k] = sig
        _DAY_CACHE[key] = out
        n_alerts = sum(1 for s in out.values() if s.insider_longshot_alert)
        logger.info(f'insider: {key} bulk fetched {len(out)} entries, {n_alerts} longshot alert')
        return out
    except Exception as e:
        logger.warning(f'insider: fetch fail for {key}: {e!r}')
        _DAY_CACHE[key] = {}
        return {}


def get_signal(hippo: str, race_no: int, horse_no: int,
               target_date=None) -> Optional[InsiderSignals]:
    """Tek at için insider signal lookup."""
    data = fetch_insider_signals_for_date(target_date)
    k = (_norm_hippo(hippo), int(race_no), int(horse_no))
    return data.get(k)


def list_alerts_today(target_date=None) -> list:
    """O günkü tüm 🔍 İNSİDER LONGSHOT alarmlarını döndür (hippo+race+horse ile)."""
    data = fetch_insider_signals_for_date(target_date)
    alerts = []
    for (hippo, race_no, horse_no), sig in data.items():
        if sig.insider_longshot_alert:
            alerts.append({
                'hippodrome': hippo,
                'race_no': race_no,
                'horse_no': horse_no,
                'agf_open': sig.agf_open,
                'agf_close': sig.agf_close,
                'drop_pct': sig.drop_pct,
                'description': sig.description,
            })
    return alerts
