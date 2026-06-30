"""RacingAPI value betting — bookmaker consensus + arbitrage detection.

Berkay (2026-06-30): 'racing api ile para yapacak yapı kur'.

Strateji (model-free, matematiksel +EV):
  1) RacingAPI'den UK/FR/US racecards çek (multi-bookmaker odds)
  2) Her at için BOOKMAKER CONSENSUS = trimmed mean of implied probs
  3) En yüksek bookmaker odd'unun implied prob'u VS consensus karşılaştır
  4) En yüksek odd << consensus prob → mispriced bookmaker → VALUE
  5) Kelly criterion ile önerilen stake fraction

NOT: V9.5 TR-spesifik features ile eğitildi → UK/FR atlarında accuracy
düşük (cross-domain transfer zayıf). Bu yüzden MODEL-FREE consensus
yaklaşımı: bookmaker'ların kendi consensus'u fair prob, outlier =
mispriced.

Telegram alert: T-30/-15/-5 öncesi yarışlar için +EV ≥ X% atlar.

API
---
- find_value_bets(racecard, min_ev_pct=5.0, min_bookmakers=4)
    → list of {horse, best_odds, consensus_prob, ev_pct, kelly_pct, ...}
- consensus_fair_prob(odds_list) → trimmed mean
- format_value_bet_telegram(value_bets, race_meta) → kompakt mesaj
"""
from __future__ import annotations

import logging
from typing import Iterable, Optional

logger = logging.getLogger(__name__)


def _trimmed_mean(values: list[float], trim_pct: float = 0.1) -> float:
    """Outlier'ları (en üst+en alt %trim_pct) at, mean al."""
    if not values:
        return 0.0
    if len(values) < 3:
        return sum(values) / len(values)
    sorted_v = sorted(values)
    n_trim = max(1, int(len(sorted_v) * trim_pct))
    trimmed = sorted_v[n_trim:-n_trim] if len(sorted_v) > 2 * n_trim else sorted_v
    return sum(trimmed) / len(trimmed) if trimmed else 0.0


def consensus_fair_prob(odds_list: list[float],
                         trim_pct: float = 0.1) -> Optional[float]:
    """Multiple bookmaker decimal odds → consensus fair probability.

    Implied prob = 1 / decimal_odds. Outlier trimmed mean.

    Args:
        odds_list: [4.5, 4.2, 4.0, 4.8, 3.9, ...] decimal odds
        trim_pct: %10 default — en uç değerleri at

    Returns: fair_prob ∈ (0, 1) veya None (yetersiz veri)
    """
    if len(odds_list) < 3:
        return None
    implieds = [1.0 / o for o in odds_list if o > 1.0]
    if len(implieds) < 3:
        return None
    return _trimmed_mean(implieds, trim_pct=trim_pct)


def kelly_fraction(decimal_odds: float, fair_prob: float) -> float:
    """Kelly criterion: optimal stake fraction.

    f* = (b·p - q) / b   where b=odds-1, p=fair_prob, q=1-p
    Negative → no bet.
    """
    if decimal_odds <= 1.0:
        return 0.0
    b = decimal_odds - 1.0
    return max(0.0, (b * fair_prob - (1 - fair_prob)) / b)


def extract_runner_odds(runner: dict) -> dict[str, float]:
    """RacingAPI runner dict → {bookmaker: decimal_odds}.

    RacingAPI 'odds' field formati esnek; çeşitli formatları destekle.
    """
    out = {}
    odds_data = runner.get("odds") or runner.get("prices") or []
    if isinstance(odds_data, list):
        for item in odds_data:
            if not isinstance(item, dict):
                continue
            bm = (item.get("bookmaker") or item.get("bookie")
                  or item.get("name") or "?")
            d = (item.get("decimal") or item.get("price")
                 or item.get("odds"))
            if isinstance(d, (int, float)) and d > 1.0:
                out[str(bm)] = float(d)
            elif isinstance(d, str):
                # Fractional ex: "7/2" → 4.5
                try:
                    if "/" in d:
                        a, b = d.split("/")
                        out[str(bm)] = 1.0 + float(a) / float(b)
                except Exception:
                    pass
    elif isinstance(odds_data, dict):
        for bm, d in odds_data.items():
            if isinstance(d, (int, float)) and d > 1.0:
                out[str(bm)] = float(d)
    return out


