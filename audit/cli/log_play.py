"""Phase 5.6 PART 10 — Berkay manuel feedback CLI (sistem → öğrenme).

Berkay "ne oynadığını" söyler → data/play_log/{date}.jsonl. weekly_calibration_report Bölüm B
bunu okur. Sistem bot değil — bu sadece KAYIT (Berkay karar verici).

Örnek:
  python audit/cli/log_play.py --date 2026-05-23 --race 14:00 --strategy kangal \
      --cost 4800 --played true --hit false --notes "Ayak 5 banker yerine 2 at koydum"
"""
from __future__ import annotations

import argparse
import json
import os
from datetime import date

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
LOG_DIR = os.path.join(_REPO, "data", "play_log")


def _b(v):
    return str(v).strip().lower() in ("1", "true", "yes", "evet", "e", "y")


def main():
    ap = argparse.ArgumentParser(description="Berkay manuel oyun feedback log")
    ap.add_argument("--date", default=date.today().isoformat())
    ap.add_argument("--race", default="", help="saat/altılı id, ör. 14:00 veya Ankara#1")
    ap.add_argument("--strategy", default="", help="sistemin önerisi: kangal|favori_yikma|tam_sistem|pas")
    ap.add_argument("--cost", type=float, default=0.0, help="gerçek harcanan TL")
    ap.add_argument("--played", default="true", help="oynadın mı (true/false)")
    ap.add_argument("--hit", default="", help="tuttu mu (true/false/boş)")
    ap.add_argument("--payout", type=float, default=0.0)
    ap.add_argument("--modifications", default="", help="sistemden sapma (ör. banker→2at)")
    ap.add_argument("--notes", default="")
    a = ap.parse_args()

    rec = {"date": a.date, "race": a.race, "strategy_suggested": a.strategy,
           "played": _b(a.played), "actual_cost": a.cost,
           "hit": (_b(a.hit) if a.hit != "" else None), "payout": a.payout,
           "modifications": a.modifications, "notes": a.notes}
    os.makedirs(LOG_DIR, exist_ok=True)
    path = os.path.join(LOG_DIR, f"{a.date}.jsonl")
    with open(path, "a", encoding="utf-8") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    print(f"✓ kaydedildi → {path}")
    print(f"  {json.dumps(rec, ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
