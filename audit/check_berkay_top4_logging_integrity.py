"""BERKAY BİLİMSEL DENEME TOP4 — logging integrity audit.

Verifies that every shadow coupon that was generated/sent has a
durable, retrievable log row. Reports missing rows, duplicate ids,
and races without a result yet.

Usage:
  python3 audit/check_berkay_top4_logging_integrity.py [YYYY-MM-DD]

Writes a report to:
  audit/reports/berkay_top4_logging_integrity_YYYY-MM-DD.md
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from top4.experimental_logger import (  # noqa: E402
    LOG_DIR, _path_for, _summary_path_for,
    read_predictions, read_results, retro_store_mode, rebuild_summary,
)


def _today() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _jsonl_prediction_count(date_str: str) -> int:
    p = _path_for(date_str)
    if not os.path.exists(p):
        return 0
    n = 0
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            try:
                if json.loads(line).get("event_type") == "prediction":
                    n += 1
            except ValueError:
                continue
    return n


def _jsonl_telegram_sent_counts(date_str: str) -> Counter:
    c: Counter = Counter()
    p = _path_for(date_str)
    if not os.path.exists(p):
        return c
    with open(p, encoding="utf-8") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("event_type") != "prediction":
                continue
            ts = row.get("telegram_sent")
            key = "true" if ts is True else ("false" if ts is False else "null")
            c[key] += 1
    return c


def _db_status() -> dict:
    out = {"available": False, "url_set": False, "reason": "", "n_pred": 0,
           "n_res": 0}
    try:
        from top4.db_store import (
            is_db_enabled, read_predictions_for_date, read_results_for_date,
        )
        out["url_set"] = is_db_enabled()
        if not out["url_set"]:
            out["reason"] = "TJK_MEASURE_DB_URL not set"
            return out
        out["available"] = True
        date_str = _today()
        out["n_pred"] = len(read_predictions_for_date(date_str))
        out["n_res"] = len(read_results_for_date(date_str))
    except Exception as exc:
        out["reason"] = f"DB layer error: {repr(exc)[:160]}"
    return out


def run_audit(date_str: str) -> dict:
    preds = read_predictions(date_str)
    results = read_results(date_str)
    jsonl_count = _jsonl_prediction_count(date_str)
    ts_counts = _jsonl_telegram_sent_counts(date_str)
    db = _db_status()

    pid_counter: Counter = Counter()
    for p in preds:
        pid = p.get("prediction_id")
        if pid:
            pid_counter[pid] += 1
    duplicate_pids = [pid for pid, c in pid_counter.items() if c > 1]

    res_pids = {r.get("prediction_id") for r in results if r.get("prediction_id")}
    missing_results = [
        p.get("prediction_id") for p in preds
        if p.get("prediction_id")
        and p.get("prediction_id") not in res_pids
    ]

    cutoff_counter: Counter = Counter()
    hippo_counter: Counter = Counter()
    mode_counter: Counter = Counter()
    confidence_counter: Counter = Counter()
    engine_status_counter: Counter = Counter()
    for p in preds:
        cutoff_counter[p.get("prediction_cutoff") or "?"] += 1
        hippo_counter[p.get("hippodrome") or "?"] += 1
        mode_counter[p.get("recommended_mode") or "?"] += 1
        confidence_counter[p.get("confidence") or "?"] += 1
        engine_status_counter[p.get("engine_status") or "?"] += 1

    return {
        "date": date_str,
        "retro_store_mode": retro_store_mode(),
        "jsonl": {
            "path": _path_for(date_str),
            "predictions": jsonl_count,
            "telegram_sent_counts": dict(ts_counts),
            "summary_path": _summary_path_for(date_str),
            "summary_exists": os.path.exists(_summary_path_for(date_str)),
        },
        "db": db,
        "merged": {
            "predictions": len(preds),
            "results": len(results),
            "duplicate_prediction_ids": duplicate_pids,
            "duplicate_count": len(duplicate_pids),
            "missing_result_prediction_ids": missing_results,
            "missing_result_count": len(missing_results),
        },
        "distributions": {
            "cutoff": dict(cutoff_counter),
            "hippodrome": dict(hippo_counter),
            "recommended_mode": dict(mode_counter),
            "confidence": dict(confidence_counter),
            "engine_status": dict(engine_status_counter),
        },
    }


def write_report(audit: dict) -> str:
    date_str = audit["date"]
    report_path = REPO / "audit" / "reports" / f"berkay_top4_logging_integrity_{date_str}.md"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    lines: list[str] = []
    lines.append("# BERKAY BİLİMSEL DENEME TOP4 — Logging Integrity Audit")
    lines.append(f"_Date: {date_str}_")
    lines.append("")
    lines.append(f"- retro_store_mode: **{audit['retro_store_mode']}**")
    lines.append("")
    lines.append("## JSONL")
    j = audit["jsonl"]
    lines.append(f"- path: `{j['path']}`")
    lines.append(f"- predictions: **{j['predictions']}**")
    lines.append(f"- telegram_sent counts: `{j['telegram_sent_counts']}`")
    lines.append(f"- summary present: {j['summary_exists']} (`{j['summary_path']}`)")
    lines.append("")
    lines.append("## DB")
    d = audit["db"]
    lines.append(f"- available: **{d['available']}**, url_set: {d['url_set']}")
    if d.get("reason"):
        lines.append(f"- reason: `{d['reason']}`")
    lines.append(f"- predictions: {d['n_pred']}, results: {d['n_res']}")
    lines.append("")
    lines.append("## Merged (JSONL + DB, deduped by prediction_id)")
    m = audit["merged"]
    lines.append(f"- predictions: **{m['predictions']}**")
    lines.append(f"- results: **{m['results']}**")
    lines.append(f"- duplicate prediction_ids: {m['duplicate_count']}")
    if m["duplicate_prediction_ids"]:
        lines.append("  - " + ", ".join(m["duplicate_prediction_ids"][:10]))
    lines.append(f"- predictions without a result row yet: {m['missing_result_count']}")
    lines.append("")
    lines.append("## Distributions")
    for k, v in audit["distributions"].items():
        lines.append(f"- **{k}**: `{v}`")
    lines.append("")
    lines.append("## Integrity verdict")
    issues: list[str] = []
    if m["duplicate_count"] > 0:
        issues.append(f"duplicate prediction_ids: {m['duplicate_count']}")
    if (audit["retro_store_mode"] in {"db", "both"}
            and not d["available"]):
        issues.append("DB mode requested but DB unavailable")
    js = j["telegram_sent_counts"]
    if js.get("null", 0) > 0 and audit["retro_store_mode"] in {"jsonl", "both"}:
        issues.append(f"{js['null']} prediction rows have telegram_sent=null "
                      "(legacy or scheduler skipped status threading)")
    if not issues:
        lines.append("✅ PASS — no integrity issues detected.")
    else:
        lines.append("⚠ ISSUES:")
        for it in issues:
            lines.append(f"  - {it}")
    lines.append("")
    lines.append("---")
    lines.append("_payout fields are optional. Races without a payout are not "
                 "an integrity failure; they are noted in the daily summary._")
    report_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return str(report_path)


def main() -> int:
    date_str = sys.argv[1] if len(sys.argv) > 1 else _today()
    audit = run_audit(date_str)
    # also (re)build the summary
    rebuild_summary(date_str)
    out = write_report(audit)
    print(json.dumps(audit, indent=2, default=str)[:2000])
    print(f"report: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
