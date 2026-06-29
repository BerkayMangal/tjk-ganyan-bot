"""Forward proof logger — T-5 bildirimleri JSONL'e kayıt + outcome eşleme.

Berkay (2026-06-29): 'forward vs model' — backtest yetmez, gerçek production
ile karşılaştırma şart.

Akış:
  • T-5 bildirim üretilir → log_t5_prediction(date, hippo, race_no, analysis)
  • data/forward_log/<date>.jsonl'e satır eklenir
  • Gece run_daily_recap çağırır → match_with_outcomes(date)
  • outcomes_rich ile eşleştirip "did_we_predict_top4" / "did_winner_match"
    flag'leri eklenir

Sonuç:
  • forward_hit_rate (gerçek production accuracy)
  • backtest_vs_forward_gap → gerçek edge ölçümü

API
---
- `log_t5_prediction(date, hippo, race_no, analysis, race_time)`
- `match_with_outcomes(date)` → forward log + outcomes paired
- `summarize_forward_metrics(start_date, end_date)` → hit rates
"""
from __future__ import annotations

import json
import logging
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "data" / "forward_log"


def _log_path(date: str) -> Path:
    return LOG_DIR / f"{date}.jsonl"


def log_t5_prediction(date: str, hippo: str, race_no: int,
                      analysis: dict,
                      race_time: Optional[str] = None) -> bool:
    """T-5 anında verilen tahmin → kalıcı kayıt.

    Args:
        date: ISO YYYY-MM-DD
        hippo: hipodrom adı
        race_no: koşu no
        analysis: race_analyzer.analyze_race çıktısı
        race_time: HH:MM

    Returns: True (saved) / False (fail).
    """
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    if not analysis or not analysis.get("winner"):
        return False
    winner = analysis["winner"]
    record = {
        "ts": datetime.now().isoformat(),
        "date": date, "hippo": hippo, "race_no": race_no,
        "race_time": race_time,
        "model_version": "v9_ensemble",
        "winner_no": winner.get("no"),
        "winner_name": winner.get("name"),
        "winner_score": winner.get("score"),
        "winner_mc_p1": winner.get("mc_p1"),
        "winner_v8_p4": winner.get("v8_p4"),
        "winner_pace": winner.get("pace"),
        "winner_tempo_top3_count": winner.get("tempo_top3_count"),
        "top4_overlap": analysis.get("top4_overlap"),
        "race_tempo_verdict": analysis.get("race_tempo_verdict"),
        "v8_top5": [{"no": x.get("no"), "name": x.get("name"),
                     "p_top4": x.get("p_top4")}
                    for x in (analysis.get("v8_top5") or [])],
        "mc_top5": [{"no": x.get("no"), "name": x.get("name"),
                     "mc_p1": x.get("mc_p1")}
                    for x in (analysis.get("mc_top5") or [])],
        "composite_top5": [{"no": x.get("no"), "name": x.get("name"),
                            "score": x.get("score"),
                            "pace": x.get("pace")}
                           for x in (analysis.get("composite_top5") or [])],
        "outcome_matched": False,
    }
    try:
        with open(_log_path(date), "a", encoding="utf-8") as f:
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
        return True
    except Exception as exc:
        logger.warning(f"forward log write fail: {exc}")
        return False


def _load_outcomes_for_date(date: str) -> dict:
    """outcomes_rich'ten o gün için lookup tablosu."""
    out_path = ROOT / "data" / "backfill" / "outcomes_rich" / f"{date}.json"
    if not out_path.exists():
        return {}
    try:
        with open(out_path) as f:
            d = json.load(f)
    except Exception:
        return {}
    lookup = {}  # (hippo, race_no) → list of (S, at_no, name)
    for hippo_entry in (d.get("hippodromes") or []):
        hippo = hippo_entry.get("hippodrome", "")
        for k_id, k in (hippo_entry.get("kosular") or {}).items():
            try:
                race_no = int(k_id)
            except Exception:
                continue
            fins = []
            for fin in (k.get("finishers") or []):
                fins.append({
                    "S": fin.get("S"),
                    "at_no": fin.get("at_no"),
                    "name": fin.get("name"),
                })
            lookup[(hippo, race_no)] = fins
    return lookup


