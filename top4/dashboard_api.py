"""Dashboard view-model builder for BERKAY DENEME.

Aggregates shadow coupons + SİB picks + retro state into a single
JSON-safe payload that the HTML page can render. Pure read; no
side effects. NEVER raises.

Exports:
  - build_today_view(date_str=None) -> dict
  - build_history_view(days=14) -> dict
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import sib_log
from .experimental_logger import (
    read_predictions, read_results, _summary_path_for as _shadow_sum_path,
)

logger = logging.getLogger(__name__)


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _shadow_pick_outcome(pred: dict,
                         res_by_pid: dict,
                         res_by_race: dict) -> dict:
    """For one shadow prediction row, compute simple outcome flags."""
    pid = pred.get("prediction_id")
    rid = pred.get("race_id")
    res = res_by_pid.get(pid) if pid else None
    if not res and rid:
        res = res_by_race.get(rid)
    if not res:
        return {"status": "pending"}
    top4 = set(res.get("top4_actual") or [])
    bankers = set(pred.get("bankers") or [])
    candidate = set(pred.get("candidate_set") or [])
    return {
        "status": "graded",
        "winner": (res.get("finish_order") or [None])[0],
        "top4_actual": list(top4),
        "banker_survived": bool(bankers and bankers.issubset(top4)),
        "candidate_hit": bool(candidate) and top4.issubset(candidate),
        "small_hit": bool(res.get("small_ticket_hit")),
        "balanced_hit": bool(res.get("balanced_ticket_hit")),
        "wide_hit": bool(res.get("wide_ticket_hit")),
    }


def build_today_view(date_str: Optional[str] = None) -> dict:
    """One-page view-model for `/api/berkay_deneme/today`."""
    date_str = date_str or _today_str()
    try:
        preds = read_predictions(date_str)
    except Exception as exc:
        logger.debug("read_predictions: %s", exc)
        preds = []
    try:
        results = read_results(date_str)
    except Exception as exc:
        logger.debug("read_results: %s", exc)
        results = []
    res_by_pid = {r.get("prediction_id"): r for r in results
                  if r.get("prediction_id")}
    res_by_race = {r.get("race_id"): r for r in results
                   if r.get("race_id")}

    shadow_rows: list[dict] = []
    for p in preds:
        outcome = _shadow_pick_outcome(p, res_by_pid, res_by_race)
        shadow_rows.append({
            "race_id": p.get("race_id"),
            "race_label": p.get("race_label"),
            "race_time": p.get("race_time"),
            "hippodrome": p.get("hippodrome"),
            "field_size": p.get("field_size"),
            "confidence": p.get("confidence"),
            "recommended_mode": p.get("recommended_mode"),
            "bankers": p.get("bankers") or [],
            "candidate_set": p.get("candidate_set") or [],
            "engine_status": p.get("engine_status"),
            "telegram_sent": p.get("telegram_sent"),
            "outcome": outcome,
            # rich horse list — keep just the role-tagged horses + names
            "horses": [
                {
                    "horse_no": h.get("horse_no"),
                    "horse_name": h.get("horse_name"),
                    "role": h.get("role"),
                    "p_top4_cal": h.get("p_top4_cal"),
                    "mp": h.get("mp"),
                    "agf_now": h.get("agf_now"),
                    "value_tag": h.get("value_tag"),
                    "value_gap_pct": h.get("value_gap_pct"),
                }
                for h in (p.get("horses") or [])
            ],
        })

    # SİB picks + results
    try:
        sib_picks = sib_log.read_picks(date_str)
        sib_results = sib_log.read_results(date_str)
    except Exception as exc:
        logger.debug("sib_log read: %s", exc)
        sib_picks, sib_results = [], []
    sib_res_by_key = {r.get("pick_key"): r for r in sib_results
                      if r.get("pick_key")}
    sib_rows: list[dict] = []
    for p in sib_picks:
        res = sib_res_by_key.get(p.get("pick_key"))
        sib_rows.append({
            "tier": p.get("tier"),
            "hippo": p.get("hippo"),
            "race_no": p.get("race_no"),
            "race_time": p.get("race_time"),
            "horse_no": p.get("horse_no"),
            "horse_name": p.get("horse_name"),
            "agf": p.get("agf"),
            "mp": p.get("mp"),
            "mult": p.get("mult"),
            "field_size": p.get("field_size"),
            "jockey_name": p.get("jockey_name"),
            "outcome": {
                "status": "graded" if res else "pending",
                "won": (res.get("won") if res else None),
                "winner_horse_no": (res.get("winner_horse_no")
                                    if res else None),
                "in_top4": (res.get("in_top4") if res else None),
            },
        })
    # Sort SiB rows by tier priority then time
    _tier_pri = {"DIAMOND": 0, "ALTIN": 1, "PREMIUM": 2, "FIRSAT": 3}
    sib_rows.sort(key=lambda r: (
        _tier_pri.get((r.get("tier") or "").upper(), 9),
        str(r.get("race_time") or ""),
    ))

    # Daily summary (shadow)
    shadow_summary = _load_json(_shadow_sum_path(date_str)) or {}
    sib_summary = sib_log.load_summary(date_str) or {}

    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "shadow": {
            "rows": shadow_rows,
            "count": len(shadow_rows),
            "summary": shadow_summary,
        },
        "sib": {
            "rows": sib_rows,
            "count": len(sib_rows),
            "summary": sib_summary,
        },
        "disclaimer": (
            "Deneme / shadow kuponudur. Resmi bot kuponu değildir. "
            "Otomatik bahis değildir."
        ),
    }


def build_history_view(days: int = 14) -> dict:
    """Last N days of summary stats. Used by the history table."""
    days = max(1, min(int(days or 14), 60))
    today = datetime.now(timezone.utc).date()
    rows: list[dict] = []
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        sh = _load_json(_shadow_sum_path(d)) or {}
        si = sib_log.load_summary(d) or {}
        if not sh and not si:
            continue
        rows.append({
            "date": d,
            "shadow": {
                "predictions": sh.get("predictions", 0),
                "results": sh.get("results", 0),
                "banker_survived": sh.get("banker_survived_count", 0),
                "candidate_hit": sh.get("candidate_set_full_top4_capture", 0),
                "small_hit": sh.get("small_ticket_hit_count", 0),
                "balanced_hit": sh.get("balanced_ticket_hit_count", 0),
                "wide_hit": sh.get("wide_ticket_hit_count", 0),
                "no_bet": sh.get("no_bet_count", 0),
            },
            "sib": {
                "picks": si.get("picks_total", 0),
                "results": si.get("results_total", 0),
                "win_rate_by_tier": si.get("win_rate_by_tier") or {},
                "by_tier_total": si.get("by_tier_total") or {},
                "by_tier_won": si.get("by_tier_won") or {},
            },
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "days_requested": days,
        "days_present": len(rows),
        "rows": rows,
    }
