"""RacingAPI value betting backtest framework.

Berkay (2026-06-30): 'racing api ile para yapacak yapı kur'.

Mantık:
  1. results endpoint'inden geçmiş yarış sonuçları çek
  2. Her yarışta value bet finder uygula (consensus-based)
  3. Gerçek finish ile karşılaştır → hit rate
  4. ROI hesapla (gerçek stake × payout)

NOT: RacingAPI'nin historical odds endpoint'i sınırlı olabilir
(genelde son N gün). Eğer yoksa script live racecards üzerinde
test eder, forward-only mod.

Usage:
    python -m audit.racing_api_backtest --days 7 --min-ev 5.0
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import date, timedelta
from pathlib import Path

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("racing_api_bt")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def backtest_value_bets(days_back: int = 7, min_ev_pct: float = 5.0,
                         min_bookmakers: int = 4,
                         regions: tuple = ("gb", "ire", "fr")):
    """Son N gün için RacingAPI results'tan value bet simülasyonu."""
    from forecast.sources.theracingapi import RacingAPIClient
    from forecast.racing_api_value import find_value_bets

    client = RacingAPIClient.from_env()
    if not client.enabled:
        log.error("Credentials yok (TJK_RACING_API_USER/PASS)")
        return None

    target_dates = [(date.today() - timedelta(days=i)).isoformat()
                    for i in range(days_back)]

    all_bets = []
    n_races_scanned = 0
    for d in target_dates:
        for region in regions:
            try:
                results = client._get(
                    f"/results/today?region_codes={region}",
                    {"date": d}) or {}
                races = results.get("results") or results.get("races") or []
            except Exception as exc:
                log.debug(f"{d} {region}: {exc}")
                continue
            for race in races:
                n_races_scanned += 1
                # Race meta
                runners = (race.get("runners") or race.get("horses")
                           or [])
                if not runners:
                    continue
                bets = find_value_bets(race, min_ev_pct=min_ev_pct,
                                        min_bookmakers=min_bookmakers)
                if not bets:
                    continue
                # Actual winner / top4
                winner_id = None
                top4_ids = set()
                for r in runners:
                    pos = r.get("position") or r.get("S")
                    if pos == 1:
                        winner_id = r.get("horse_id") or r.get("id")
                    if isinstance(pos, int) and pos <= 4:
                        top4_ids.add(r.get("horse_id") or r.get("id"))
                for vb in bets:
                    hid = vb.get("horse_id")
                    vb["won"] = (hid == winner_id) if winner_id else None
                    vb["top4"] = (hid in top4_ids) if top4_ids else None
                    vb["race_id"] = race.get("race_id") or race.get("id")
                    vb["date"] = d
                    vb["region"] = region
                    all_bets.append(vb)

    log.info(f"Scanned {n_races_scanned} races over {days_back} days")
    log.info(f"Found {len(all_bets)} value bets (min_ev={min_ev_pct}%)")

    if not all_bets:
        log.warning("Veri yok — RacingAPI results endpoint historical odds "
                    "vermiyor olabilir. Forward-only mod gerek.")
        return None

    # ROI hesap
    matched = [b for b in all_bets if b.get("won") is not None]
    if matched:
        total_staked = len(matched)
        wins = sum(1 for b in matched if b["won"])
        total_return = sum(b["best_odds"] for b in matched if b["won"])
        roi = (total_return - total_staked) / total_staked * 100
        hit_rate = wins / len(matched) * 100
        log.info(f"\n=== ROI ANALYSIS ({len(matched)} matched bets) ===")
        log.info(f"  Hit rate: {hit_rate:.2f}% ({wins}/{len(matched)})")
        log.info(f"  Total staked: {total_staked} units")
        log.info(f"  Total return: {total_return:.2f} units")
        log.info(f"  ROI: {roi:+.2f}%")
        # EV ortalama
        avg_ev = sum(b["ev_pct"] for b in matched) / len(matched)
        log.info(f"  Avg expected EV: +{avg_ev:.2f}%")
        # Kalibrasyon: tahmin vs gerçek
        actual_p = wins / len(matched)
        avg_pred_p = sum(b["consensus_prob_pct"] / 100
                          for b in matched) / len(matched)
        log.info(f"  Pred prob avg: {avg_pred_p*100:.2f}% vs actual: "
                 f"{actual_p*100:.2f}%")
    else:
        log.warning("Hiç matched bet yok — finish position eksik")

    # Save
    out_path = ROOT / "audit" / "reports" / "racing_api_backtest.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w") as f:
        json.dump({
            "n_races_scanned": n_races_scanned,
            "n_value_bets": len(all_bets),
            "n_matched": len(matched),
            "min_ev_pct": min_ev_pct,
            "min_bookmakers": min_bookmakers,
            "regions": list(regions),
            "days_back": days_back,
            "bets": all_bets[:200],  # sample
        }, f, indent=2, ensure_ascii=False)
    log.info(f"saved {out_path}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--days", type=int, default=7)
    parser.add_argument("--min-ev", type=float, default=5.0)
    parser.add_argument("--min-bookmakers", type=int, default=4)
    parser.add_argument("--regions", default="gb,ire,fr")
    args = parser.parse_args()
    regions = tuple(r.strip().lower() for r in args.regions.split(","))
    backtest_value_bets(
        days_back=args.days, min_ev_pct=args.min_ev,
        min_bookmakers=args.min_bookmakers, regions=regions)


if __name__ == "__main__":
    main()
