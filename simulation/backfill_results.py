"""Phase 5.2 — Geçmiş yarış sonuçları backfill (retro wrap + disk cache).

engine.retro.fetch_results geçmiş sonuçları (agftablosu/at-yarisi-sonuclar) çekiyor
(Phase 5.1: lokal IP ~1 ay geriye). Bu modül onu sarar + diske cache'ler (idempotent).
Read-only, simulation/ altında.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date as _date
from typing import Optional

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

CACHE_DIR = os.path.join(_REPO, "data", "backfill", "results")


def fetch_results_for_date(date_str: str) -> dict:
    """date_str='YYYY-MM-DD'. Returns {date, ok, altilis:[{hippodrome, altili_no,
    winners:[{leg_number, horse_number, ganyan}]}]}."""
    out = {"date": date_str, "source": "agftablosu/retro", "ok": False, "error": None, "altilis": []}
    try:
        from engine.retro import fetch_results
        y, m, d = (int(x) for x in date_str.split("-"))
        rows = fetch_results(_date(y, m, d)) or []
        for r in rows:
            out["altilis"].append({
                "hippodrome": r.get("hippodrome"),
                "altili_no": r.get("altili_no"),
                "winners": [{"leg_number": w.get("leg_number"),
                             "horse_number": w.get("horse_number"),
                             "ganyan": w.get("ganyan")} for w in (r.get("winners") or [])],
            })
        out["ok"] = bool(out["altilis"])
    except Exception as e:
        out["error"] = repr(e)[:120]
    return out


def is_cached(date_str: str) -> bool:
    return os.path.exists(os.path.join(CACHE_DIR, date_str, "results.json"))


def save_day(day: dict) -> Optional[str]:
    if not day.get("ok"):
        return None
    os.makedirs(os.path.join(CACHE_DIR, day["date"]), exist_ok=True)
    path = os.path.join(CACHE_DIR, day["date"], "results.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return path
