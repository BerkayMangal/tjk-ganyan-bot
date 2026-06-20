"""Forward / retro logger for the BERKAY BİLİMSEL DENEME TOP4 layer.

Hardened version:

  - Every prediction row carries a stable `prediction_id` derived from
    (label, race_id, cutoff, generated_at[:minute], model_version,
    agf_snapshot_time). See `top4/prediction_id.py`.
  - Idempotent JSONL writes: existing prediction_ids are not re-written.
  - `telegram_sent`, `telegram_send_error`, `engine_status` are recorded.
  - Optional DB fan-out via `TJK_TOP4_RETRO_STORE=jsonl|db|both`
    (default `jsonl`). DB uses the existing `event_store`
    (`pipeline_events` table); no migration required.
  - When DB write fails after a successful Telegram send, a single
    visible WARNING is emitted to Railway logs — silent divergence is
    not allowed.
  - `record_results_for_date` is idempotent: a result row keyed by
    `prediction_id` is written once per prediction.

Daily summary path:
  `data/forward_logs/berkay_scientific_top4/YYYY-MM-DD.summary.json`
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from .experimental_coupon import EXPERIMENTAL_LABEL, is_forward_log_enabled
from .prediction_id import LABEL, make_prediction_id_for_coupon

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "forward_logs", "berkay_scientific_top4")

# Storage mode env: jsonl | db | both. Default jsonl for safety.
ENV_RETRO_STORE = "TJK_TOP4_RETRO_STORE"

_WRITE_LOCK = threading.Lock()
_SEEN_IDS_BY_DATE: dict[str, set[str]] = {}


def retro_store_mode() -> str:
    val = (os.environ.get(ENV_RETRO_STORE) or "jsonl").strip().lower()
    if val not in {"jsonl", "db", "both"}:
        return "jsonl"
    return val


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _path_for(date_str: Optional[str] = None) -> str:
    date_str = date_str or _today_str()
    return os.path.join(LOG_DIR, f"{date_str}.jsonl")


def _summary_path_for(date_str: Optional[str] = None) -> str:
    date_str = date_str or _today_str()
    return os.path.join(LOG_DIR, f"{date_str}.summary.json")


def _load_seen_ids(date_str: str) -> set[str]:
    if date_str in _SEEN_IDS_BY_DATE:
        return _SEEN_IDS_BY_DATE[date_str]
    seen: set[str] = set()
    path = _path_for(date_str)
    if os.path.exists(path):
        try:
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("event_type") == "prediction":
                        pid = row.get("prediction_id")
                        if pid:
                            seen.add(pid)
        except OSError:
            pass
    _SEEN_IDS_BY_DATE[date_str] = seen
    return seen


def _reset_seen_cache_for_test():
    """Test helper — clear in-memory dedupe cache."""
    _SEEN_IDS_BY_DATE.clear()


def build_prediction_row(
    coupon: Mapping,
    *,
    telegram_sent: Optional[bool] = None,
    telegram_send_error: Optional[str] = None,
    telegram_message_id: Optional[str] = None,
) -> dict:
    """Construct the canonical prediction row from a coupon dict.
    Adds `prediction_id`, send-status fields, and a `label`.

    The returned dict is JSON-safe. Caller decides whether to write it.
    """
    prediction_id = make_prediction_id_for_coupon(coupon)
    return {
        "event_type": "prediction",
        "label": EXPERIMENTAL_LABEL,
        "prediction_id": prediction_id,
        "generated_at": coupon.get("generated_at"),
        "race_id": coupon.get("race_id"),
        "race_label": coupon.get("race_label"),
        "race_time": coupon.get("race_time"),
        "hippodrome": coupon.get("hippodrome"),
        "field_size": coupon.get("field_size"),
        "prediction_cutoff": coupon.get("prediction_cutoff"),
        "model_version": coupon.get("model_version"),
        "feature_snapshot_hash": coupon.get("feature_snapshot_hash"),
        "agf_snapshot_time": coupon.get("agf_snapshot_time"),
        "horses": coupon.get("horses", []),
        "bankers": [h["horse_no"] for h in coupon.get("bankers", [])],
        "core": [h["horse_no"] for h in coupon.get("core", [])],
        "spread": [h["horse_no"] for h in coupon.get("spread", [])],
        "chaos": [h["horse_no"] for h in coupon.get("chaos", [])],
        "avoid": [h["horse_no"] for h in coupon.get("avoid", [])],
        "candidate_set": coupon.get("candidate_set", []),
        "small_ticket": coupon.get("small_ticket"),
        "balanced_ticket": coupon.get("balanced_ticket"),
        "wide_ticket": coupon.get("wide_ticket"),
        "confidence": coupon.get("confidence"),
        "variance": coupon.get("variance"),
        "recommended_mode": coupon.get("recommended_mode"),
        "no_bet_reason": coupon.get("no_bet_reason"),
        "engine_status": coupon.get("engine_status"),
        "telegram_sent": telegram_sent,
        "telegram_send_error": telegram_send_error,
        "telegram_message_id": telegram_message_id,
        "retro_store_mode": retro_store_mode(),
    }


def log_prediction(
    coupon: Mapping,
    *,
    telegram_sent: Optional[bool] = None,
    telegram_send_error: Optional[str] = None,
    telegram_message_id: Optional[str] = None,
    force: bool = False,
) -> Optional[str]:
    """Idempotent prediction log writer.

    Returns the JSONL path on success (or "db_only" when only DB write
    happened), or None when disabled / failed.

    Behavior matrix (TJK_TOP4_FORWARD_LOG, TJK_TOP4_RETRO_STORE):
      LOG=0 & not force          -> no-op
      LOG=1 & STORE=jsonl        -> JSONL only
      LOG=1 & STORE=db           -> DB only
      LOG=1 & STORE=both         -> JSONL + DB
      DB unavailable             -> WARN once, JSONL still written if mode allows
    """
    if not force and not is_forward_log_enabled():
        return None

    row = build_prediction_row(
        coupon,
        telegram_sent=telegram_sent,
        telegram_send_error=telegram_send_error,
        telegram_message_id=telegram_message_id,
    )
    pid = row["prediction_id"]
    date_str = _today_str()
    mode = retro_store_mode()

    jsonl_written = False
    jsonl_dedupe = False
    if mode in {"jsonl", "both"}:
        try:
            os.makedirs(LOG_DIR, exist_ok=True)
            seen = _load_seen_ids(date_str)
            if pid in seen:
                logger.debug("log_prediction skip dupe %s", pid)
                jsonl_dedupe = True
            else:
                path = _path_for(date_str)
                with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
                    fh.write(json.dumps(row, default=str,
                                        ensure_ascii=False) + "\n")
                seen.add(pid)
                jsonl_written = True
        except Exception as exc:
            logger.warning(
                "log_prediction JSONL write failed (pid=%s, telegram_sent=%s): %s",
                pid, telegram_sent, exc,
            )

    db_written = False
    if mode in {"db", "both"}:
        try:
            from .db_store import write_prediction, is_db_enabled
            if is_db_enabled():
                db_written = write_prediction(row)
                if not db_written and telegram_sent:
                    logger.warning(
                        "log_prediction: Telegram SENT but DB write FAILED "
                        "(pid=%s). Retro analysis may be incomplete.",
                        pid,
                    )
            elif mode == "db":
                logger.warning(
                    "TJK_TOP4_RETRO_STORE=db but no DB URL set; "
                    "TJK_MEASURE_DB_URL is required. Prediction NOT durably "
                    "logged (pid=%s, telegram_sent=%s)",
                    pid, telegram_sent,
                )
        except Exception as exc:
            logger.warning(
                "log_prediction DB path failed (pid=%s): %s",
                pid, exc,
            )

    if not jsonl_written and not db_written:
        if jsonl_dedupe:
            # legitimate idempotent skip — no warning
            return _path_for(date_str)
        if telegram_sent:
            logger.warning(
                "log_prediction: Telegram SENT but NEITHER JSONL NOR DB "
                "captured this prediction (pid=%s). Retro analysis will "
                "miss this row.", pid,
            )
        return None
    return _path_for(date_str) if jsonl_written else "db_only"


def _horses_from_ticket(ticket: Optional[Mapping]) -> list[int]:
    if not ticket or ticket.get("skip"):
        return []
    out = []
    for k in ("banker", "core", "spread", "chaos"):
        out.extend(ticket.get(k) or [])
    return out


def _read_jsonl(date_str: Optional[str] = None) -> list[dict]:
    path = _path_for(date_str)
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                out.append(json.loads(line))
            except ValueError:
                continue
    return out


def read_predictions(date_str: Optional[str] = None) -> list[dict]:
    """Read prediction rows from JSONL + (if mode allows) DB. Deduped by
    prediction_id (latest occurrence wins per source). Public helper for
    audit / report scripts."""
    date_str = date_str or _today_str()
    rows = [r for r in _read_jsonl(date_str)
            if r.get("event_type") == "prediction"]
    mode = retro_store_mode()
    if mode in {"db", "both"}:
        try:
            from .db_store import read_predictions_for_date, dedupe_predictions
            db_rows = read_predictions_for_date(date_str)
            rows = dedupe_predictions(rows + db_rows)
        except Exception:
            pass
    else:
        # dedupe locally too
        seen: dict[str, dict] = {}
        for r in rows:
            pid = r.get("prediction_id")
            if pid:
                seen[pid] = r
            else:
                seen[id(r)] = r  # type: ignore[index]
        rows = list(seen.values())
    return rows


def read_results(date_str: Optional[str] = None) -> list[dict]:
    date_str = date_str or _today_str()
    rows = [r for r in _read_jsonl(date_str)
            if r.get("event_type") == "result"]
    mode = retro_store_mode()
    if mode in {"db", "both"}:
        try:
            from .db_store import read_results_for_date
            rows = rows + read_results_for_date(date_str)
        except Exception:
            pass
    # dedupe by (prediction_id or race_id)
    seen: dict[str, dict] = {}
    for r in rows:
        key = r.get("prediction_id") or r.get("race_id") or str(id(r))
        seen[key] = r
    return list(seen.values())


def log_result(
    *,
    race_id: str,
    race_label: Optional[str] = None,
    prediction_id: Optional[str] = None,
    finish_order: Iterable[int],
    payouts: Optional[Mapping] = None,
    notes: Optional[list[str]] = None,
    force: bool = False,
) -> Optional[str]:
    """Write a result row keyed by prediction_id (or race_id fallback).
    Idempotent: existing matching result row is not duplicated.

    If `prediction_id` is not supplied, the function attempts to find
    the most recent prediction for `race_id` and use ITS id.
    """
    if not force and not is_forward_log_enabled():
        return None
    try:
        finish_list = [int(x) for x in finish_order]
        top4 = finish_list[:4]
        date_str = _today_str()
        existing_results = read_results(date_str)
        if not prediction_id:
            # find a matching prediction by race_id
            preds = read_predictions(date_str)
            matching = [p for p in preds if p.get("race_id") == race_id]
            if matching:
                prediction_id = matching[-1].get("prediction_id")
        # dedupe: already have a result for this prediction_id?
        if prediction_id and any(
            r.get("prediction_id") == prediction_id for r in existing_results
        ):
            logger.debug("log_result skip dupe pid=%s", prediction_id)
            # still rebuild summary
            rebuild_summary(date_str)
            return _path_for(date_str)

        latest_pred = {}
        if prediction_id:
            preds = read_predictions(date_str)
            latest_pred = next(
                (p for p in preds if p.get("prediction_id") == prediction_id),
                {},
            )
        elif race_id:
            preds = read_predictions(date_str)
            matching = [p for p in preds if p.get("race_id") == race_id]
            if matching:
                latest_pred = matching[-1]

        bankers = set(latest_pred.get("bankers") or [])
        candidate = set(latest_pred.get("candidate_set") or [])
        small_h = set(_horses_from_ticket(latest_pred.get("small_ticket")))
        balanced_h = set(_horses_from_ticket(latest_pred.get("balanced_ticket")))
        wide_h = set(_horses_from_ticket(latest_pred.get("wide_ticket")))
        top4_set = set(top4)
        result_row = {
            "event_type": "result",
            "label": EXPERIMENTAL_LABEL,
            "prediction_id": prediction_id,
            "race_id": race_id,
            "race_label": race_label,
            "finalized_at": datetime.now(timezone.utc).isoformat(),
            "finish_order": finish_list,
            "top4_actual": top4,
            "banker_survived": bool(bankers and bankers.issubset(top4_set)),
            "candidate_set_captured_top4":
                bool(candidate) and top4_set.issubset(candidate),
            "small_ticket_hit": bool(small_h) and top4_set.issubset(small_h),
            "balanced_ticket_hit":
                bool(balanced_h) and top4_set.issubset(balanced_h),
            "wide_ticket_hit": bool(wide_h) and top4_set.issubset(wide_h),
            "payouts_if_available": dict(payouts or {}),
            "notes": list(notes or []),
        }
        mode = retro_store_mode()
        if mode in {"jsonl", "both"}:
            os.makedirs(LOG_DIR, exist_ok=True)
            with _WRITE_LOCK, open(_path_for(date_str), "a",
                                   encoding="utf-8") as fh:
                fh.write(json.dumps(result_row, default=str,
                                    ensure_ascii=False) + "\n")
        if mode in {"db", "both"}:
            try:
                from .db_store import write_result
                write_result(result_row)
            except Exception as exc:
                logger.warning("log_result DB path failed: %s", exc)
        rebuild_summary(date_str)
        return _path_for(date_str)
    except Exception as exc:
        logger.warning("log_result failed: %s", exc)
        return None


def rebuild_summary(date_str: Optional[str] = None) -> Optional[str]:
    """Aggregate the day's JSONL+DB into a summary file."""
    try:
        date_str = date_str or _today_str()
        preds = read_predictions(date_str)
        results = read_results(date_str)
        if not preds and not results:
            return None
        os.makedirs(LOG_DIR, exist_ok=True)

        latest_by_pid: dict[str, dict] = {}
        for p in preds:
            pid = p.get("prediction_id") or p.get("race_id")
            if pid:
                latest_by_pid[pid] = p
        result_by_key: dict[str, dict] = {}
        for r in results:
            key = r.get("prediction_id") or r.get("race_id") or ""
            if key:
                result_by_key[key] = r

        n_pred = len(latest_by_pid)
        n_res = len(result_by_key)
        confidence_counter: Counter = Counter()
        mode_counter: Counter = Counter()
        no_bet = 0
        engine_fallback = 0
        engine_error = 0
        hippo_counter: Counter = Counter()
        field_buckets: Counter = Counter()
        telegram_sent_count = 0
        telegram_failed_count = 0
        telegram_unknown_count = 0

        banker_survived = 0
        candidate_hit = 0
        small_hit = 0
        balanced_hit = 0
        wide_hit = 0
        agf_drift_signal_correct = 0
        agf_drift_signal_total = 0
        missing_payout = 0

        for pid, pred in latest_by_pid.items():
            confidence_counter[pred.get("confidence") or "?"] += 1
            mode_counter[pred.get("recommended_mode") or "?"] += 1
            if pred.get("recommended_mode") == "NO_BET":
                no_bet += 1
            if pred.get("engine_status") == "fallback":
                engine_fallback += 1
            elif pred.get("engine_status") == "error":
                engine_error += 1
            hippo_counter[pred.get("hippodrome") or "?"] += 1
            fs = pred.get("field_size") or 0
            if fs <= 8:
                field_buckets["small_<=8"] += 1
            elif fs <= 12:
                field_buckets["mid_9_12"] += 1
            elif fs <= 15:
                field_buckets["large_13_15"] += 1
            else:
                field_buckets["xlarge_16+"] += 1
            ts = pred.get("telegram_sent")
            if ts is True:
                telegram_sent_count += 1
            elif ts is False:
                telegram_failed_count += 1
            else:
                telegram_unknown_count += 1

            res = result_by_key.get(pid) or result_by_key.get(pred.get("race_id"))
            if res:
                if res.get("banker_survived"):
                    banker_survived += 1
                if res.get("candidate_set_captured_top4"):
                    candidate_hit += 1
                if res.get("small_ticket_hit"):
                    small_hit += 1
                if res.get("balanced_ticket_hit"):
                    balanced_hit += 1
                if res.get("wide_ticket_hit"):
                    wide_hit += 1
                if not (res.get("payouts_if_available") or {}):
                    missing_payout += 1
                horses_pred = pred.get("horses") or []
                top4 = set(res.get("top4_actual") or [])
                for h in horses_pred:
                    rel = h.get("agf_drift_rel")
                    if rel is None:
                        continue
                    if abs(rel) >= 0.20:
                        agf_drift_signal_total += 1
                        if (rel > 0 and h.get("horse_no") in top4):
                            agf_drift_signal_correct += 1

        summary = {
            "date": date_str,
            "label": EXPERIMENTAL_LABEL,
            "retro_store_mode": retro_store_mode(),
            "predictions": n_pred,
            "telegram_sent_count": telegram_sent_count,
            "telegram_failed_count": telegram_failed_count,
            "telegram_unknown_count": telegram_unknown_count,
            "results": n_res,
            "missing_results_count": max(0, n_pred - n_res),
            "missing_payout_count": missing_payout,
            "no_bet_count": no_bet,
            "engine_fallback_count": engine_fallback,
            "engine_error_count": engine_error,
            "confidence_distribution": dict(confidence_counter),
            "mode_distribution": dict(mode_counter),
            "by_hippodrome": dict(hippo_counter),
            "by_field_size_bucket": dict(field_buckets),
            "banker_survived_count": banker_survived,
            "candidate_set_full_top4_capture": candidate_hit,
            "small_ticket_hit_count": small_hit,
            "balanced_ticket_hit_count": balanced_hit,
            "wide_ticket_hit_count": wide_hit,
            "agf_drift_signal_total": agf_drift_signal_total,
            "agf_drift_signal_correct": agf_drift_signal_correct,
            "agf_drift_signal_hit_rate": (
                (agf_drift_signal_correct / agf_drift_signal_total)
                if agf_drift_signal_total else None
            ),
            "notes": [
                "payout fields recorded only when available.",
                "ticket_hit means full top4 set ⊆ ticket horse list.",
                "banker_survived means all BANKER horses appeared in actual top4.",
                "telegram_unknown_count = predictions logged without send-status hint (back-compat).",
            ],
        }
        sp = _summary_path_for(date_str)
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        return sp
    except Exception:
        return None
