"""Intraday AGF capture + steam move detection — insider sinyal yakalama.

Berkay (2026-06-30): 'agfsi aktif cok degisen bir atin kuponlarda olmasi
insider betting recognition anlaminda cok onemli'.

Mantık:
  • Sabah (09:00) — AGF tablosu yayınlanır, ilk snapshot alınır
  • Gün içinde (T-30 / T-15 / T-5) — anlık AGF snapshot alınır
  • Sabah vs anlık karşılaştırma:
      Δagf >= +5 pp  → 'STEAM MOVE' (insider para girişi proxy)
      Δagf <= -5 pp  → 'DRIFT OUT' (insider çıkış)
  • T-3 top4 ve T-5 altılı mesajlarında etiket olarak görünür

NOT: Backtest EDİLEMEZ — backfill'de günde tek snapshot var. Bu sadece
forward-only insider signal capture (Berkay onayıyla).

API
---
- snapshot_agf(now) → mevcut AGF tablosunu çek + diske yaz
- get_snapshots(date, hippo) → o gün için tüm snapshot dosyaları
- detect_steam_moves(date, hippo, threshold=5.0) → at başına Δagf + etiket
- steam_tag_for_horse(date, hippo, at_no) → "⚡ +%6 STEAM" gibi string
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
SNAPSHOT_DIR = ROOT / "data" / "agf_snapshots"

STEAM_THRESHOLD_PP = float(os.environ.get(
    "TJK_STEAM_THRESHOLD_PP", "5.0"))  # +%5 yükseliş → steam
DRIFT_THRESHOLD_PP = float(os.environ.get(
    "TJK_DRIFT_THRESHOLD_PP", "-5.0"))  # -%5 düşüş → drift out


def _snapshot_path(date: str, hippo: str, hhmm: str) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    safe_h = hippo.replace(" ", "_").replace("/", "_")
    return SNAPSHOT_DIR / date / f"{safe_h}_{hhmm}.json"


def snapshot_agf(now: Optional[datetime] = None) -> dict:
    """Anlık AGF tablosunu çek, diske yaz.

    Returns: {date, hhmm, n_hippos, n_horses, paths: [Path,...]}.
    """
    if now is None:
        now = datetime.now()
    date_str = now.date().isoformat()
    hhmm = now.strftime("%H%M")
    out = {"date": date_str, "hhmm": hhmm, "ts": now.isoformat(),
           "n_hippos": 0, "n_horses": 0, "paths": []}
    try:
        try:
            from scraper.agf_scraper import (
                fetch_agf_page, parse_agf_page,
            )
            html = fetch_agf_page()
            if not html:
                logger.warning("[agf-intraday] fetch empty")
                return out
            hippos = parse_agf_page(html, target_date=now.date()) or []
        except Exception as exc:
            logger.warning(f"[agf-intraday] scraper fail: {exc}")
            return out

        for hippo_entry in hippos:
            hippo = (hippo_entry.get("hippodrome")
                      or hippo_entry.get("hipodrom") or "?")
            # parse_agf_page: legs = LIST of 6 lists (ayaks); each ayak list
            # of {horse_number, agf_pct, is_ekuri}
            legs = hippo_entry.get("legs")
            horse_agf = {}
            if isinstance(legs, list):
                for idx, ayak_list in enumerate(legs, 1):
                    if not isinstance(ayak_list, list):
                        continue
                    for h in ayak_list:
                        at_no = h.get("horse_number") or h.get("at_no")
                        agf = h.get("agf_pct")
                        if at_no is not None and agf is not None:
                            key = f"{idx}_{at_no}"
                            horse_agf[key] = float(agf)
            elif isinstance(legs, dict):
                for ayak_id, horses in legs.items():
                    try:
                        ayak_no = int(ayak_id)
                    except Exception:
                        continue
                    for h in (horses or []):
                        at_no = (h.get("horse_number") or h.get("at_no"))
                        agf = h.get("agf_pct")
                        if at_no is not None and agf is not None:
                            key = f"{ayak_no}_{at_no}"
                            horse_agf[key] = float(agf)
            if not horse_agf:
                continue
            p = _snapshot_path(date_str, hippo, hhmm)
            p.parent.mkdir(parents=True, exist_ok=True)
            with open(p, "w", encoding="utf-8") as f:
                json.dump({
                    "ts": now.isoformat(), "hippo": hippo,
                    "date": date_str, "hhmm": hhmm,
                    "horse_agf": horse_agf,
                }, f, ensure_ascii=False)
            out["paths"].append(str(p))
            out["n_hippos"] += 1
            out["n_horses"] += len(horse_agf)
        logger.info(f"[agf-intraday] snapshot {hhmm}: "
                    f"{out['n_hippos']} hippo, {out['n_horses']} at")
    except Exception as exc:
        logger.warning(f"[agf-intraday] snapshot fail: {exc}")
    return out


def get_snapshots(date: str, hippo: str) -> list[dict]:
    """O gün/hipodrom için tüm snapshot'ları kronolojik döndür."""
    safe_h = hippo.replace(" ", "_").replace("/", "_")
    day_dir = SNAPSHOT_DIR / date
    if not day_dir.exists():
        return []
    out = []
    for fp in sorted(day_dir.glob(f"{safe_h}_*.json")):
        try:
            with open(fp) as f:
                out.append(json.load(f))
        except Exception:
            pass
    return out


