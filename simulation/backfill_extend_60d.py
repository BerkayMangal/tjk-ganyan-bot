"""Backfill genişlet — 30 günden 60 güne (geçmişe).

backfill_agf_external.fetch_agf_for_date'i tarih başına çağırır,
sonra backfill_outcomes_rich.fetch_rich/save ile outcome'ı doldurur.

Usage:
    python simulation/backfill_extend_60d.py [n_days]
"""
from __future__ import annotations

import os
import sys
import time
from datetime import date, timedelta

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)

from simulation.backfill_agf_external import (
    fetch_agf_for_date, save_day, is_cached,
)
from simulation.backfill_outcomes_rich import (
    fetch_rich, save as save_rich, CACHE as RICH_CACHE,
)


def main(n_extra_days: int = 25):
    """En eski mevcut AGF tarihinden geriye n_extra_days kadar git."""
    agf_dir = os.path.join(ROOT, "data", "backfill", "agftahmin")
    existing = sorted(os.listdir(agf_dir))
    if not existing:
        print("agftahmin boş")
        return
    earliest = date.fromisoformat(existing[0])
    print(f"En eski mevcut: {earliest}, {n_extra_days} gün daha eski "
          f"hedef: {earliest - timedelta(days=n_extra_days)}")
    targets = [(earliest - timedelta(days=i + 1)).isoformat()
               for i in range(n_extra_days)]

    agf_ok = 0
    outcome_ok = 0
    for dt in targets:
        # AGF
        if is_cached(dt):
            agf_ok += 1
        else:
            try:
                day = fetch_agf_for_date(dt)
                if day.get("ok"):
                    save_day(day)
                    agf_ok += 1
                    print(f"  [AGF ok] {dt} altılı={len(day.get('altilis', []))}")
                else:
                    print(f"  [AGF skip] {dt}")
                time.sleep(1.5)
            except Exception as exc:
                print(f"  [AGF FAIL] {dt}: {repr(exc)[:120]}")

        # Outcome rich
        out_path = os.path.join(RICH_CACHE, f"{dt}.json")
        if os.path.exists(out_path):
            outcome_ok += 1
            continue
        try:
            day = fetch_rich(dt)
            if save_rich(day):
                outcome_ok += 1
                nf = sum(len(k["finishers"])
                         for h in day["hippodromes"]
                         for k in h["kosular"].values())
                print(f"  [OUT ok] {dt} hip={len(day['hippodromes'])} "
                      f"finishers={nf}")
            else:
                print(f"  [OUT skip] {dt}")
            time.sleep(1.5)
        except Exception as exc:
            print(f"  [OUT FAIL] {dt}: {repr(exc)[:120]}")

    print(f"\n=== DONE  AGF: {agf_ok}/{len(targets)}  "
          f"Outcome: {outcome_ok}/{len(targets)}")


if __name__ == "__main__":
    n = int(sys.argv[1]) if len(sys.argv) > 1 else 25
    main(n_extra_days=n)
