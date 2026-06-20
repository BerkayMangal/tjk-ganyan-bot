"""Durable storage backend for the BERKAY BİLİMSEL DENEME TOP4 layer.

Uses the existing `dashboard.event_store` (Supabase `pipeline_events`
generic JSONB table). Two new event types are emitted:

  - `berkay_top4_prediction`  — payload = the full prediction row
  - `berkay_top4_result`      — payload = the full result row

This module never raises. When no DB URL is set, all operations are
no-ops and return False / [].

A separate, strongly-typed migration is shipped at
`dashboard/migrations/m5_berkay_top4_shadow.sql` for users who want
queryable typed columns later, but the default path uses the generic
table so no migration is required to start writing today.
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)

EVENT_PREDICTION = "berkay_top4_prediction"
EVENT_RESULT = "berkay_top4_result"


def _event_store():
    """Import lazily so unit tests without the dashboard package work."""
    try:
        from dashboard import event_store
        return event_store
    except Exception:
        try:
            import event_store  # type: ignore
            return event_store
        except Exception as exc:
            logger.debug("event_store import failed: %s", exc)
            return None


def is_db_enabled() -> bool:
    es = _event_store()
    if not es:
        return False
    try:
        return bool(es.is_enabled())
    except Exception:
        return False


def write_prediction(prediction_row: dict) -> bool:
    """Persist a prediction row via event_store. Idempotency is
    best-effort here: event_store has no unique constraint. We rely on
    the prediction_id in the payload so dedupe is possible at read time.
    """
    es = _event_store()
    if not es:
        return False
    try:
        return bool(es.write_event(
            event_type=EVENT_PREDICTION,
            payload=prediction_row or {},
            event_date=_date_iso(prediction_row.get("generated_at")),
            hippodrome=prediction_row.get("hippodrome"),
            altili_no=None,
        ))
    except Exception as exc:
        logger.warning("db_store.write_prediction failed: %s", exc)
        return False


def write_result(result_row: dict) -> bool:
    es = _event_store()
    if not es:
        return False
    try:
        return bool(es.write_event(
            event_type=EVENT_RESULT,
            payload=result_row or {},
            event_date=_date_iso(result_row.get("finalized_at")),
            hippodrome=None,
            altili_no=None,
        ))
    except Exception as exc:
        logger.warning("db_store.write_result failed: %s", exc)
        return False


def read_predictions_for_date(date_iso: str, limit: int = 1000) -> list[dict]:
    """Pull prediction payloads for a date. Returns [] on no-op/failure."""
    es = _event_store()
    if not es:
        return []
    try:
        events = es.read_events(EVENT_PREDICTION, limit=limit) or []
    except Exception:
        return []
    out: list[dict] = []
    for ev in events:
        if (ev.get("event_date") or "").startswith(date_iso):
            payload = ev.get("payload") or {}
            if isinstance(payload, dict):
                out.append(payload)
    return out


def read_results_for_date(date_iso: str, limit: int = 1000) -> list[dict]:
    es = _event_store()
    if not es:
        return []
    try:
        events = es.read_events(EVENT_RESULT, limit=limit) or []
    except Exception:
        return []
    out: list[dict] = []
    for ev in events:
        if (ev.get("event_date") or "").startswith(date_iso):
            payload = ev.get("payload") or {}
            if isinstance(payload, dict):
                out.append(payload)
    return out


def dedupe_predictions(rows: Iterable[dict]) -> list[dict]:
    """Keep latest occurrence of each prediction_id (insertion order
    preserved). Useful when reading from event_store which has no
    uniqueness guarantee."""
    seen: dict[str, dict] = {}
    for r in rows:
        pid = r.get("prediction_id")
        if not pid:
            # No id → keep all (no dedupe possible)
            seen[id(r)] = r  # type: ignore[index]
        else:
            seen[pid] = r
    return list(seen.values())


def _date_iso(ts: Optional[str]) -> Optional[str]:
    if not ts:
        return None
    return str(ts)[:10]
