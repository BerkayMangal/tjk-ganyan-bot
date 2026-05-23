"""Phase 5.2.5 PART C — AGF dataset ↔ outcome join → won_flag.

calibration_dataset.csv (AGF, won_flag boş) + outcomes/ (TJK kazanan + at_no seti) →
ayak↔koşu eşleştirme (at-seti Jaccard, varsayım yok) → calibration_dataset_complete.csv.
"""
from __future__ import annotations

import csv
import glob
import json
import os
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset.csv")
OUTCOMES_DIR = os.path.join(_REPO, "data", "backfill", "outcomes")
OUT_CSV = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
JACCARD_MIN = 0.5  # ayak↔koşu eşleşme eşiği (yanlış eşleşmeyi at)


_TR_FOLD = str.maketrans("İıÇçĞğÖöŞşÜü", "iiccggoossuu")


def _norm_hip(s: str) -> str:
    return (s or "").strip().translate(_TR_FOLD).lower()


def _load_outcomes() -> dict:
    """{date: {norm_hip: {kosu_no(int): {'winner': int, 'at_nos': set}}}}"""
    out: dict = {}
    for p in glob.glob(os.path.join(OUTCOMES_DIR, "*", "outcomes.json")):
        day = json.load(open(p, encoding="utf-8"))
        dmap = out.setdefault(day["date"], {})
        for h in day.get("hippodromes", []):
            kos = {}
            for kno, info in h.get("kosular", {}).items():
                kos[int(kno)] = {"winner": info["winner"], "at_nos": set(info["at_nos"])}
            dmap[_norm_hip(h["hippodrome"])] = kos
    return out


def _best_kosu(ayak_at_set: set, kosular: dict):
    """En yüksek Jaccard'lı koşu (winner, score). Eşik altı → (None, 0)."""
    best, best_s = None, 0.0
    for kno, info in kosular.items():
        inter = len(ayak_at_set & info["at_nos"])
        union = len(ayak_at_set | info["at_nos"])
        s = inter / union if union else 0.0
        if s > best_s:
            best, best_s = info, s
    return (best, best_s) if best_s >= JACCARD_MIN else (None, best_s)


def join() -> dict:
    rows = list(csv.DictReader(open(DATASET, encoding="utf-8")))
    outcomes = _load_outcomes()

    # ayak grupları: (date,hip,altili,ayak) → at_no seti
    groups: dict = defaultdict(set)
    for r in rows:
        groups[(r["date"], r["hippodrome"], r["altili_no"], r["ayak"])].add(int(r["at_no"]))

    # her ayağı en iyi koşuya bağla → winner
    ayak_winner: dict = {}
    matched_ayak = 0
    for key, at_set in groups.items():
        date, hip, _, _ = key
        kosular = outcomes.get(date, {}).get(_norm_hip(hip))
        if not kosular:
            continue
        info, score = _best_kosu(at_set, kosular)
        if info:
            ayak_winner[key] = info["winner"]
            matched_ayak += 1

    # won_flag yaz
    filled = 0
    for r in rows:
        key = (r["date"], r["hippodrome"], r["altili_no"], r["ayak"])
        if key in ayak_winner:
            r["won_flag"] = "1" if int(r["at_no"]) == ayak_winner[key] else "0"
            filled += 1
        else:
            r["won_flag"] = ""

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=rows[0].keys())
        w.writeheader()
        w.writerows(rows)

    return {
        "rows_total": len(rows),
        "rows_labeled": filled,
        "ayak_total": len(groups),
        "ayak_matched": matched_ayak,
        "out_csv": OUT_CSV,
    }


if __name__ == "__main__":
    print(json.dumps(join(), ensure_ascii=False, indent=2))
