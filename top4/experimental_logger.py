"""Forward / retro logger for the BERKAY BİLİMSEL DENEME TOP4 layer.

Writes append-only JSONL rows under
`data/forward_logs/berkay_scientific_top4/YYYY-MM-DD.jsonl` and a
companion `YYYY-MM-DD.summary.json`. Never raises.

Two event types are written to the same daily JSONL:
  - `event_type="prediction"` — produced when the coupon is generated.
  - `event_type="result"` — produced post-race when finish order is
    known (called from retro/recap path).

The daily summary aggregates banker / core / spread survival, no-bet
counts, ticket-mode hit counts, AGF drift signal performance, and
segment slices.
"""
from __future__ import annotations

import json
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

from .experimental_coupon import EXPERIMENTAL_LABEL, is_forward_log_enabled

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "forward_logs", "berkay_scientific_top4")

_WRITE_LOCK = threading.Lock()


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _path_for(date_str: Optional[str] = None) -> str:
    date_str = date_str or _today_str()
    return os.path.join(LOG_DIR, f"{date_str}.jsonl")


def _summary_path_for(date_str: Optional[str] = None) -> str:
    date_str = date_str or _today_str()
    return os.path.join(LOG_DIR, f"{date_str}.summary.json")


def log_prediction(coupon: Mapping, *, force: bool = False) -> Optional[str]:
    """Write one prediction row. Returns the file path written, or None.

    If `TJK_TOP4_FORWARD_LOG != 1` and `force=False`, no write occurs.
    """
    if not force and not is_forward_log_enabled():
        return None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        rec = {
            "event_type": "prediction",
            "label": EXPERIMENTAL_LABEL,
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
        }
        path = _path_for()
        with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(rec, default=str, ensure_ascii=False) + "\n")
        return path
    except Exception:
        return None


def log_result(
    *,
    race_id: str,
    race_label: Optional[str] = None,
    finish_order: Iterable[int],
    payouts: Optional[Mapping] = None,
    notes: Optional[list[str]] = None,
    force: bool = False,
) -> Optional[str]:
    """Write a result row, then update the daily summary."""
    if not force and not is_forward_log_enabled():
        return None
    try:
        finish_list = [int(x) for x in finish_order]
        top4 = finish_list[:4]
        os.makedirs(LOG_DIR, exist_ok=True)
        # find matching prediction(s) for this race in today's file
        path = _path_for()
        predictions: list[dict] = []
        if os.path.exists(path):
            with open(path, encoding="utf-8") as fh:
                for line in fh:
                    try:
                        row = json.loads(line)
                    except ValueError:
                        continue
                    if row.get("event_type") == "prediction" and \
                       row.get("race_id") == race_id:
                        predictions.append(row)
        latest_pred = predictions[-1] if predictions else {}
        bankers = set(latest_pred.get("bankers") or [])
        candidate = set(latest_pred.get("candidate_set") or [])
        small_h = set(_horses_from_ticket(latest_pred.get("small_ticket")))
        balanced_h = set(_horses_from_ticket(latest_pred.get("balanced_ticket")))
        wide_h = set(_horses_from_ticket(latest_pred.get("wide_ticket")))
        top4_set = set(top4)
        result_row = {
            "event_type": "result",
            "label": EXPERIMENTAL_LABEL,
            "race_id": race_id,
            "race_label": race_label,
            "finalized_at": datetime.now(timezone.utc).isoformat(),
            "finish_order": finish_list,
            "top4_actual": top4,
            "banker_survived": bool(bankers and bankers.issubset(top4_set)),
            "candidate_set_captured_top4":
                bool(candidate) and top4_set.issubset(candidate),
            "small_ticket_hit": bool(small_h) and top4_set.issubset(small_h),
            "balanced_ticket_hit": bool(balanced_h) and top4_set.issubset(balanced_h),
            "wide_ticket_hit": bool(wide_h) and top4_set.issubset(wide_h),
            "payouts_if_available": dict(payouts or {}),
            "notes": list(notes or []),
        }
        with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(result_row, default=str, ensure_ascii=False) + "\n")
        # update summary
        rebuild_summary()
        return path
    except Exception:
        return None


def _horses_from_ticket(ticket: Optional[Mapping]) -> list[int]:
    if not ticket or ticket.get("skip"):
        return []
    out = []
    for k in ("banker", "core", "spread", "chaos"):
        out.extend(ticket.get(k) or [])
    return out


def rebuild_summary(date_str: Optional[str] = None) -> Optional[str]:
    """Aggregate the daily JSONL into a summary file. Returns path or None."""
    try:
        date_str = date_str or _today_str()
        path = _path_for(date_str)
        if not os.path.exists(path):
            return None
        preds: list[dict] = []
        results: list[dict] = []
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                t = row.get("event_type")
                if t == "prediction":
                    preds.append(row)
                elif t == "result":
                    results.append(row)

        # latest prediction per race
        latest_by_race: dict[str, dict] = {}
        for p in preds:
            latest_by_race[p.get("race_id") or ""] = p
        result_by_race: dict[str, dict] = {
            r.get("race_id") or "": r for r in results
        }

        n_pred = len(latest_by_race)
        n_res = len(result_by_race)
        confidence_counter: Counter = Counter()
        mode_counter: Counter = Counter()
        no_bet = 0
        engine_fallback = 0
        engine_error = 0
        hippodrome_counter: Counter = Counter()
        field_buckets: Counter = Counter()

        banker_survived = 0
        candidate_hit = 0
        small_hit = 0
        balanced_hit = 0
        wide_hit = 0
        agf_drift_signal_correct = 0
        agf_drift_signal_total = 0

        for race_id, pred in latest_by_race.items():
            confidence_counter[pred.get("confidence") or "?"] += 1
            mode_counter[pred.get("recommended_mode") or "?"] += 1
            if pred.get("recommended_mode") == "NO_BET":
                no_bet += 1
            if pred.get("engine_status") == "fallback":
                engine_fallback += 1
            elif pred.get("engine_status") == "error":
                engine_error += 1
            hippodrome_counter[pred.get("hippodrome") or "?"] += 1
            fs = pred.get("field_size") or 0
            if fs <= 8:
                field_buckets["small_<=8"] += 1
            elif fs <= 12:
                field_buckets["mid_9_12"] += 1
            elif fs <= 15:
                field_buckets["large_13_15"] += 1
            else:
                field_buckets["xlarge_16+"] += 1

            res = result_by_race.get(race_id)
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
                # AGF drift signal performance: did a horse whose AGF was
                # rising land in the top-4?
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
            "predictions": n_pred,
            "results": n_res,
            "no_bet_count": no_bet,
            "engine_fallback_count": engine_fallback,
            "engine_error_count": engine_error,
            "confidence_distribution": dict(confidence_counter),
            "mode_distribution": dict(mode_counter),
            "by_hippodrome": dict(hippodrome_counter),
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
            ],
        }
        sp = _summary_path_for(date_str)
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        return sp
    except Exception:
        return None


def read_predictions(date_str: Optional[str] = None) -> list[dict]:
    """Helper for tests / audit."""
    path = _path_for(date_str)
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event_type") == "prediction":
                out.append(row)
    return out
