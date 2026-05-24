"""Phase 5.2 — kalibrasyon veri seti + AGF cross-check.

AGF backfill (agftahmin) → satırlar. outcome (won_flag) kaynağı BLOKE (PART A) →
won_flag=None (forward'da retro/bet_diary ile dolacak). Yani şu an AGF-ONLY dataset
(label'sız) + agftahmin↔agftablosu kalite cross-check.

cross_check: agftahmin'in gerçek TJK AGF mi olduğunu kanıtlar (bugün, iki kaynak da var).
"""
from __future__ import annotations

import csv
import os
import re
import sys
from datetime import date

import requests
from bs4 import BeautifulSoup

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from simulation.backfill_agf_external import CACHE_DIR as AGF_CACHE  # noqa: E402

OUT_CSV = os.path.join(_REPO, "data", "backfill", "calibration_dataset.csv")
HDR = {"User-Agent": "Mozilla/5.0 Chrome/120", "Accept-Encoding": "gzip, deflate"}
# Hem agftahmin (AGF Tahmin) hem agftablosu (AGF Tablosu) başlığını yakala
_HEAD = re.compile(r"(\d{4}-\d{2}-\d{2})?.*?(\d{1,2}:\d{2})\s+(.+?)\s+AGF\s+(?:Tahmin|Tablosu)\s+(\d+)",
                   re.IGNORECASE)
_AYAK = re.compile(r"(\d)\.\s*AYAK", re.IGNORECASE)
_AT = re.compile(r"(\d+)\s*\(%\s?(\d{1,2}[.,]\d{1,2})\)")


def _parse_at_level(html: str, only_hippo_substr=None) -> dict:
    """Genel at-level parse (agftahmin VEYA agftablosu). Returns {(hippo,altili):{ayak:{at_no:agf}}}."""
    soup = BeautifulSoup(html, "html.parser")
    out, cur = {}, None
    for el in soup.find_all(["h3", "table"]):
        if el.name == "h3":
            m = _HEAD.search(el.get_text(strip=True))
            if m:
                hippo, alt = m.group(3).strip(), int(m.group(4))
                if only_hippo_substr and only_hippo_substr.lower() not in hippo.lower():
                    cur = None
                    continue
                cur = (hippo, alt)
                out.setdefault(cur, {})
            else:
                cur = None
        elif el.name == "table" and cur is not None:
            ayak = None
            for tr in el.find_all("tr"):
                t = tr.get_text(" ", strip=True)
                ma = _AYAK.search(t)
                if ma:
                    ayak = int(ma.group(1)); out[cur].setdefault(ayak, {}); continue
                mt = _AT.search(t)
                if mt and ayak is not None:
                    out[cur][ayak][int(mt.group(1))] = float(mt.group(2).replace(",", "."))
    return out


def cross_check_today() -> dict:
    """agftahmin vs agftablosu (bugün) AGF% — ortak (hippo,altili,ayak,at) Pearson + MAE."""
    today = date.today().isoformat()
    a = _parse_at_level(requests.get(f"https://www.agftahmin.com/agf-tablosu/{today}",
                                     headers=HDR, timeout=20).text)
    b = _parse_at_level(requests.get("https://www.agftablosu.com/agf-tablosu",
                                     headers=HDR, timeout=20).text)
    pairs = []
    for key in set(a) & set(b):
        for ayak in set(a[key]) & set(b[key]):
            for at_no in set(a[key][ayak]) & set(b[key][ayak]):
                pairs.append((a[key][ayak][at_no], b[key][ayak][at_no]))
    if len(pairs) < 5:
        return {"n_pairs": len(pairs), "verdict": "INSUFFICIENT_OVERLAP",
                "common_altilis": len(set(a) & set(b))}
    xs = [p[0] for p in pairs]; ys = [p[1] for p in pairs]
    n = len(pairs)
    mx, my = sum(xs) / n, sum(ys) / n
    cov = sum((x - mx) * (y - my) for x, y in pairs)
    vx = sum((x - mx) ** 2 for x in xs) ** 0.5
    vy = sum((y - my) ** 2 for y in ys) ** 0.5
    pearson = cov / (vx * vy) if vx and vy else 0.0
    mae = sum(abs(x - y) for x, y in pairs) / n
    verdict = "OK" if pearson > 0.95 else ("WARN" if pearson > 0.85 else "FAIL")
    return {"n_pairs": n, "pearson": round(pearson, 4), "mae": round(mae, 3),
            "verdict": verdict, "common_altilis": len(set(a) & set(b))}


def build_agf_only_dataset() -> dict:
    """agftahmin cache → CSV satırları (won_flag=None — outcome BLOKE, forward'da dolacak)."""
    import json
    rows = 0
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["date", "hippodrome", "altili_no", "ayak", "at_no", "agf_pct",
                    "agf_implied_prob", "won_flag"])
        if os.path.isdir(AGF_CACHE):
            for d in sorted(os.listdir(AGF_CACHE)):
                p = os.path.join(AGF_CACHE, d, "agf.json")
                if not os.path.exists(p):
                    continue
                day = json.load(open(p, encoding="utf-8"))
                for alt in day.get("altilis", []):
                    for ayak, horses in alt.get("legs", {}).items():
                        for h in horses:
                            agf = h["agf_pct"]
                            w.writerow([day["date"], alt["hippodrome"], alt["altili_no"], ayak,
                                        h["at_no"], agf, round(agf / 100.0, 4), ""])  # won_flag boş
                            rows += 1
    return {"rows": rows, "path": OUT_CSV}


if __name__ == "__main__":
    import json
    print("cross_check:", json.dumps(cross_check_today(), ensure_ascii=False))
    print("dataset:", json.dumps(build_agf_only_dataset(), ensure_ascii=False))
