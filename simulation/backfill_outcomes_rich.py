"""Phase 5.5 PART E — zengin outcome enrichment (TJK Sehir, per-finisher).

backfill_outcomes.py kazanan+at_no veriyordu; bu modül HER finisher için age/weight/jockey
+ koşu mesafesi çıkarır (TR public-bias hipotez testleri için). Read-only, politeness 2s.
Kolonlar: Forma|S|At İsmi|Yaş|Orijin|Sıklet|Jokey (Phase 5.2.5 doğrulandı).
"""
from __future__ import annotations

import json
import os
import re
import sys
import time

from bs4 import BeautifulSoup

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
from simulation.backfill_outcomes import BASE, _get, _sehir_links, _AT_NO  # noqa: E402

CACHE = os.path.join(_REPO, "data", "backfill", "outcomes_rich")
_AGE = re.compile(r"(\d+)")
_DIST = re.compile(r"(\d{3,4})\s*(?:m|metre|ÇİM|KUM|Çim|Kum)", re.I)


def _num(s):
    m = _AGE.search(s or "")
    return int(m.group(1)) if m else None


def _weight(s):
    s = (s or "").replace(",", ".")
    m = re.search(r"(\d+(?:\.\d+)?)", s)
    return float(m.group(1)) if m else None


def _parse_rich(link):
    txt = _get(BASE + link)
    m = re.search(r"SehirAdi=([^&]+)", link)
    from urllib.parse import unquote
    sehir = unquote((m.group(1) if m else "?").replace("+", " "))
    out = {"hippodrome": sehir, "kosular": {}}
    if not txt:
        return out
    soup = BeautifulSoup(txt, "html.parser")
    for i, tbl in enumerate(soup.find_all("table"), start=1):
        # mesafe: tablo öncesi metinde ara
        dist = None
        prev = tbl.find_previous(string=_DIST)
        if prev:
            dm = _DIST.search(prev)
            dist = int(dm.group(1)) if dm else None
        finishers = []
        for tr in tbl.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            mt = _AT_NO.search(cells[2])
            if not mt:
                continue
            # Orijin (Baba-Anne) = cell[4]; baba/sire = "-" öncesi (breeding-connection proxy)
            sire = None
            if len(cells) > 4 and cells[4]:
                sire = re.split(r"\s*[-/]\s*", cells[4])[0].strip() or None
            finishers.append({
                "at_no": int(mt.group(1)),
                "S": _num(cells[1]),                       # finish position
                "name": re.sub(r"\(\d+\).*", "", cells[2]).strip(),
                "age": _num(cells[3]) if len(cells) > 3 else None,
                "sire": sire,                              # baba (PART 6 connection proxy)
                "weight": _weight(cells[5]) if len(cells) > 5 else None,
                "jockey": cells[6] if len(cells) > 6 else None,
            })
        if finishers:
            out["kosular"][i] = {"distance": dist, "finishers": finishers}
    return out


def fetch_rich(date_iso):
    y, m, d = date_iso.split("-")
    links = _sehir_links(f"{d}/{m}/{y}")
    out = {"date": date_iso, "hippodromes": []}
    for l in links:
        time.sleep(2.0)
        p = _parse_rich(l)
        if p["kosular"]:
            out["hippodromes"].append(p)
    out["ok"] = bool(out["hippodromes"])
    return out


def save(day):
    if not day.get("ok"):
        return None
    os.makedirs(CACHE, exist_ok=True)
    p = os.path.join(CACHE, f"{day['date']}.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False)
    return p


if __name__ == "__main__":
    import glob
    dates = sorted(os.path.basename(x) for x in glob.glob(
        os.path.join(_REPO, "data", "backfill", "agftahmin", "*")) if os.path.isdir(x))
    ok = 0
    for dt in dates:
        if os.path.exists(os.path.join(CACHE, f"{dt}.json")):
            ok += 1
            continue
        day = fetch_rich(dt)
        if save(day):
            ok += 1
            nf = sum(len(k["finishers"]) for h in day["hippodromes"] for k in h["kosular"].values())
            print(f"[ok] {dt} hip={len(day['hippodromes'])} finishers={nf}")
        else:
            print(f"[FAIL] {dt}")
    print(f"=== DONE {ok}/{len(dates)}")
