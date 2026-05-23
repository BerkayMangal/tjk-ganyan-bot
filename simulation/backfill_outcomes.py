"""Phase 5.2.5 — Geçmiş yarış sonuçları backfill (TJK Sehir, statik HTML).

page (GunlukYarisSonuclari?Tarih) → Sehir detay linkleri (page-driven Era — kritik) →
9 koşu tablosu → S=1 satırı → kazanan at_no (isim parantez). Read-only, politeness 2s.
"""
from __future__ import annotations

import html
import json
import os
import re
import time
from typing import Optional
from urllib.parse import unquote

import requests
from bs4 import BeautifulSoup

BASE = "https://www.tjk.org"
PAGE = BASE + "/TR/YarisSever/Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih={}"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Accept-Encoding": "gzip, deflate"}
TR_HIPPO = ("ankara", "istanbul", "izmir", "bursa", "adana", "kocaeli",
            "antalya", "sanliurfa", "urfa", "elaz", "diyarb")
POLITE = 2.0
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CACHE_DIR = os.path.join(_REPO, "data", "backfill", "outcomes")
_LINK_RE = re.compile(r'(/TR/YarisSever/Info/Sehir/GunlukYarisSonuclari\?[^"\']+)')
_AT_NO = re.compile(r"\((\d+)\)")
_TR_FOLD = str.maketrans("İıÇçĞğÖöŞşÜü", "iiccggoossuu")


def _fold(s: str) -> str:
    """Türkçe-ASCII fold + lower (İstanbul=%C4%B0... eşleşsin)."""
    return unquote(s).translate(_TR_FOLD).lower()


def _get(url: str, retries: int = 3) -> Optional[str]:
    for a in range(retries):
        try:
            r = requests.get(url, headers=HDR, timeout=20)
            if r.status_code == 200:
                return r.text
        except Exception:
            pass
        time.sleep(1.5 * (a + 1))
    return None


def _sehir_links(dd_mm_yyyy: str) -> list:
    txt = _get(PAGE.format(dd_mm_yyyy))
    if not txt:
        return []
    links = {html.unescape(l) for l in _LINK_RE.findall(txt.replace("&amp;", "&"))}
    return [l for l in links if any(t in _fold(l) for t in TR_HIPPO)]


def _parse_sehir(link: str) -> dict:
    txt = _get(BASE + link)
    m = re.search(r"SehirAdi=([^&]+)", link)
    sehir = unquote(html.unescape(m.group(1)).replace("+", " ")) if m else "?"
    out = {"hippodrome": sehir, "kosular": {}}
    if not txt:
        return out
    soup = BeautifulSoup(txt, "html.parser")
    for i, tbl in enumerate(soup.find_all("table"), start=1):
        winner = None
        at_nos = []
        for tr in tbl.find_all("tr")[1:]:
            cells = [c.get_text(" ", strip=True) for c in tr.find_all(["td", "th"])]
            if len(cells) < 3:
                continue
            mt = _AT_NO.search(cells[2])  # at_no, isim parantez "ZİDAN(4)"
            if not mt:
                continue
            atn = int(mt.group(1))
            at_nos.append(atn)
            if cells[1].strip() == "1" and winner is None:  # S=1 → kazanan
                winner = atn
        if winner is not None and at_nos:  # all_at_nos → kesin ayak↔koşu join (PART C)
            out["kosular"][i] = {"winner": winner, "at_nos": at_nos}
    return out


def fetch_outcomes_for_date(date_iso: str) -> dict:
    """date_iso='YYYY-MM-DD'. Returns {date, ok, hippodromes:[{hippodrome, kosular:{kosu_no:winner_at_no}}]}."""
    y, m, d = date_iso.split("-")
    dd_mm = f"{d}/{m}/{y}"
    out = {"date": date_iso, "source": "tjk_sehir", "ok": False, "hippodromes": []}
    links = _sehir_links(dd_mm)
    for l in links:
        time.sleep(POLITE)
        parsed = _parse_sehir(l)
        if parsed["kosular"]:
            out["hippodromes"].append(parsed)
    out["ok"] = bool(out["hippodromes"])
    return out


def is_cached(date_iso: str) -> bool:
    return os.path.exists(os.path.join(CACHE_DIR, date_iso, "outcomes.json"))


def save_day(day: dict) -> Optional[str]:
    if not day.get("ok"):
        return None
    os.makedirs(os.path.join(CACHE_DIR, day["date"]), exist_ok=True)
    p = os.path.join(CACHE_DIR, day["date"], "outcomes.json")
    with open(p, "w", encoding="utf-8") as f:
        json.dump(day, f, ensure_ascii=False, indent=1)
    return p