def find_value_bets(racecard: dict, min_ev_pct: float = 5.0,
                    min_bookmakers: int = 4,
                    min_odds: float = 1.5,
                    max_odds: float = 20.0,
                    my_bookmakers: Optional[set[str]] = None) -> list[dict]:
    """
    my_bookmakers: ['coral', 'ladbrokes'] → SADECE bu bookmaker'lar outlier
                   verdiğinde value bet listele (kullanıcı bahis yapabilir)
                   None → tüm bookmaker'lar
    """
    """Bir yarış için value bet listesi (consensus-based, model-free).

    Args:
        racecard: RacingAPI race dict ({course, off_time, runners: [...]})
        min_ev_pct: minimum +EV yüzdesi (default %5)
        min_bookmakers: at için en az kaç bookmaker odd'u gerek
        min_odds / max_odds: değerlendirilecek odds aralığı

    Returns: sıralı (en yüksek EV önce) value bet list:
        [{horse, best_odds, best_bm, consensus_prob, implied_prob,
          ev_pct, kelly_pct, n_bookmakers}, ...]
    """
    value_bets = []
    runners = (racecard.get("runners") or racecard.get("horses")
               or [])
    for runner in runners:
        odds_dict = extract_runner_odds(runner)
        if len(odds_dict) < min_bookmakers:
            continue
        # Eğer kullanıcı kendi bookmaker'ını belirttiyse: sadece bunlar
        # outlier (best) ise alert gönder
        if my_bookmakers:
            my_odds = {bm: o for bm, o in odds_dict.items()
                       if any(my_name.lower() in bm.lower()
                              for my_name in my_bookmakers)}
            if not my_odds:
                continue
            best_bm, best_odds = max(my_odds.items(), key=lambda x: x[1])
        else:
            best_bm, best_odds = max(odds_dict.items(), key=lambda x: x[1])
        if not (min_odds <= best_odds <= max_odds):
            continue
        # Consensus (best hariç tutalım — outlier kontaminasyonu önle)
        non_best = [o for bm, o in odds_dict.items() if bm != best_bm]
        consensus_p = consensus_fair_prob(non_best)
        if consensus_p is None:
            continue
        implied_p = 1.0 / best_odds
        # Value: consensus_p ne kadar büyük implied_p'den
        if consensus_p <= implied_p:
            continue
        ev = consensus_p * (best_odds - 1) - (1 - consensus_p)
        ev_pct = ev * 100
        if ev_pct < min_ev_pct:
            continue
        kelly = kelly_fraction(best_odds, consensus_p) * 100
        value_bets.append({
            "horse_name": (runner.get("name") or runner.get("horse")
                           or "?"),
            "horse_id": runner.get("horse_id") or runner.get("id"),
            "best_odds": round(best_odds, 2),
            "best_bookmaker": best_bm,
            "consensus_prob_pct": round(consensus_p * 100, 2),
            "implied_prob_pct": round(implied_p * 100, 2),
            "ev_pct": round(ev_pct, 2),
            "kelly_pct": round(kelly, 2),
            "n_bookmakers": len(odds_dict),
        })
    return sorted(value_bets, key=lambda x: -x["ev_pct"])


def fetch_today_value_alerts(min_ev_pct: float = 5.0,
                              regions: tuple = ("gb", "ire", "fr"),
                              hours_ahead: int = 2,
                              my_bookmakers: Optional[list[str]] = None) -> list[dict]:
    """RacingAPI'den bugünkü yarışları çek, value bet alarmları üret.

    Returns: [{race_meta, value_bets, off_time, course}, ...]
    """
    try:
        from forecast.sources.theracingapi import RacingAPIClient
    except Exception as exc:
        logger.warning(f"RacingAPI import fail: {exc}")
        return []
    client = RacingAPIClient.from_env()
    if not client.enabled:
        logger.warning("RacingAPI credentials yok (TJK_RACING_API_USER/PASS)")
        return []

    alerts = []
    for region in regions:
        try:
            cards = client.racecards_today(region=region) or []
        except Exception as exc:
            logger.debug(f"racecards {region}: {exc}")
            continue
        for card in cards:
            races = card.get("races") or [card]  # bazı format'larda flat
            for race in races:
                # Skip past races (off_time geçmiş)
                bets = find_value_bets(
                    race, min_ev_pct=min_ev_pct,
                    my_bookmakers=(set(my_bookmakers)
                                    if my_bookmakers else None))
                if not bets:
                    continue
                alerts.append({
                    "course": race.get("course") or card.get("course")
                              or "?",
                    "off_time": race.get("off_time") or race.get("time"),
                    "race_id": race.get("race_id") or race.get("id"),
                    "region": region.upper(),
                    "value_bets": bets,
                    "n_runners": len(race.get("runners")
                                      or race.get("horses") or []),
                })
    return alerts


def format_value_bet_telegram(alert: dict) -> str:
    """Bir yarış için Telegram-friendly value bet mesajı."""
    lines = []
    course = alert.get("course", "?")
    region = alert.get("region", "?")
    off = alert.get("off_time", "?")
    lines.append(f"💰 <b>VALUE BET · {region} {course}</b>  ({off})")
    lines.append("━━━━━━━━━━━━━━━━━━━━━")
    for i, vb in enumerate(alert.get("value_bets", [])[:3], 1):
        lines.append(
            f"  {i}. <b>{vb['horse_name']}</b>  "
            f"odds {vb['best_odds']} @{vb['best_bookmaker']}")
        lines.append(
            f"     consensus %{vb['consensus_prob_pct']} vs "
            f"implied %{vb['implied_prob_pct']}  "
            f"→ <b>+EV %{vb['ev_pct']}</b>")
        lines.append(
            f"     Kelly %{vb['kelly_pct']:.1f} ({vb['n_bookmakers']} bm)")
    lines.append("")
    lines.append("⚠ Karar destek aracı — bahis garantisi YOK.")
    return "\n".join(lines)


def format_alerts_summary(alerts: list[dict]) -> str:
    """Çoklu yarış için tek özet mesajı."""
    if not alerts:
        return ""
    n_races = len(alerts)
    n_bets = sum(len(a.get("value_bets") or []) for a in alerts)
    lines = [f"💰 <b>RACING API VALUE ALERTS · {n_races} yarış, "
             f"{n_bets} bet</b>"]
    for alert in alerts[:10]:
        course = alert.get("course", "?")
        region = alert.get("region", "?")
        off = (alert.get("off_time") or "")[-8:]  # HH:MM:SS
        top_bet = (alert.get("value_bets") or [{}])[0]
        if top_bet:
            lines.append(
                f"  {region} {course} ({off}): "
                f"<b>{top_bet.get('horse_name', '?')}</b> "
                f"@{top_bet.get('best_odds', 0)} "
                f"(+EV %{top_bet.get('ev_pct', 0):.1f})")
    return "\n".join(lines)
