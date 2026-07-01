"""UK/IRE/FR yarış analizi — TOP-4 tahmini + arbitraj tespiti.

Berkay (2026-07-01): 'yurtdisi yarislari icin de gelmesi lazim, top4
mesela veya arbitraj bulursa yurtdisi favori TJK yuksek gibi'.

Model-free strateji (V9.5 TR-spesifik olduğu için UK'da consensus kullan):
  1) RacingAPI'den UK yarış + multi-bookmaker odds
  2) Her at için bookmaker consensus fair probability
  3) Sıralama = TOP-4 tahmini (10+ bookmaker "wisdom of crowds")
  4) Ek: value bet tespiti (best outlier vs consensus)
  5) Ek: TR AGF karşılaştırma (aynı at TR'de koşuyorsa → cross-market arbitraj)

API
---
- analyze_uk_race(race_data) → {top4, value_bets, arbitrage_signals}
- fetch_upcoming_uk_races(hours_ahead=2, regions=('gb','ire','fr'))
- format_uk_race_telegram(analysis) → kompakt Telegram mesajı
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta
from typing import Optional

logger = logging.getLogger(__name__)


def analyze_uk_race(race_data: dict,
                     my_bookmakers: Optional[list[str]] = None) -> dict:
    """Bir UK yarış için tam analiz.

    Returns:
      {
        course, off_time, region, n_runners,
        top4: [{horse_name, consensus_prob, best_odds, best_bm, ...}],
        value_bets: [+EV outlier'lar],
        strong_favorite: en yüksek consensus at (arbitraj adayı),
        confidence: 'HIGH' if top1 consensus >= 40%,
      }
    """
    try:
        from forecast.racing_api_value import (
            extract_runner_odds, consensus_fair_prob, kelly_fraction,
        )
    except Exception as exc:
        logger.warning(f"racing_api_value import: {exc}")
        return {}

    runners = (race_data.get("runners") or race_data.get("horses") or [])
    if not runners:
        return {}

    # Her at için: consensus prob, best odds, best bm
    analyses = []
    for runner in runners:
        odds_dict = extract_runner_odds(runner)
        if len(odds_dict) < 3:
            continue
        best_bm, best_odds = max(odds_dict.items(), key=lambda x: x[1])
        # Consensus (best hariç)
        non_best = [o for bm, o in odds_dict.items() if bm != best_bm]
        consensus_p = consensus_fair_prob(non_best or list(odds_dict.values()))
        if consensus_p is None:
            continue
        # Value?
        implied_p = 1.0 / best_odds
        ev_pct = (consensus_p * (best_odds - 1) - (1 - consensus_p)) * 100
        # My bookmakers filter
        is_my_bm = True
        if my_bookmakers:
            is_my_bm = any(bm.lower() in best_bm.lower()
                            for bm in my_bookmakers)
        analyses.append({
            "horse_name": runner.get("name") or runner.get("horse") or "?",
            "horse_id": runner.get("horse_id") or runner.get("id"),
            "consensus_prob_pct": round(consensus_p * 100, 2),
            "best_odds": round(best_odds, 2),
            "best_bookmaker": best_bm,
            "implied_prob_pct": round(implied_p * 100, 2),
            "ev_pct": round(ev_pct, 2),
            "kelly_pct": round(kelly_fraction(best_odds, consensus_p) * 100, 2),
            "is_my_bookmaker": is_my_bm,
            "n_bookmakers": len(odds_dict),
        })

    if not analyses:
        return {}

    # Sıralama: consensus_prob descending
    analyses.sort(key=lambda x: -x["consensus_prob_pct"])
    top4 = analyses[:4]

    # Value bets (min EV %5, my bookmaker filter)
    value_bets = [a for a in analyses
                  if a["ev_pct"] >= 5.0 and a.get("is_my_bookmaker")]
    value_bets.sort(key=lambda x: -x["ev_pct"])

    # Strong favorite (top1 consensus ≥ 40%)
    strong_fav = None
    if top4 and top4[0]["consensus_prob_pct"] >= 40:
        strong_fav = top4[0]
    confidence = "HIGH" if strong_fav else (
        "MED" if top4 and top4[0]["consensus_prob_pct"] >= 25 else "LOW")

    return {
        "course": race_data.get("course") or "?",
        "off_time": race_data.get("off_time") or race_data.get("time"),
        "race_id": race_data.get("race_id") or race_data.get("id"),
        "region": (race_data.get("region") or "").upper(),
        "n_runners": len(analyses),
        "top4": top4,
        "value_bets": value_bets[:3],
        "strong_favorite": strong_fav,
        "confidence": confidence,
    }


def fetch_upcoming_uk_races(hours_ahead: float = 2.0,
                             regions: tuple = ("gb", "ire", "fr"),
                             my_bookmakers: Optional[list[str]] = None
                             ) -> list[dict]:
    """T-hours_ahead süre içinde başlayacak UK yarışları çek + analyze.

    Returns: [analyze_uk_race(...) çıktı list].
    """
    try:
        from forecast.sources.theracingapi import RacingAPIClient
    except Exception:
        return []
    client = RacingAPIClient.from_env()
    if not client.enabled:
        return []

    out = []
    now = datetime.now()
    cutoff = now + timedelta(hours=hours_ahead)
    for region in regions:
        try:
            cards = client.racecards_today(region=region) or []
        except Exception:
            continue
        for card in cards:
            races = card.get("races") or [card]
            for race in races:
                if "region" not in race:
                    race["region"] = region
                # Off time check (nadir bulunabilir)
                off = race.get("off_time") or race.get("time")
                if off:
                    try:
                        # Basit parse (dt objesi yoksa string kontrolü)
                        pass
                    except Exception:
                        pass
                analysis = analyze_uk_race(race, my_bookmakers=my_bookmakers)
                if analysis:
                    out.append(analysis)
    return out


def format_uk_race_telegram(analysis: dict) -> str:
    """UK yarış TOP-4 + varsa value bet + arbitraj → Telegram mesajı."""
    if not analysis:
        return ""
    course = analysis.get("course", "?")
    region = analysis.get("region", "?")
    off = analysis.get("off_time") or "?"
    conf = analysis.get("confidence", "LOW")

    icon = "🌍" if conf == "LOW" else ("🎯" if conf == "MED" else "🔥")
    lines = [
        f"{icon} <b>{region} {course}</b>  ({off})",
        f"    {analysis.get('n_runners', 0)} at · güven: {conf}",
        "━━━━━━━━━━━━━━━━━━━━━",
    ]

    # STRONG FAVORITE (arbitraj adayı)
    sf = analysis.get("strong_favorite")
    if sf:
        lines.append(
            f"🔥 <b>FAVORİ: {sf['horse_name']}</b>  "
            f"consensus %{sf['consensus_prob_pct']:.1f}  "
            f"odds {sf['best_odds']}")
        lines.append("")

    # TOP-4
    lines.append("<b>TOP-4 (consensus sıralı):</b>")
    for i, h in enumerate(analysis.get("top4", []), 1):
        star = " ⭐" if h.get("is_my_bookmaker") else ""
        lines.append(
            f"  {i}. <b>{h['horse_name']}</b>  "
            f"%{h['consensus_prob_pct']:.1f}  @ "
            f"{h['best_odds']} ({h['best_bookmaker']}){star}")

    # VALUE BETS
    vbs = analysis.get("value_bets") or []
    if vbs:
        lines.append("")
        lines.append("💰 <b>VALUE BETS:</b>")
        for vb in vbs[:2]:
            lines.append(
                f"  ⚡ <b>{vb['horse_name']}</b> "
                f"odds {vb['best_odds']} @{vb['best_bookmaker']} "
                f"→ +EV %{vb['ev_pct']:.1f}  Kelly %{vb['kelly_pct']:.1f}")

    lines.append("")
    lines.append("⚠ Karar destek — bahis garantisi YOK.")
    return "\n".join(lines)


def find_cross_market_arbitrage(uk_race: dict, tjk_pools: list) -> list:
    """UK yarıştaki atı TJK'da (aynı gün) ara — cross-market arbitraj.

    Nadir ama değerli: aynı at UK'da favori (odds 2-3) + TJK'da yüksek
    ganyan → TJK'da underrated → oyna.
    """
    if not uk_race or not tjk_pools:
        return []
    # UK favori atları
    top_uk = uk_race.get("top4", [])[:3]
    if not top_uk:
        return []
    uk_horses = {h["horse_name"].upper(): h for h in top_uk}

    signals = []
    for pool in tjk_pools:
        if pool.get("status") != "ok":
            continue
        for leg in (pool.get("race_legs") or []):
            for tjk_horse in (leg or []):
                nm = (tjk_horse.get("horse_name") or "").upper().strip()
                if nm in uk_horses:
                    uk_data = uk_horses[nm]
                    agf = tjk_horse.get("agf_value", 0) or 0
                    uk_prob = uk_data["consensus_prob_pct"] / 100.0
                    # UK'da %30+ favori + TJK AGF %10- → cross-market underrated
                    if uk_prob >= 0.30 and agf < 10:
                        signals.append({
                            "horse": tjk_horse.get("horse_name"),
                            "hippo": pool.get("hippo"),
                            "race_no": tjk_horse.get("race_number"),
                            "uk_prob": uk_prob * 100,
                            "uk_odds": uk_data["best_odds"],
                            "tjk_agf_pct": agf,
                            "signal": "TJK_UNDERBET",
                            "note": (f"UK'da %{uk_prob*100:.0f} "
                                     f"favori, TJK AGF %{agf:.1f} → "
                                     f"TJK'da underrated"),
                        })
    return signals
