"""Dashboard view-model builder for BERKAY DENEME.

Aggregates shadow coupons + SİB picks + retro state into a single
JSON-safe payload that the HTML page can render. Pure read; no
side effects. NEVER raises.

Exports:
  - build_today_view(date_str=None) -> dict
  - build_history_view(days=14) -> dict
  - refresh_sib_today(date_str=None) -> dict
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import sib_log
from .experimental_logger import (
    read_predictions, read_results, _summary_path_for as _shadow_sum_path,
)

logger = logging.getLogger(__name__)

# Cache for "live" SiB fetch — picks are expensive (~30s).
_SIB_LIVE_CACHE: dict = {}  # date_str -> (timestamp, payload)
_SIB_CACHE_TTL = 600  # 10 minutes
_SIB_CACHE_LOCK = threading.Lock()


def refresh_sib_today(date_str: Optional[str] = None,
                      force: bool = False) -> dict:
    """Live-fetch today's SiB picks (DIAMOND/ALTIN/PREMIUM/FIRSAT) and
    persist them via sib_log. Useful when scheduler hasn't run yet
    today or when env was added after morning emit (picks lost).

    Cached for 10 minutes per date. Returns counts + status.

    NEVER raises.
    """
    date_str = date_str or _today_str()
    try:
        with _SIB_CACHE_LOCK:
            cached = _SIB_LIVE_CACHE.get(date_str)
        if cached and not force and (time.time() - cached[0]) < _SIB_CACHE_TTL:
            return {
                "status": "cached", "date": date_str,
                "totals": cached[1].get("totals") or {},
            }
        # Live fetch from sib_top4_service. This is the SAME source the
        # morning scheduler uses; we just call it on-demand.
        try:
            from datetime import date as _date
            try:
                target = _date.fromisoformat(date_str)
            except ValueError:
                target = _date.today()
            try:
                from dashboard.sib_top4_service import collect_today_picks
            except ImportError:
                from sib_top4_service import collect_today_picks  # type: ignore
            payload = collect_today_picks(target)
            if not payload:
                return {"status": "empty", "date": date_str, "totals": {}}
            # Persist to log (idempotent).
            try:
                sib_log.log_sib_picks(payload, telegram_sent=False, force=True)
            except Exception as exc:
                logger.warning("refresh_sib_today log: %s", exc)
            with _SIB_CACHE_LOCK:
                _SIB_LIVE_CACHE[date_str] = (time.time(), payload)
            return {
                "status": "fresh",
                "date": date_str,
                "totals": payload.get("totals") or {},
                "diamond": len(payload.get("diamond") or []),
                "altin": len(payload.get("altin") or []),
                "premium": len(payload.get("premium") or []),
                "firsat": len(payload.get("firsat") or []),
            }
        except Exception as exc:
            logger.warning("refresh_sib_today fetch: %s", exc)
            return {"status": "error", "date": date_str,
                    "reason": repr(exc)[:200]}
    except Exception as exc:
        return {"status": "error", "date": date_str,
                "reason": repr(exc)[:200]}


def telegram_messages_for_today() -> list[dict]:
    """Return the Telegram message dump for today (from yerli kupon
    cache + smart_coupon all). Each entry: {category, title, text}.

    'Berkay's Telegram'da ne varsa is te' request: dashboard shows
    everything that gets sent to Telegram so detail-seekers don't
    need to scroll Telegram.
    """
    out: list[dict] = []
    # 1) V5.1 yerli kupon mesajları (cache'ten)
    try:
        try:
            from dashboard.app import _yerli_cache, _yerli_lock
        except Exception:
            return out
        with _yerli_lock:
            data = (_yerli_cache.get("data") or {}) if _yerli_cache else {}
        if data:
            for hp in (data.get("hippodromes") or []):
                # Each hippodrome has its own Telegram message under
                # 'telegram_msg' or similar key. The smart_coupon
                # service stores it as 'text'. We fall back gracefully.
                txt = (hp.get("telegram_msg") or hp.get("text")
                       or hp.get("kupon_text") or "")
                if not txt:
                    continue
                out.append({
                    "category": "V5.1 KUPON",
                    "title": (hp.get("hippodrome") or "?")
                             + (" · " + str(hp.get("altili_no")) + ". altılı"
                                if hp.get("altili_no") else ""),
                    "text": txt,
                })
            # Top-level daily digest if present
            if data.get("telegram_msg"):
                out.append({
                    "category": "GÜNLÜK",
                    "title": "Günlük TJK özeti",
                    "text": data["telegram_msg"],
                })
    except Exception as exc:
        logger.debug("telegram messages: %s", exc)
    return out


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

    # Live SiB fallback: if today's picks are empty AND we're looking
    # at "today", try fetching them on-demand (cached). This solves
    # the case where the morning scheduler ran BEFORE the forward-log
    # env var was set, so picks were sent to Telegram but never logged.
    if not sib_picks and date_str == _today_str():
        try:
            stat = refresh_sib_today(date_str)
            if stat.get("status") in ("fresh", "cached"):
                sib_picks = sib_log.read_picks(date_str)
        except Exception as exc:
            logger.debug("live sib fallback: %s", exc)
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

    # Telegram messages dump (for today only — uses live cache)
    tg_msgs: list[dict] = []
    if date_str == _today_str():
        try:
            tg_msgs = telegram_messages_for_today()
        except Exception as exc:
            logger.debug("telegram messages: %s", exc)

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
        "telegram_messages": tg_msgs,
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
