"""Phase 5.8.8 — At-idman (galop dereceleri) CANLI scraper.

Berkay (2026-06-15): "galoplar var mı içinde idman dereceleri" — bu modül onu
çözer. TJK İdman İstatistikleri sayfası mesafe-bazlı geçiş zamanı verir.

Endpoint:
    https://www.tjk.org/TR/YarisSever/Query/Page/IdmanIstatistikleri
      ?QueryParameter_ATADI=ATADI [&Sort=IDMANTARIH DESC]

Şema (her idman kaydı):
    atadi, irk, cinsiyet, yas,
    info1400, info1200, info1000, info800, info600, info400, info200,  # geçiş zamanları
    galopkisa,                                                          # kısa galop
    idmantarih,                                                         # DD.MM.YYYY
    kostuguhip, atin_konumu, pist_tur, idman_tur, jokey

Politeness 2s. Statik HTML, GET. At kariyeri >100 idman → IDMANTARIH DESC ile yeniler.
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

BASE = "https://www.tjk.org/TR/YarisSever/Query/Page/IdmanIstatistikleri"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) Chrome/120.0",
       "Accept-Language": "tr-TR,tr;q=0.9"}
POLITE_SEC = 2.0
TIMEOUT = 25

_COLS = [
    'atadi', 'irk', 'cinsiyet', 'yas',
    'info1400', 'info1200', 'info1000', 'info800', 'info600', 'info400', 'info200',
    'galopkisa', 'idmantarih', 'kostuguhip', 'atin_konumu', 'pist_tur', 'idman_tur',
    'jokey', 'id', 'atadi_dup',
]


def _to_iso(d):
    """DD.MM.YYYY → YYYY-MM-DD veya None."""
    if not d:
        return None
    m = re.search(r"(\d{2})\.(\d{2})\.(\d{4})", str(d))
    return f"{m.group(3)}-{m.group(2)}-{m.group(1)}" if m else None


def _parse_time(s):
    """'29.50' (sn) → 29.50 float; '1.14.46' → 74.46 sn. Boş → None."""
    if not s or not str(s).strip() or str(s).strip() in ('-', '.'):
        return None
    s = str(s).strip()
    parts = s.split('.')
    try:
        if len(parts) == 2:
            return float(parts[0]) + float('0.' + parts[1])
        if len(parts) == 3:
            return float(parts[0]) * 60 + float(parts[1]) + float('0.' + parts[2])
        return float(s)
    except Exception:
        return None


def _parse_idman_html(html: str) -> list[dict]:
    """`sorgu-IdmanIstatistikleri-*` class'lı td'leri sıralı olarak parse et."""
    soup = BeautifulSoup(html, "html.parser")
    tbl = soup.find("table")
    if not tbl:
        return []
    rows = tbl.find_all("tr")
    if len(rows) < 2:
        return []
    out = []
    for tr in rows[1:]:
        tds = tr.find_all("td")
        if len(tds) < 18:
            continue
        cells = [td.get_text(" ", strip=True) for td in tds]
        rec = dict(zip(_COLS, cells + [''] * (len(_COLS) - len(cells))))
        out.append({
            'atadi': rec['atadi'],
            'irk': rec['irk'],
            'cinsiyet': rec['cinsiyet'],
            'yas': rec['yas'],
            't_1400': _parse_time(rec['info1400']),
            't_1200': _parse_time(rec['info1200']),
            't_1000': _parse_time(rec['info1000']),
            't_800':  _parse_time(rec['info800']),
            't_600':  _parse_time(rec['info600']),
            't_400':  _parse_time(rec['info400']),
            't_200':  _parse_time(rec['info200']),
            'galop_kisa': rec['galopkisa'],
            'idman_date': _to_iso(rec['idmantarih']),
            'hippodrome': rec['kostuguhip'],
            'atin_konumu': rec['atin_konumu'],
            'pist_tur': rec['pist_tur'],
            'idman_tur': rec['idman_tur'],
            'jokey': rec['jokey'],
        })
    return out


def fetch_horse_idman(at_adi: str, sort: str = "IDMANTARIH DESC",
                      retries: int = 3) -> list[dict]:
    """Bir atın TJK İdman kayıtlarını çek. Hata → []. Politeness yapılmaz; çağıran
    multiple call yapacaksa ara verme görevini yüklenir."""
    if not at_adi:
        return []
    url = f"{BASE}?QueryParameter_ATADI={quote(at_adi)}&Sort={quote(sort)}"
    last_err = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=HDR, timeout=TIMEOUT)
            if r.status_code == 200 and len(r.text) > 8000:
                recs = _parse_idman_html(r.text)
                return recs
            last_err = f"HTTP {r.status_code} (len={len(r.text)})"
        except Exception as e:
            last_err = repr(e)[:120]
        time.sleep(1.5 * (attempt + 1))
    logger.warning(f"tjk_idman {at_adi!r} fetch failed ({retries}x): {last_err}")
    return []


def best_speed_for_distance(idman_records: list[dict], target_dist: int,
                              window_days: int = 30) -> Optional[float]:
    """Son N gün içinde target_dist mesafesine en yakın geçiş hızı (m/s).

    "INFO1400" gibi alanlar, atın o noktaya kadar geçişine bakar:
      atin_konumu='1400' olan satırlarda t_1400 → atın 1400m'lik kısmı koştuğu sn
    Aslında daha basit: target_dist=1400 ise t_1400 alanına bak.
    """
    if not idman_records:
        return None
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=window_days)).isoformat()
    key = f"t_{target_dist}"
    speeds = []
    for r in idman_records:
        d = r.get('idman_date')
        if not d or d < cutoff:
            continue
        t = r.get(key)
        if t and t > 0:
            speeds.append(target_dist / t)   # m/s
    if not speeds:
        return None
    return max(speeds)   # en hızlı


def avg_speed_for_distance(idman_records, target_dist, window_days=30):
    """Ortalama geçiş hızı."""
    if not idman_records:
        return None
    from datetime import date as _date, timedelta
    cutoff = (_date.today() - timedelta(days=window_days)).isoformat()
    key = f"t_{target_dist}"
    speeds = []
    for r in idman_records:
        d = r.get('idman_date')
        if not d or d < cutoff:
            continue
        t = r.get(key)
        if t and t > 0:
            speeds.append(target_dist / t)
    if not speeds:
        return None
    return sum(speeds) / len(speeds)


if __name__ == '__main__':
    import sys
    import json
    name = sys.argv[1] if len(sys.argv) > 1 else 'DOĞAN EFE'
    recs = fetch_horse_idman(name)
    print(f"\n{name} — {len(recs)} idman kaydı")
    for r in recs[:5]:
        print(f"  {r['idman_date']:>10s} · {r['hippodrome']:<12s} · "
              f"t1400={r['t_1400']} t1000={r['t_1000']} t600={r['t_600']} "
              f"galop={r['galop_kisa']:>6} jokey={r['jokey']}")
    print(f"\nbest_speed @1400: {best_speed_for_distance(recs, 1400, 30)} m/s")
    print(f"avg_speed @1000:  {avg_speed_for_distance(recs, 1000, 30)} m/s")
