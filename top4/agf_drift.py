"""AGF drift helpers for the experimental Top-4 layer.

Compute open→now drift, rank movement, staleness, and produce a small
struct that role assignment / role reasoning can consume.

Inputs are intentionally permissive: missing snapshots → graceful
neutral output with `status` set to `MISSING` or `STALE`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional


@dataclass
class DriftRow:
    horse_no: int
    agf_open: Optional[float]
    agf_now: Optional[float]
    agf_drift_abs: Optional[float]
    agf_drift_rel: Optional[float]
    agf_rank_open: Optional[int]
    agf_rank_now: Optional[int]
    agf_rank_movement: Optional[int]
    status: str = "OK"  # OK | MISSING | STALE


@dataclass
class DriftReport:
    rows: list[DriftRow]
    snapshot_open_ts: Optional[str]
    snapshot_now_ts: Optional[str]
    is_stale: bool
    is_missing: bool
    notes: list[str] = field(default_factory=list)


def _safe_float(x) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _rank_by_agf(values: list[tuple[int, Optional[float]]]) -> dict[int, Optional[int]]:
    valid = [(h, v) for h, v in values if v is not None]
    if not valid:
        return {h: None for h, _ in values}
    valid.sort(key=lambda kv: kv[1] or 0.0, reverse=True)
    out: dict[int, Optional[int]] = {h: None for h, _ in values}
    for r, (h, _v) in enumerate(valid, start=1):
        out[h] = r
    return out


def _is_stale(now_ts: Optional[str], threshold_minutes: int = 60) -> bool:
    if not now_ts:
        return True
    try:
        dt = datetime.fromisoformat(now_ts.replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return True
    delta = (datetime.now(timezone.utc) - dt).total_seconds() / 60.0
    return delta > threshold_minutes


def compute_drift(
    horses: Iterable[Mapping],
    agf_snapshot_open: Optional[Mapping] = None,
    agf_snapshot_now: Optional[Mapping] = None,
    stale_threshold_minutes: int = 60,
) -> DriftReport:
    """Inputs:

      horses: iterable of dicts with at least `horse_no`; may carry
              inline `agf_open`/`agf_now` already.
      agf_snapshot_open: optional dict with keys `ts` and
              `horses` -> {horse_no: pct}
      agf_snapshot_now:  same shape as `_open`.

    Returns a DriftReport. NEVER raises.
    """
    horses = list(horses)
    if not horses:
        return DriftReport(rows=[], snapshot_open_ts=None,
                           snapshot_now_ts=None,
                           is_stale=False, is_missing=True,
                           notes=["empty horses"])

    open_map: dict[int, Optional[float]] = {}
    now_map: dict[int, Optional[float]] = {}
    open_ts: Optional[str] = None
    now_ts: Optional[str] = None

    if agf_snapshot_open and isinstance(agf_snapshot_open, Mapping):
        open_ts = agf_snapshot_open.get("ts")
        for h, v in (agf_snapshot_open.get("horses") or {}).items():
            try:
                open_map[int(h)] = _safe_float(v)
            except (TypeError, ValueError):
                continue
    if agf_snapshot_now and isinstance(agf_snapshot_now, Mapping):
        now_ts = agf_snapshot_now.get("ts")
        for h, v in (agf_snapshot_now.get("horses") or {}).items():
            try:
                now_map[int(h)] = _safe_float(v)
            except (TypeError, ValueError):
                continue

    # Inline fallback from horses
    open_pairs: list[tuple[int, Optional[float]]] = []
    now_pairs: list[tuple[int, Optional[float]]] = []
    for h in horses:
        try:
            hn = int(h.get("horse_no"))
        except (TypeError, ValueError):
            continue
        o = open_map.get(hn, _safe_float(h.get("agf_open")))
        n = now_map.get(hn, _safe_float(h.get("agf_now") or h.get("agf")))
        open_pairs.append((hn, o))
        now_pairs.append((hn, n))

    rank_open = _rank_by_agf(open_pairs)
    rank_now = _rank_by_agf(now_pairs)

    notes: list[str] = []
    # Only run staleness check if a snapshot dict was explicitly provided
    # AND it carried a `ts`. Inline-only AGF (no snapshot dict) is treated
    # as fresh — the caller never claimed a timestamp.
    if agf_snapshot_now is not None:
        is_stale = _is_stale(now_ts, threshold_minutes=stale_threshold_minutes)
    else:
        is_stale = False
    is_missing = not now_pairs or all(n is None for _h, n in now_pairs)
    if is_missing:
        notes.append("AGF_MISSING")
    elif is_stale:
        notes.append("AGF_STALE")

    rows: list[DriftRow] = []
    for (hn, o), (_, n) in zip(open_pairs, now_pairs):
        if o is not None and n is not None:
            drift_abs = n - o
            denom = max(o, 0.5)
            drift_rel = drift_abs / denom
        else:
            drift_abs = None
            drift_rel = None
        ro = rank_open.get(hn)
        rn = rank_now.get(hn)
        rank_mv = (ro - rn) if (ro is not None and rn is not None) else None
        status = "OK"
        if n is None and o is None:
            status = "MISSING"
        elif is_stale:
            status = "STALE"
        rows.append(DriftRow(
            horse_no=hn, agf_open=o, agf_now=n,
            agf_drift_abs=drift_abs, agf_drift_rel=drift_rel,
            agf_rank_open=ro, agf_rank_now=rn,
            agf_rank_movement=rank_mv, status=status,
        ))

    return DriftReport(rows=rows, snapshot_open_ts=open_ts,
                       snapshot_now_ts=now_ts,
                       is_stale=is_stale and not is_missing,
                       is_missing=is_missing, notes=notes)


def drift_reason_for(drift_row: DriftRow, model_rank: int) -> Optional[str]:
    """Translate a drift row into a short Turkish reason fragment for
    role text. Conservative: only fires for clearly directional moves
    and only when AGF is OK (not STALE/MISSING).
    """
    if drift_row.status != "OK":
        return None
    if drift_row.agf_drift_rel is None:
        return None
    abs_chg = abs(drift_row.agf_drift_rel)
    if abs_chg < 0.20:
        return None
    direction = "yükselen" if drift_row.agf_drift_rel > 0 else "düşen"
    if drift_row.agf_drift_rel > 0 and model_rank <= 4:
        return f"canlı AGF hareketi {direction} ({drift_row.agf_drift_rel:+.0%})"
    if drift_row.agf_drift_rel < 0 and model_rank <= 3:
        return f"AGF eriyor — sharp money adayı ({drift_row.agf_drift_rel:+.0%})"
    return None
