"""Online Elo update — retro'da her koşu sonucu → bundle Elo güncelle.

Berkay (2026-07-01): 'oldukça pushla canlıya, model ona göre çıktı versin'.

Full retrain gerektirmez — bundle içindeki v11_elo_final ve v11_elo_timeline
ile v11_h2h_dates in-place güncellenir. Ertesi gün canlıda güncel Elo kullanılır.

Mantık:
  1) Verilen tarih için outcomes_rich çek
  2) Kronolojik yarış işle (aynı tarih içinde kosu_no sırası)
  3) Her koşuda winner-loser pair → Elo update
  4) Snapshot timeline: (date, elo_before) → EKLE
  5) h2h_dates[(winner, loser)] → EKLE
  6) Bundle'ı yaz (v11_ensemble.json)

Çift-yazım önleme: last_update_date > target_date ise skip.

Usage:
  python -m model.v11.online_elo_update 2026-07-01
"""
from __future__ import annotations

import json
import logging
import sys
from datetime import date
from itertools import combinations
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("v11_elo_online")

ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(ROOT))

BUNDLE_PATH = ROOT / "model" / "v11" / "trained" / "v11_ensemble.json"
OUTCOMES_DIR = ROOT / "data" / "backfill" / "outcomes_rich"

INIT_ELO = 1500.0
K_BASE = 24.0


def _load_bundle() -> Optional[dict]:
    if not BUNDLE_PATH.exists():
        log.error(f"bundle yok: {BUNDLE_PATH}")
        return None
    with open(BUNDLE_PATH, encoding="utf-8") as f:
        return json.load(f)


def _save_bundle(b: dict):
    with open(BUNDLE_PATH, "w", encoding="utf-8") as f:
        json.dump(b, f, ensure_ascii=False)


def _load_outcomes_for_date(target_date: str) -> list[dict]:
    p = OUTCOMES_DIR / f"{target_date}.json"
    if not p.exists():
        log.warning(f"outcomes yok: {target_date}")
        return []
    with open(p) as f:
        d = json.load(f)
    records = []
    for hip in (d.get("hippodromes") or []):
        hippo = hip.get("hippodrome") or ""
        for k_id, kv in (hip.get("kosular") or {}).items():
            try:
                kno = int(k_id)
            except Exception:
                continue
            for fin in (kv.get("finishers") or []):
                records.append({
                    "date": target_date, "hippo": hippo,
                    "kosu_no": kno,
                    "name": fin.get("name"),
                    "finish": fin.get("S"),
                    "at_no": fin.get("at_no"),
                })
    return records


def update_elo(target_date: str, dry_run: bool = False) -> dict:
    """Online Elo update: bundle içindeki Elo'yu target_date verileri ile büyüt."""
    bundle = _load_bundle()
    if bundle is None:
        return {"status": "no_bundle"}

    # Idempotency: aynı tarih iki kez update ederse Elo bozulur
    last_upd = bundle.get("last_online_elo_update")
    if last_upd and target_date <= last_upd:
        return {"status": "already_updated",
                 "date": target_date, "last_update": last_upd}

    records = _load_outcomes_for_date(target_date)
    if not records:
        return {"status": "no_outcomes", "date": target_date}

    # Group by race
    from collections import defaultdict
    race_groups = defaultdict(list)
    for r in records:
        if r.get("finish") is None or not r.get("name"):
            continue
        race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)

    if not race_groups:
        return {"status": "no_valid_races", "date": target_date}

    # Current state
    elo_final = dict(bundle.get("v11_elo_final") or {})
    timeline = {k: list(v) for k, v in
                 (bundle.get("v11_elo_timeline") or {}).items()}
    h2h_dates_str = bundle.get("v11_h2h_dates") or {}
    h2h_dates = {}
    for k, v in h2h_dates_str.items():
        if "||" in k:
            a, b = k.split("||", 1)
            h2h_dates[(a, b)] = list(v)

    n_races_processed = 0
    n_pairs = 0
    new_horses = 0
    ordered_races = sorted(race_groups.items(),
                            key=lambda kv: (kv[0][0], kv[0][2]))

    for (dt, _hippo, _kosu), runners in ordered_races:
        finished = [r for r in runners
                    if isinstance(r.get("finish"), int)]
        if len(finished) < 2:
            continue
        # Snapshot BEFORE update
        for r in finished:
            nm = r["name"]
            if nm not in elo_final:
                elo_final[nm] = INIT_ELO
                new_horses += 1
            timeline.setdefault(nm, []).append(
                [dt, elo_final[nm]])
        # Pairwise updates
        for a, b in combinations(finished, 2):
            fa, fb = a["finish"], b["finish"]
            if fa == fb:
                continue
            winner = a if fa < fb else b
            loser = b if fa < fb else a
            wn, ln = winner["name"], loser["name"]
            ew = 1.0 / (1.0 + 10 ** (
                (elo_final[ln] - elo_final[wn]) / 400.0))
            elo_final[wn] = elo_final[wn] + K_BASE * (1.0 - ew)
            elo_final[ln] = elo_final[ln] - K_BASE * (1.0 - ew)
            h2h_dates.setdefault((wn, ln), []).append(dt)
            n_pairs += 1
        n_races_processed += 1

    if dry_run:
        return {
            "status": "dry_run", "date": target_date,
            "n_races": n_races_processed,
            "n_pairs": n_pairs,
            "new_horses": new_horses,
            "elo_size": len(elo_final),
        }

    # Save back
    bundle["v11_elo_final"] = elo_final
    bundle["v11_elo_timeline"] = timeline
    bundle["v11_h2h_dates"] = {
        f"{a}||{b}": sorted(v) for (a, b), v in h2h_dates.items()}
    bundle["last_online_elo_update"] = target_date
    _save_bundle(bundle)

    log.info(f"[online-elo] {target_date}: "
             f"{n_races_processed} koşu, {n_pairs} pair, "
             f"{new_horses} yeni at, elo_size={len(elo_final)}")
    return {
        "status": "ok", "date": target_date,
        "n_races": n_races_processed,
        "n_pairs": n_pairs,
        "new_horses": new_horses,
        "elo_size": len(elo_final),
    }


if __name__ == "__main__":
    target = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()
    dry = "--dry" in sys.argv
    r = update_elo(target, dry_run=dry)
    print(json.dumps(r, indent=2, ensure_ascii=False))