def match_with_outcomes(date: str) -> dict:
    """Forward log + outcomes_rich → "predicted vs actual" eşleştirme.

    Returns: {n_predictions, n_matched, winner_hit_rate, top4_hit_rate}
    """
    log_p = _log_path(date)
    if not log_p.exists():
        return {"n_predictions": 0}
    outcomes = _load_outcomes_for_date(date)
    if not outcomes:
        return {"n_predictions": -1, "reason": "outcomes not yet available"}

    records = []
    try:
        with open(log_p, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    records.append(json.loads(line))
    except Exception as exc:
        logger.warning(f"forward log read fail: {exc}")
        return {}

    updated = []
    n_winner_hit = 0
    n_top4_hit = 0
    n_top5_hit = 0
    n_matched = 0
    n_total = len(records)
    for r in records:
        key = (r.get("hippo"), r.get("race_no"))
        # Hippo normalize — 'İstanbul' vs 'İstanbul Hipodromu' sapması olabilir
        fins = outcomes.get(key)
        if not fins:
            # fallback fuzzy match
            for (h, rn), v in outcomes.items():
                if rn == r.get("race_no") and (
                        r.get("hippo", "") in h or h in r.get("hippo", "")):
                    fins = v
                    break
        if not fins:
            r["outcome_matched"] = False
            updated.append(r)
            continue
        # Winner check
        actual_winner_no = next(
            (f["at_no"] for f in fins if f.get("S") == 1), None)
        winner_predicted = r.get("winner_no") == actual_winner_no
        # Top-4 actual set
        actual_top4 = {f["at_no"] for f in fins
                       if isinstance(f.get("S"), int) and f["S"] <= 4}
        # Predicted top-5 set
        pred_top5 = {x.get("no")
                     for x in (r.get("composite_top5") or [])}
        # Predicted top-4 set (composite top-4)
        pred_top4 = {x.get("no")
                     for x in (r.get("composite_top5") or [])[:4]}
        winner_in_top4_pred = actual_winner_no in pred_top4
        top4_overlap = len(actual_top4 & pred_top4)
        top5_overlap = len(actual_top4 & pred_top5)
        r["outcome_matched"] = True
        r["actual_winner_no"] = actual_winner_no
        r["winner_predicted"] = winner_predicted
        r["winner_in_predicted_top4"] = winner_in_top4_pred
        r["top4_actual_in_pred4_count"] = top4_overlap
        r["top4_actual_in_pred5_count"] = top5_overlap
        updated.append(r)
        n_matched += 1
        if winner_predicted:
            n_winner_hit += 1
        if winner_in_top4_pred:
            n_top4_hit += 1
        if top5_overlap >= 1:
            n_top5_hit += 1

    # Re-write log
    with open(log_p, "w", encoding="utf-8") as f:
        for r in updated:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")

    return {
        "date": date,
        "n_predictions": n_total,
        "n_matched": n_matched,
        "winner_hit_rate": (n_winner_hit / n_matched
                             if n_matched else 0),
        "winner_in_pred_top4_rate": (n_top4_hit / n_matched
                                       if n_matched else 0),
        "actual_top4_in_pred5_any_rate": (n_top5_hit / n_matched
                                            if n_matched else 0),
    }


def summarize_forward_metrics(start_date: str, end_date: str) -> dict:
    """Tarih aralığında forward proof özet."""
    from datetime import date as _d, timedelta
    s = _d.fromisoformat(start_date)
    e = _d.fromisoformat(end_date)
    daily = []
    while s <= e:
        m = match_with_outcomes(s.isoformat())
        if m and m.get("n_matched", 0) > 0:
            daily.append(m)
        s += timedelta(days=1)
    if not daily:
        return {"n_days": 0}
    total_pred = sum(d["n_matched"] for d in daily)
    total_winner = sum(d["winner_hit_rate"] * d["n_matched"]
                       for d in daily)
    total_top4 = sum(d["winner_in_pred_top4_rate"] * d["n_matched"]
                     for d in daily)
    return {
        "n_days": len(daily),
        "n_predictions": total_pred,
        "winner_hit_rate": total_winner / total_pred if total_pred else 0,
        "winner_in_pred_top4_rate": (total_top4 / total_pred
                                       if total_pred else 0),
        "daily": daily,
    }
