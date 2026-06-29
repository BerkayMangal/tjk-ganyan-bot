"""AGF tarihsel hareket embedding — smart money / public bias features.

Berkay (2026-06-29): 'icine agf hareketlerini de embedded yapip backtest'.

Atın 'halk gözünden kaçan ama top-4 yapan' sıklığı = saklı edge sinyali.

Yöntem:
  • data/backfill/agftahmin/ → AGF tarihsel (180g)
  • data/backfill/outcomes_rich/ → outcome (S=sıralama)
  • Paired join (date, hippo, kosu_no, at_no) → at_name × AGF history
  • Her at için kronolojik AGF örüntüsü
  • Features: avg, trend (slope), volatility, underdog_top4, AGF band

API
---
- `build_agf_history_map(agf_root, outcomes_root)` → {name: list[dict]}
- `agf_features(name, ref_date, agf_history_map, outcome_history)`
"""
from __future__ import annotations

import json
import logging
import math
import os
from collections import defaultdict
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)


def build_agf_history_map(agf_root: str, outcomes_root: str) -> dict:
    """AGF tarih + outcomes pair join → at-bazlı AGF zaman serisi.

    Returns: {horse_name: [{date, hippo, kosu_no, at_no, agf_pct, finish}, ...]}
    Sorted by date DESC (en taze önce).
    """
    agf_root = Path(agf_root)
    outcomes_root = Path(outcomes_root)
    if not agf_root.exists() or not outcomes_root.exists():
        logger.warning(f"AGF/outcomes klasör yok: {agf_root}, {outcomes_root}")
        return {}

    # 1) outcomes_rich → (date, hippo, kosu_no, at_no) → name + finish
    outcome_lookup = {}
    for fp in sorted(outcomes_root.glob("*.json")):
        try:
            with open(fp) as f:
                d = json.load(f)
        except Exception:
            continue
        date = d.get("date")
        for hippo_entry in (d.get("hippodromes") or []):
            hippo = hippo_entry.get("hippodrome", "")
            for k_id, k in (hippo_entry.get("kosular") or {}).items():
                try:
                    kosu_no = int(k_id)
                except Exception:
                    continue
                for fin in (k.get("finishers") or []):
                    key = (date, hippo, kosu_no, fin.get("at_no"))
                    outcome_lookup[key] = {
                        "name": fin.get("name"),
                        "finish": fin.get("S"),
                    }

    # 2) AGF → her satır için outcome lookup ile birleştir
    horse_history: dict = defaultdict(list)
    for date_dir in sorted(agf_root.iterdir()):
        if not date_dir.is_dir():
            continue
        agf_path = date_dir / "agf.json"
        if not agf_path.exists():
            continue
        try:
            with open(agf_path) as f:
                agf_data = json.load(f)
        except Exception:
            continue
        date = agf_data.get("date") or date_dir.name
        for alt in (agf_data.get("altilis") or []):
            hippo = alt.get("hippodrome", "")
            legs = alt.get("legs") or {}
            # altili_no farklı olabilir ama outcomes_rich'te kosu_no
            # global. Burada legs ayak numarası YEREL altılı içinde.
            # Outcomes_rich'te kosu_no genel sıralama — birebir eşleşmez.
            # Best effort: at_no + agf_pct + tarih + hipodrom
            for ayak_id, horses in legs.items():
                try:
                    ayak_no = int(ayak_id)
                except Exception:
                    continue
                # Tüm kosu_no'larını dene; outcome'da match olanı al
                for h in (horses or []):
                    at_no = h.get("at_no")
                    agf_pct = h.get("agf_pct")
                    if at_no is None or agf_pct is None:
                        continue
                    # Match: kosu_no'su bilinmiyor, en yakın tarih/hipodrom
                    # eşleşmesini dene
                    # Önce direkt key dene
                    matched = None
                    for kosu_offset in (ayak_no,
                                         ayak_no + 6 * (alt.get("altili_no", 1) - 1)):
                        key = (date, hippo, kosu_offset, at_no)
                        if key in outcome_lookup:
                            matched = outcome_lookup[key]
                            break
                    if matched is None:
                        continue
                    nm = matched.get("name")
                    if not nm:
                        continue
                    horse_history[nm].append({
                        "date": date, "hippo": hippo, "ayak": ayak_no,
                        "at_no": at_no, "agf_pct": float(agf_pct),
                        "finish": matched.get("finish"),
                    })
    # Sort desc by date
    for nm in horse_history:
        horse_history[nm].sort(key=lambda x: x["date"], reverse=True)
    logger.info(f"AGF history map: {len(horse_history)} at")
    return dict(horse_history)


