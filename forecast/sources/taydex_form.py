"""Taydex DB → at form history with REAL finish positions.

V8 modelinin ana labelı "top-N hit". TJK derece scraper bunu vermez
(sadece zaman). Taydex production DB'sinde race_horses tablosunda
finish_position field'ı var — bu modül onu çeker.

Berkay (2026-06-27): "taydex datasindan da cekebilirsin oraya bagli
olmamiz lazim bence. modelimiz artik bu oluyor".

DSN: TAYDEX_DSN env (prod'da set, lokal'de yok). Graceful no-op
lokal'de — feature builder fallback (zaman → estimated rank) kullanır.

API
---
- `fetch_horse_form(horse_name, limit=20)` → list[dict] (en taze önce)
- `is_available()` → bool
- `parse_form_string(form_str)` → list[int]  (örn '1-3-2' → [1,3,2])
"""
from __future__ import annotations

import logging
import os
from typing import Optional

logger = logging.getLogger(__name__)

DSN_ENV = "TAYDEX_DSN"
CONNECT_TIMEOUT = 5


def _dsn() -> Optional[str]:
    return os.environ.get(DSN_ENV)


def is_available() -> bool:
    """Probe whether Taydex DB is reachable."""
    dsn = _dsn()
    if not dsn:
        return False
    try:
        import psycopg2
        conn = psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT)
        conn.close()
        return True
    except Exception as exc:
        logger.debug(f"Taydex not available: {exc}")
        return False


# SQL: race_horses + races + horses join
_SQL_FORM_BY_NAME = """
SELECT
    r.race_date AS date,
    rh.finish_position AS finish,
    r.distance,
    r.track_type,
    r.group_name AS kosu_cinsi,
    r.hippodrome_name AS sehir,
    rh.weight_carried AS kilo,
    rh.jockey_name,
    rh.horse_number
FROM race_horses rh
JOIN races r ON rh.race_id = r.id
JOIN horses h ON rh.horse_id = h.id
WHERE UPPER(h.name) = UPPER(%s)
  AND rh.finish_position IS NOT NULL
ORDER BY r.race_date DESC
LIMIT %s
"""


def fetch_horse_form(horse_name: str, limit: int = 20) -> list[dict]:
    """At için form history (Taydex DB).

    Returns:
        list of dicts (en taze önce), each with:
          - date (str YYYY-MM-DD)
          - finish (int) ← REAL finish position
          - distance, track_type, kosu_cinsi, kilo, jockey_name

    Empty list if DSN missing or query fails.
    """
    dsn = _dsn()
    if not dsn or not horse_name:
        return []
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError:
        logger.debug("psycopg2 not available")
        return []

    try:
        conn = psycopg2.connect(dsn, connect_timeout=CONNECT_TIMEOUT)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(_SQL_FORM_BY_NAME, (horse_name, limit))
            rows = cur.fetchall()
        conn.close()
    except Exception as exc:
        logger.debug(f"fetch_horse_form fail for {horse_name}: {exc}")
        return []

    out: list[dict] = []
    for r in rows:
        # Normalize to our internal shape
        out.append({
            "date": str(r["date"]) if r.get("date") else None,
            "finish": int(r["finish"]) if r.get("finish") else None,
            "mesafe": int(r["distance"]) if r.get("distance") else None,
            "pist": _track_tr(r.get("track_type")),
            "kosu_cinsi": r.get("kosu_cinsi") or "",
            "sehir": r.get("sehir") or "",
            "kilo": float(r["kilo"]) if r.get("kilo") else None,
            "jockey_name": (r.get("jockey_name") or "").strip(),
            "horse_number": (int(r["horse_number"])
                             if r.get("horse_number") else None),
            "source": "taydex",
        })
    return out


def _track_tr(track_type) -> str:
    """DB track_type → TR format."""
    if not track_type:
        return ""
    t = str(track_type).lower()
    if "dirt" in t or "sand" in t or "kum" in t:
        return "Kum"
    if "turf" in t or "çim" in t or "cim" in t:
        return "Çim"
    if "syn" in t or "sentetik" in t:
        return "Sentetik"
    return str(track_type)


def parse_form_string(form_str: Optional[str]) -> list[int]:
    """TJK form string → finish list.

    '1-3-2-4-1' → [1, 3, 2, 4, 1]
    '13241' → [1, 3, 2, 4, 1]
    """
    if not form_str:
        return []
    s = str(form_str)
    digits: list[int] = []
    for ch in s:
        if ch.isdigit():
            try:
                d = int(ch)
                if 1 <= d <= 9:
                    digits.append(d)
            except ValueError:
                pass
    return digits


def merge_history_sources(
    horse_name: str,
    fallback_history: Optional[list[dict]] = None,
) -> list[dict]:
    """En iyi data source'undan merge.

    Öncelik:
        1. Taydex DB (gerçek finish position)
        2. Fallback: passed history (zamandan estimated finish)
    """
    if is_available():
        taydex = fetch_horse_form(horse_name)
        if taydex:
            return taydex
    if fallback_history:
        # Enrich fallback with estimated finish
        try:
            from forecast.finish_estimator import enrich_history
            return enrich_history(fallback_history)
        except ImportError:
            return fallback_history
    return []
