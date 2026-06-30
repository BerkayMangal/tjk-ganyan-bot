"""Live UK Odds Steam Tracking — yabancı bookmaker insider sermaye taklit.

Berkay (2026-06-30): 'alfa alfa alfa para — yurtdışında çok beğenilen
ama TJK'de gözden kaçan atlar'.

EN BÜYÜK ALFA: TJK racecard'daki yabancı atların UK/IRE bookmaker
odds'unu sabah, T-30, T-15, T-5 anlarında çek. Eğer UK odds DÜŞÜYORSA
(steam in), aynı at TJK AGF'sinde değişmemişse → halk fark etmemiş,
insider taklit et, TJK'da OYNA.

Akış:
  1) Sabah 09:00 — TJK racecard yabancı at adlarını topla
  2) RacingAPI'den her at için UK odds çek (consensus)
  3) Snapshot disk'e
  4) T-30/T-15/T-5'te aynısı tekrar
  5) Δ ≥ -10% (odds düşmüş = at "hot") → STEAM signal
  6) T-3 mesajında "⚡ UK STEAM Δ-15% — INSIDER" etiketi

Cache: data/uk_live_odds/<date>/<horse>_<HHMM>.json
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
CACHE_DIR = ROOT / "data" / "uk_live_odds"

# Steam threshold: odds düşüşü (= at hot)
STEAM_DROP_PCT = float(os.environ.get("TJK_UK_STEAM_DROP_PCT", "-10.0"))
DRIFT_RISE_PCT = float(os.environ.get("TJK_UK_DRIFT_RISE_PCT", "10.0"))


def _safe_name(s: str) -> str:
    return s.replace(" ", "_").replace("/", "_")[:60]


def snapshot_uk_odds(horse_names: list[str],
                      now: Optional[datetime] = None) -> dict:
    """Verilen at adları için UK odds (consensus) anlık snapshot.

    Returns: {horse: {consensus_prob, best_odds, n_bookmakers, hhmm}}
    """
    if now is None:
        now = datetime.now()
    date_str = now.date().isoformat()
    hhmm = now.strftime("%H%M")
    CACHE_DIR.mkdir(parents=True, exist_ok=True)

    try:
        from forecast.sources.theracingapi import RacingAPIClient
        from forecast.racing_api_value import (
            consensus_fair_prob, extract_runner_odds,
        )
    except Exception as exc:
        logger.warning(f"uk_live_odds import: {exc}")
        return {}
    client = RacingAPIClient.from_env()
    if not client.enabled:
        return {}

    out = {}
    for name in horse_names:
        try:
            results = client.search_horse(name) or []
            if not results:
                continue
            horse_id = results[0].get("horse_id") or results[0].get("id")
            if not horse_id:
                continue
            # Pro endpoint to get current odds (if at has active entries)
            pro = client.horse_pro(horse_id) or {}
            # Try to find today's entry with odds
            entries = pro.get("entries") or pro.get("races") or []
            for entry in entries:
                runner = entry.get("runner") or entry
                odds_dict = extract_runner_odds(runner)
                if len(odds_dict) < 3:
                    continue
                odds_values = list(odds_dict.values())
                consensus_p = consensus_fair_prob(odds_values)
                if consensus_p is None:
                    continue
                snap = {
                    "horse_id": horse_id, "horse_name": name,
                    "consensus_prob": round(consensus_p, 4),
                    "best_odds": round(max(odds_values), 2),
                    "n_bookmakers": len(odds_dict),
                    "hhmm": hhmm, "ts": now.isoformat(),
                }
                out[name] = snap
                # Persist
                day_dir = CACHE_DIR / date_str
                day_dir.mkdir(parents=True, exist_ok=True)
                p = day_dir / f"{_safe_name(name)}_{hhmm}.json"
                with open(p, "w", encoding="utf-8") as f:
                    json.dump(snap, f, ensure_ascii=False)
                break  # ilk match yeterli
        except Exception as exc:
            logger.debug(f"snapshot {name}: {exc}")
    logger.info(f"[uk-live-odds] snapshot {hhmm}: {len(out)} at")
    return out


def get_uk_steam_signal(horse_name: str, date: str) -> dict:
    """Bir at için sabah vs latest UK odds farkı.

    Returns: {has_steam, delta_pct, tag, early_odds, latest_odds}
    """
    day_dir = CACHE_DIR / date
    if not day_dir.exists():
        return {"has_steam": False}
    safe = _safe_name(horse_name)
    snaps = sorted(day_dir.glob(f"{safe}_*.json"))
    if len(snaps) < 2:
        return {"has_steam": False}
    try:
        with open(snaps[0]) as f:
            early = json.load(f)
        with open(snaps[-1]) as f:
            latest = json.load(f)
    except Exception:
        return {"has_steam": False}

    early_odds = early.get("best_odds")
    latest_odds = latest.get("best_odds")
    if not (early_odds and latest_odds):
        return {"has_steam": False}
    # Δ% = (latest - early) / early * 100
    # Steam: odds DÜŞÜYOR (latest < early) → at hot, money in
    # Drift: odds YÜKSELİYOR → at soğuk
    delta_pct = (latest_odds - early_odds) / early_odds * 100

    if delta_pct <= STEAM_DROP_PCT:
        tag = f"⚡ UK STEAM {delta_pct:.1f}%"
        return {
            "has_steam": True, "kind": "STEAM",
            "delta_pct": delta_pct, "tag": tag,
            "early_odds": early_odds, "latest_odds": latest_odds,
            "score": min(1.0, abs(delta_pct) / 20),  # 20% = full
        }
    if delta_pct >= DRIFT_RISE_PCT:
        tag = f"📉 UK DRIFT +{delta_pct:.1f}%"
        return {
            "has_steam": False, "kind": "DRIFT",
            "delta_pct": delta_pct, "tag": tag,
            "early_odds": early_odds, "latest_odds": latest_odds,
            "score": -min(1.0, delta_pct / 20),
        }
    return {"has_steam": False, "delta_pct": delta_pct}
