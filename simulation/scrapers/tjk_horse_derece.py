"""Phase 9 — At-form CANLI scraper (TJK DetayliDereceIst).

Her at için son ~52 derece kaydını çek (Sort=Yıl DESC → yeniden eskiye sıralı).
Her satırın `At İsmi` hücresi tıklanabilir link → href'te tam tarih (DD/MM/YYYY) var
→ görünür kolon sadece Yıl ama biz tam tarihi parse ediyoruz.

Politeness 2s. Statik HTML (Era pagination GET ile çalışmıyor — sadece default sayfa).
At kariyer >52 koşu ise Sort=Yıl DESC ile en yeni 52 alınır, form için yeterli.

Şema (her kayıt):
    at_adi, kilo, irk, cinsiyet, yil, sehir, pist, pist_durumu, mesafe, derece,
    kosu_cinsi, date (YYYY-MM-DD veya None)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Optional
from urllib.parse import quote

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.tjk.org/TR/YarisSever/Query/Page/DetayliDereceIst"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Accept-Language": "tr-TR,tr;q=0.9"}
POLITE_SEC = 2.0
TIMEOUT = 25

# href örneği: "../Info/Page/GunlukYarisSonuclari?QueryParameter_Tarih=13%2f01%2f2018"
_DATE_RE = re.compile(r"Tarih=(\d{2})[/%]2[fF]?(\d{2})[/%]2[fF]?(\d{4})", re.IGNORECASE)


def _to_int(s):
    try:
        return int(str(s or "").replace(".", "").strip())
    except Exception:
        return None


def _parse_date_from_href(href: str) -> Optional[str]:
    """href içinden Tarih=DD/MM/YYYY → ISO 'YYYY-MM-DD'."""
    if not href:
        return None
    cleaned = href.replace("%2f", "/").replace("%2F", "/")
    m = re.search(r"Tarih=(\d{2})/(\d{2})/(\d{4})", cleaned)
    if not m:
        return None
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"


def _parse_derece_html(html: str) -> list[dict]:
    """11-sütunlu DerereIst tablosunu parse et + her satırdan tam tarih çıkar."""
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return []
    rows = tbl.find_all("tr")
    if len(rows) < 2:
        return []
    out = []
    for tr in rows[1:]:
        cells = [td.get_text(" ", strip=True) for td in tr.find_all(["td", "th"])]
        if len(cells) < 11:
            continue
        link = tr.find("a")
        date = _parse_date_from_href(link.get("href", "") if link else "")
        out.append({
            "at_adi": cells[0],
            "kilo": _to_int(cells[1]),
            "irk": cells[2],
            "cinsiyet": cells[3],
            "yil": _to_int(cells[4]),
            "sehir": cells[5],
            "pist": cells[6],
            "pist_durumu": cells[7],
            "mesafe": _to_int(cells[8]),       # "1.200" → 1200
            "derece": cells[9],                # "1.14.46" — saniye HH.MM.SS format
            "kosu_cinsi": cells[10],
            "date": date,
        })
    return out


def fetch_horse_derece(at_adi: str, sort: str = "Yil DESC",
                       retries: int = 3) -> list[dict]:
    """Bir atın TJK Detaylı Derece kayıtlarını çek. Hata → [] (sessiz değil, log atılır)."""
    if not at_adi:
        return []
    url = f"{BASE}?QueryParameter_AtAdi={quote(at_adi)}&Sort={quote(sort)}"
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 200 and len(r.text) > 8000:
                recs = _parse_derece_html(r.text)
                if recs:
                    return recs
                logger.warning(f"tjk_derece {at_adi!r}: 200 ama 0 kayıt parse edildi")
                return []
            last_err = f"HTTP {r.status_code} (len={len(r.text)})"
        except Exception as e:
            last_err = repr(e)[:120]
        time.sleep(1.5 * (attempt + 1))
    logger.warning(f"tjk_derece {at_adi!r} fetch başarısız ({retries} deneme): {last_err}")
    return []
