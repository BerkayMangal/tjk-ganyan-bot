"""bet_diary outcome backfill — Phase 1E.2 bug fix sonrası geçmiş 34 günü doldur.

Berkay direktifi (2026-06-13): "dediklerinin hepsini sırayla yap" — fix sonrası
data/backfill/outcomes/ klasöründeki gerçek sonuçlarla bet_diary'de eksik
did_we_win alanlarını doldurur. Forward'da yeni gönderim yapmaz, sadece JSONL
update'ler.

Kullanım:
    python audit/88_betdiary_outcome_backfill.py [--dry-run]

Çıktı: per-date stat + toplam updated/wins/losses.
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "dashboard"))

OUTCOMES_DIR = os.path.join(_REPO, "data", "backfill", "outcomes")


def _backfill_to_results(date_str: str):
    """outcomes.json → update_outcomes_for_date format'a dönüştür.

    Varsayım: günün altılısı = TJK koşu listesinin SON 6 koşusu (Phase 12 öncesi
    tek havuz dönemi için doğru). Çoklu havuz günleri (2026-06+) için altılı_no=1
    bağlanır; ikinci havuz kayıtları match etmez (atlanır — bet_diary'de altili_no
    eşleşmiyorsa zaten update_outcomes_for_date pas geçer).
    """
    path = os.path.join(OUTCOMES_DIR, date_str, "outcomes.json")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        data = json.load(f)
    out = []
    for h in (data.get("hippodromes") or []):
        kosular = h.get("kosular") or {}
        if not kosular:
            continue
        try:
            kosu_nums = sorted(int(k) for k in kosular.keys())
        except ValueError:
            continue
        if len(kosu_nums) < 6:
            continue
        altili_kosular = kosu_nums[-6:]
        winners = []
        for leg_idx, kosu_no in enumerate(altili_kosular, 1):
            kw = kosular.get(str(kosu_no)) or {}
            wno = kw.get("winner")
            if wno is None:
                continue
            winners.append({
                "leg_number": leg_idx,
                "horse_number": int(wno),
                "race_number": int(kosu_no),
            })
        if winners:
            out.append({
                "hippodrome": h.get("hippodrome"),
                "altili_no": 1,
                "winners": winners,
            })
    return out


def _iter_dates(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def main(dry_run: bool = False):
    from bet_diary_writer import update_outcomes_for_date

    if not os.path.isdir(OUTCOMES_DIR):
        print(f"FAIL  outcomes dir yok: {OUTCOMES_DIR}")
        sys.exit(1)
    dirs = sorted(d for d in os.listdir(OUTCOMES_DIR)
                   if os.path.isdir(os.path.join(OUTCOMES_DIR, d)))
    if not dirs:
        print("FAIL  outcomes klasörü boş")
        sys.exit(1)

    total = {"records_updated": 0, "wins": 0, "losses": 0, "days": 0, "skipped": 0}
    print(f"backfill başlıyor: {len(dirs)} gün ({dirs[0]} → {dirs[-1]}) · "
          f"dry_run={dry_run}")
    for date_str in dirs:
        try:
            target_dt = date.fromisoformat(date_str)
        except ValueError:
            continue
        results = _backfill_to_results(date_str)
        if not results:
            total["skipped"] += 1
            continue
        if dry_run:
            n_winners = sum(len(r.get("winners") or []) for r in results)
            print(f"  [DRY] {date_str}: {len(results)} hipodrom · {n_winners} winner")
            continue
        rep = update_outcomes_for_date(target_dt, results)
        upd = rep.get("records_updated", 0)
        if upd:
            total["days"] += 1
            total["records_updated"] += upd
            total["wins"] += rep.get("wins", 0)
            total["losses"] += rep.get("losses", 0)
            print(f"  {date_str}: updated={upd:3d} wins={rep.get('wins',0):3d} "
                  f"losses={rep.get('losses',0):3d} errors={len(rep.get('errors') or [])}")
        else:
            total["skipped"] += 1

    print()
    print(f"TOPLAM · {total['days']} gün · {total['records_updated']} kayıt "
          f"güncellendi · wins={total['wins']} losses={total['losses']} "
          f"skipped={total['skipped']}")


if __name__ == "__main__":
    main(dry_run="--dry-run" in sys.argv)