def detect_steam_moves(date: str, hippo: str,
                        threshold_pp: Optional[float] = None) -> dict:
    """At başına AGF değişimi + steam/drift etiketleri.

    Returns: {
      "early_hhmm": "0930",
      "latest_hhmm": "1145",
      "comparisons": [
        {"key": "3_7", "ayak": 3, "at_no": 7, "early_agf": 4.2,
         "latest_agf": 12.5, "delta_pp": 8.3, "tag": "STEAM"},
        ...
      ],
      "steam_horses": [(ayak, at_no), ...],
      "drift_horses": [...]
    }
    """
    threshold_pp = threshold_pp or STEAM_THRESHOLD_PP
    snaps = get_snapshots(date, hippo)
    if len(snaps) < 2:
        return {"comparisons": [], "steam_horses": [], "drift_horses": []}
    early = snaps[0]
    latest = snaps[-1]
    comparisons = []
    steam_horses = []
    drift_horses = []
    for key, late_agf in latest.get("horse_agf", {}).items():
        early_agf = (early.get("horse_agf") or {}).get(key)
        if early_agf is None:
            continue
        delta = late_agf - early_agf
        try:
            ayak_str, at_str = key.split("_")
            ayak, at_no = int(ayak_str), int(at_str)
        except Exception:
            continue
        tag = ""
        if delta >= threshold_pp:
            tag = "STEAM"
            steam_horses.append((ayak, at_no))
        elif delta <= DRIFT_THRESHOLD_PP:
            tag = "DRIFT"
            drift_horses.append((ayak, at_no))
        comparisons.append({
            "key": key, "ayak": ayak, "at_no": at_no,
            "early_agf": round(early_agf, 2),
            "latest_agf": round(late_agf, 2),
            "delta_pp": round(delta, 2), "tag": tag,
        })
    return {
        "early_hhmm": early.get("hhmm"),
        "latest_hhmm": latest.get("hhmm"),
        "comparisons": comparisons,
        "steam_horses": steam_horses,
        "drift_horses": drift_horses,
    }


def steam_tag_for_horse(date: str, hippo: str, ayak: int,
                         at_no: int) -> str:
    """At başına kompakt etiket: '⚡ +6.2pp STEAM' veya ''."""
    try:
        result = detect_steam_moves(date, hippo)
        for c in result.get("comparisons", []):
            if c["ayak"] == ayak and c["at_no"] == at_no:
                if c["tag"] == "STEAM":
                    return f"⚡ AGF +{c['delta_pp']:.1f}pp"
                if c["tag"] == "DRIFT":
                    return f"📉 AGF {c['delta_pp']:+.1f}pp"
                return ""
    except Exception:
        pass
    return ""


def steam_tag_for_race_no(date: str, hippo: str, race_no: int,
                            at_no: int) -> str:
    """race_no = global kosu_no (outcomes_rich/smart_coupon).

    AGF snapshot ayak (altılı içinde 1-6) ile match için her ayağı dene.
    """
    try:
        result = detect_steam_moves(date, hippo)
        for c in result.get("comparisons", []):
            # race_no doğrudan ayak değil; gevşek match dene
            if c["at_no"] == at_no and c["tag"]:
                if c["tag"] == "STEAM":
                    return f"⚡ AGF +{c['delta_pp']:.1f}pp"
                if c["tag"] == "DRIFT":
                    return f"📉 AGF {c['delta_pp']:+.1f}pp"
    except Exception:
        pass
    return ""
