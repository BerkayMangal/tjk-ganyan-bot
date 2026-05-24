"""Phase 5.1.5/5.2 — Geçmiş AGF backfill (agftahmin.com).

agftahmin.com/agf-tablosu/{YYYY-MM-DD} geçmiş AGF arşivi. Gün-bazlı tek istek tüm
hipodromları verir (verimli: 90 gün = 90 istek). Tablo formatı: "N. AYAK" başlık +
"{at_no} (%{agf_pct})" satırları (agftablosu ile aynı). At İSMİ yok → at_no ile join.

Read-only, prod'a bağlı değil. politeness 1.2s/req. simulation/ altında (backtest aracı).
NOT: agftahmin AGF'si = TJK piyasa AGF'si mi → Phase 5.2 cross-check (PART B) doğrular.
"""
from __future__ import annotations

import json
import os
import re
import time
from typing import Optional

import requests
from bs4 import BeautifulSoup

BASE = "https://www.agftahmin.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Accept-Encoding": "gzip, deflate"}
TR_HIPPO = ("ankara", "istanbul", "i̇stanbul", "izmir", "i̇zmir", "bursa",
            "adana", "kocaeli", "antalya", "sanliurfa", "şanlıurfa", "elaz", "diyarb")
POLITE_SEC = 1.2
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_REPO, "data", "backfill", "agftahmin")

_HEAD_RE = re.compile(r"(\d{4}-\d{2}-\d{2}).*?(\d{1,2}:\d{2})\s+(.+?)\s+AGF\s+Tahmin\s+(\d+)",
                      re.IGNORECASE)
_AYAK_RE = re.compile(r"(\d)\.\s*AYAK", re.IGNORECASE)
_AT_RE = re.compile(r"(\d+)\s*\(%\s?(\d{1,2}[.,]\d{1,2})\)")


def _norm_tr(h: str) -> bool:
    return any(t in (h or "").lower() for t in TR_HIPPO)


def fetch_agf_for_date(date_str: str, only_tr: bool = True, timeout: int = 20,
                       retries: int = 3) -> dict:
    """date_str='YYYY-MM-DD'. Returns {date, source, ok, altilis:[{hippodrome,
    altili_no, time, legs:{ayak:[{at_no, agf_pct}]}}]}. At-level (at_no + AGF%)."""
    out = {"date": date_str, "source": "agftahmin.com", "ok": False, "error": None, "altilis": []}
    html = None
    for attempt in range(retries):
        try:
            r = requests.get(f"{BASE}/agf-tablosu/{date_str}", headers=HDR, timeout=timeout)
            if r.status_code == 200:
                html = r.text
                break
            out["error"] = f"HTTP {r.status_code}"
        except Exception as e:
            out["error"] = repr(e)[:100]
        time.sleep(1.5 * (attempt + 1))  # exponential backoff
    if not html:
        return out

    soup = BeautifulSoup(html, "html.parser")
    cur = None
    # h3 (altılı başlığı) ve table (ayak) sırayla gez
    for el in soup.find_all(["h3", "table"]):
        if el.name == "h3":
            m = _HEAD_RE.search(el.get_text(strip=True))
            if m and m.group(1) == date_str and (not only_tr or _norm_tr(m.group(3))):
                cur = {"hippodrome": m.group(3).strip(), "altili_no": int(m.group(4)),
                       "time": m.group(2), "legs": {}}
                out["altilis"].append(cur)
            else:
                cur = None
        elif el.name == "table" and cur is not None:
            ayak = None
            for tr in el.find_all("tr"):
                txt = tr.get_text(" ", strip=True)
                ma = _AYAK_RE.search(txt)
                if ma:
                    ayak = int(ma.group(1))
                    cur["legs"].setdefault(ayak, [])
                    continue
                mt = _AT_RE.search(txt)
                if mt and ayak is not None:
                    cur["legs"][ayak].append(
                        {"at_no": int(mt.group(1)), "agf_pct": float(mt.group(2).replace(",", "."))})
    out["ok"] = bool(out["altilis"])
    return out


def save_day(day: dict) -> Optional[str]:
    if not day.get("ok"):
        return None
    d = day["date"]
    os.makedirs(os.path.join(CACHE_DIR, d), exist_ok=True)
    path = os.path.join(CACHE_DIR, d, "agf.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return path


def is_cached(date_str: str) -> bool:
    return os.path.exists(os.path.join(CACHE_DIR, date_str, "agf.json"))


def quality_check(day: dict) -> dict:
    """Ayak başına AGF% toplamı ~100 mü (piyasa normalizasyonu)."""
    notes = []
    for alt in day.get("altilis", []):
        per_leg = {ay: round(sum(h["agf_pct"] for h in hs), 1) for ay, hs in alt["legs"].items()}
        ok = all(80 <= v <= 120 for v in per_leg.values()) if per_leg else False
        notes.append({"hippodrome": alt["hippodrome"], "altili_no": alt["altili_no"],
                      "n_legs": len(alt["legs"]), "per_leg_agf_sum": per_leg, "legs_ok": ok})
    return {"date": day.get("date"), "altili_count": len(day.get("altilis", [])), "per_altili": notes}
