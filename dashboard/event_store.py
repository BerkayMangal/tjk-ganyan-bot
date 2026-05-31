"""Phase 1A.5 — Persistent event storage (Supabase `pipeline_events`).

Writer-bug-independent, ADDITIVE storage. Bypasses the broken kupon writer
(kupon_dar vs dar) and the ephemeral /data volume. Every pipeline event flows
into one generic table.

Design:
  - Reads TJK_MEASURE_DB_URL. If unset → graceful no-op + WARNING (local dev OK).
  - Fresh psycopg2 connection per call (NO pooling this round — simplicity).
  - NEVER touches measurement_db.py. Fully isolated.
  - Never raises into the caller — write/read failures return False/[] + warning.
"""
from __future__ import annotations

import logging
import os
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger(__name__)

ENV_DB_URL = "TJK_MEASURE_DB_URL"
CONNECT_TIMEOUT = 10
VALID_EVENT_TYPES = {
    "kupon_generated",
    "shadow_validation",
    "retro_result",
    "agf_fetch",
    "pipeline_run",
    "bet_decision",
    "daily_snapshot",   # Phase 7: snapshot persistence (Railway ephemeral disk fix)
}


@dataclass
class EventRecord:
    """One row destined for pipeline_events."""
    event_type: str
    payload: dict = field(default_factory=dict)
    event_date: Optional[str] = None      # ISO date (yarış günü), opsiyonel
    hippodrome: Optional[str] = None
    altili_no: Optional[int] = None
    timestamp: str = ""                   # set at write time if empty

    def to_dict(self) -> dict:
        return asdict(self)


def _db_url() -> str:
    return (os.environ.get(ENV_DB_URL) or "").strip()


def is_enabled() -> bool:
    """True if a DB URL is configured (writes will be attempted)."""
    return bool(_db_url())


def write_event(
    event_type: str,
    payload: dict,
    event_date: Optional[str] = None,
    hippodrome: Optional[str] = None,
    altili_no: Optional[int] = None,
) -> bool:
    """Append one event. Returns True on insert, False on no-op/failure.

    Graceful: never raises. URL yoksa warning + False (lokal dev'de normal).
    """
    url = _db_url()
    if not url:
        logger.warning("event_store: %s not set — write_event('%s') no-op", ENV_DB_URL, event_type)
        return False

    if event_type not in VALID_EVENT_TYPES:
        # Yine de yaz ama uyar — şema event_type'ı serbest, sadece konvansiyon.
        logger.warning("event_store: bilinmeyen event_type '%s' (yine de yazılıyor)", event_type)

    try:
        import psycopg2
        from psycopg2.extras import Json
    except ImportError as e:
        logger.warning("event_store: psycopg2 missing: %s", e)
        return False

    conn = None
    try:
        conn = psycopg2.connect(url, connect_timeout=CONNECT_TIMEOUT)
        conn.autocommit = True
        with conn.cursor() as cur:
            cur.execute(
                "INSERT INTO pipeline_events "
                "(event_type, event_date, hippodrome, altili_no, payload) "
                "VALUES (%s, %s, %s, %s, %s)",
                (event_type, event_date, hippodrome, altili_no, Json(payload or {})),
            )
        return True
    except Exception as e:
        logger.warning("event_store: write_event('%s') failed: %s", event_type, repr(e)[:140])
        return False
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


def read_events(
    event_type: str,
    since: Optional[str] = None,
    limit: int = 100,
) -> list[dict]:
    """Read recent events of a type (newest first). Returns [] on no-op/failure."""
    url = _db_url()
    if not url:
        logger.warning("event_store: %s not set — read_events('%s') → []", ENV_DB_URL, event_type)
        return []

    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as e:
        logger.warning("event_store: psycopg2 missing: %s", e)
        return []

    conn = None
    try:
        conn = psycopg2.connect(url, connect_timeout=CONNECT_TIMEOUT)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            if since:
                cur.execute(
                    "SELECT * FROM pipeline_events WHERE event_type = %s AND timestamp >= %s "
                    "ORDER BY timestamp DESC LIMIT %s",
                    (event_type, since, limit),
                )
            else:
                cur.execute(
                    "SELECT * FROM pipeline_events WHERE event_type = %s "
                    "ORDER BY timestamp DESC LIMIT %s",
                    (event_type, limit),
                )
            return [dict(r) for r in cur.fetchall()]
    except Exception as e:
        logger.warning("event_store: read_events('%s') failed: %s", event_type, repr(e)[:140])
        return []
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# ─────────────────────────────────────────────────────────────────────────────
# Phase 7 — DAILY SNAPSHOT (retro öğrenme için, ephemeral disk bypass)
# ─────────────────────────────────────────────────────────────────────────────

def save_daily_snapshot(date_iso: str, payload: dict) -> bool:
    """Pipeline result dict'ini DB'de sakla (retro için kalıcı). Railway ephemeral disk
    dosyaları siliyor → DB persistence olmadan retro 'no_snapshot'da takılıyor."""
    return write_event(event_type="daily_snapshot", payload=payload or {}, event_date=date_iso)


def load_daily_snapshot(date_iso: str) -> Optional[dict]:
    """Bir tarihin en son daily_snapshot event'ini oku. None = yok / DB no-op."""
    url = _db_url()
    if not url:
        return None
    try:
        import psycopg2
        from psycopg2.extras import RealDictCursor
    except ImportError as e:
        logger.warning("event_store: psycopg2 missing: %s", e)
        return None
    conn = None
    try:
        conn = psycopg2.connect(url, connect_timeout=CONNECT_TIMEOUT)
        with conn.cursor(cursor_factory=RealDictCursor) as cur:
            cur.execute(
                "SELECT payload FROM pipeline_events "
                "WHERE event_type = 'daily_snapshot' AND event_date = %s "
                "ORDER BY timestamp DESC LIMIT 1",
                (date_iso,),
            )
            row = cur.fetchone()
            if not row:
                return None
            pl = row.get("payload")
            return dict(pl) if pl else None
    except Exception as e:
        logger.warning("event_store: load_daily_snapshot('%s') failed: %s",
                       date_iso, repr(e)[:140])
        return None
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass
