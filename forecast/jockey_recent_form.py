"""Jokey son N gün form — runtime hesap (retrain gerektirmez).

Berkay (2026-07-01): 'oldukça pushla canlıya, model ona göre çıktı versin'.

Backfill outcomes_rich'ten jokey × son N gün top4 hit rate hesaplanır.
Publisher inference zamanında bu değerleri lookup eder.

Rolling window: default 30 gün (parametric).

API
---
- build_jockey_form_map(days_back=30) → {jockey_name: {n, top4, hot_rate}}
- get_hot_tag(jockey, form_map, thresh_hot=0.40) → "🔥 JOKEY HOT %X" | ""
"""
from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent
OUTCOMES_DIR = ROOT / "data" / "backfill" / "outcomes_rich"


def build_jockey_form_map(days_back: int = 30,
                            end_date: str = None,
                            min_n: int = 8) -> dict:
    """Jokey → son N gün top4/win rate.

    Returns:
      {jockey: {"n": int, "top4": int, "wins": int,
                "top4_rate": %, "win_rate": %, "hot": bool}}
    """
    if end_date is None:
        end_date = date.today().isoformat()
    end_d = date.fromisoformat(end_date)
    start_d = end_d - timedelta(days=days_back)

    stats = defaultdict(lambda: {"n": 0, "top4": 0, "wins": 0})
    for fp in sorted(OUTCOMES_DIR.glob("*.json")):
        try:
            fd = date.fromisoformat(fp.stem)
        except Exception:
            continue
        if not (start_d <= fd < end_d):
            continue
        try:
            with open(fp) as f:
                d = json.load(f)
        except Exception:
            continue
        for hip in (d.get("hippodromes") or []):
            for kv in (hip.get("kosular") or {}).values():
                for fin in (kv.get("finishers") or []):
                    j = (fin.get("jockey") or "").strip()
                    S = fin.get("S")
                    if not j or not isinstance(S, int):
                        continue
                    stats[j]["n"] += 1
                    if S <= 4:
                        stats[j]["top4"] += 1
                    if S == 1:
                        stats[j]["wins"] += 1

    out = {}
    for j, s in stats.items():
        if s["n"] < min_n:
            continue
        rt4 = s["top4"] / s["n"]
        rw = s["wins"] / s["n"]
        out[j] = {
            "n": s["n"], "top4": s["top4"], "wins": s["wins"],
            "top4_rate": round(rt4 * 100, 1),
            "win_rate": round(rw * 100, 1),
            "hot": rt4 >= 0.40,
            "elite": rt4 >= 0.50,
        }
    logger.info(f"[jockey-form] {len(out)} jockeys, "
                f"days_back={days_back}, min_n={min_n}")
    return out


def _normalize_jockey(name: str) -> str:
    """Full name → abbreviated (İSA AKYAVUZ → İ.AKYAVUZ).

    Outcomes_rich abbreviated saklıyor, yerli_engine full veriyor.
    """
    if not name:
        return ""
    n = name.strip()
    # Already abbreviated
    if "." in n and len(n) < 20:
        return n
    parts = n.split()
    if len(parts) >= 2:
        return f"{parts[0][0]}.{parts[-1]}"
    return n


def _lookup(jockey: str, form_map: dict) -> dict:
    if not jockey:
        return {}
    n = jockey.strip()
    # try exact, then normalized
    return form_map.get(n) or form_map.get(_normalize_jockey(n)) or {}


def get_hot_tag(jockey: str, form_map: dict,
                 thresh: float = 40.0) -> str:
    """Publisher etiketi — sadece HOT jokeyler için."""
    s = _lookup(jockey, form_map)
    if not s:
        return ""
    rt = s["top4_rate"]
    if s.get("elite"):
        return f"🔥 JOKEY ELİT %{rt:.0f}"
    if s.get("hot"):
        return f"🔥 JOKEY HOT %{rt:.0f}"
    return ""


def get_jockey_form_ratio(jockey: str, form_map: dict) -> float:
    """0..1 scale — hibrit skor'a katkı için."""
    s = _lookup(jockey, form_map)
    if not s:
        return 0.30
    return round(s["top4_rate"] / 100.0, 3)