def _agf_band(agf_pct: float) -> str:
    """AGF bandı kategorize: heavy / med / med-low / longshot."""
    if agf_pct >= 30:
        return "heavy"
    if agf_pct >= 15:
        return "med"
    if agf_pct >= 5:
        return "med_low"
    return "longshot"


def _slope(xs: list) -> float:
    """Basit lineer regresyon slope (en güncel önce verilmiş seri)."""
    n = len(xs)
    if n < 2:
        return 0.0
    # x = 0..n-1 (n-1 en eski, 0 en taze)
    indices = list(range(n))
    mx = sum(indices) / n
    my = sum(xs) / n
    num = sum((i - mx) * (x - my) for i, x in zip(indices, xs))
    den = sum((i - mx) ** 2 for i in indices)
    return num / den if den > 0 else 0.0


def agf_features(name: str, ref_date: str,
                  agf_history_map: dict, top_n: int = 6) -> dict:
    """Bir at için AGF tarihsel features (point-in-time).

    Returns dict (10 feature, AGF-FREE FALSE — bu AGF'yi KULLANIYOR
    ama "halk vs gerçek" sapma sinyali olarak):
      agf_recent_avg, agf_recent_max, agf_recent_min, agf_recent_std,
      agf_trend, agf_underdog_top4_rate, agf_overbet_miss_rate,
      agf_heavy_count, agf_longshot_count, agf_n_history
    """
    out = {
        "agf_recent_avg": 0.0, "agf_recent_max": 0.0,
        "agf_recent_min": 0.0, "agf_recent_std": 0.0,
        "agf_trend": 0.0, "agf_underdog_top4_rate": 0.0,
        "agf_overbet_miss_rate": 0.0,
        "agf_heavy_count": 0, "agf_longshot_count": 0,
        "agf_n_history": 0,
    }
    if not name or not agf_history_map:
        return out
    past = [h for h in (agf_history_map.get(name) or [])
            if h.get("date", "9999") < ref_date]
    if not past:
        return out
    past = past[:top_n]
    pcts = [h["agf_pct"] for h in past if isinstance(h.get("agf_pct"),
                                                       (int, float))]
    if not pcts:
        return out
    out["agf_n_history"] = len(past)
    out["agf_recent_avg"] = sum(pcts) / len(pcts)
    out["agf_recent_max"] = max(pcts)
    out["agf_recent_min"] = min(pcts)
    if len(pcts) > 1:
        m = sum(pcts) / len(pcts)
        out["agf_recent_std"] = math.sqrt(
            sum((p - m) ** 2 for p in pcts) / len(pcts))
        out["agf_trend"] = _slope(pcts)
    # Underdog top4 rate: AGF < %10 iken top4'e girme sıklığı
    underdog_n = sum(1 for h in past
                     if h["agf_pct"] < 10
                     and isinstance(h.get("finish"), int)
                     and h["finish"] <= 4)
    underdog_total = sum(1 for h in past if h["agf_pct"] < 10
                          and isinstance(h.get("finish"), int))
    out["agf_underdog_top4_rate"] = (underdog_n / underdog_total
                                      if underdog_total else 0.0)
    # Overbet miss: AGF heavy (>%30) iken top4'e GİRMEME sıklığı
    heavy_n = [h for h in past if h["agf_pct"] >= 30
                and isinstance(h.get("finish"), int)]
    heavy_miss = sum(1 for h in heavy_n if h["finish"] > 4)
    out["agf_overbet_miss_rate"] = (heavy_miss / len(heavy_n)
                                     if heavy_n else 0.0)
    out["agf_heavy_count"] = sum(1 for h in past if h["agf_pct"] >= 30)
    out["agf_longshot_count"] = sum(1 for h in past if h["agf_pct"] < 5)
    return out
