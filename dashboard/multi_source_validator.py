"""
Multi-Source Scraper Validator
==============================
3 bagimsiz kaynaktan altili listesi ceker, capraz dogrulama yapar.

Source 1: agftablosu.com (mevcut AGF scraper)
Source 2: TJK resmi sitesi (www.tjk.org gunluk program)
Source 3: horseturk.com (expert consensus tahminleri)

Her kaynak icin altili listesi: [(hippodrome, altili_no, time, n_legs)]

Sonuc: dict with
  - consensus_altilis: en az 2 kaynakta dogrulanmis altili listesi
  - single_source_altilis: sadece 1 kaynakta gorulen (suspicious)
  - conflicts: ayni (hippo, altili_no) icin kaynaklar arasi farklar
  - source_status: her kaynagin OK/FAIL + detail
"""
import requests
import logging
import re
from bs4 import BeautifulSoup
from datetime import date
from typing import List, Dict, Tuple, Optional

logger = logging.getLogger(__name__)

STRONG_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                   "AppleWebKit/537.36 (KHTML, like Gecko) "
                   "Chrome/120.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "tr-TR,tr;q=0.9,en;q=0.8",
    "Accept-Encoding": "gzip, deflate, br",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1",
}

TURKISH_HIPPODROMES = [
    "bursa", "istanbul", "ankara", "izmir", "adana",
    "elazig", "elazig", "diyarbakir", "sanliurfa",
    "antalya", "kocaeli",
]


def _tr_lower(s: str) -> str:
    """Turkish-safe lowercase."""
    import unicodedata
    result = s.lower()
    result = unicodedata.normalize("NFC", result)
    result = result.replace("\u0307", "")
    return result


def _normalize_hippo(name: str) -> str:
    """Extract canonical Turkish hippodrome name."""
    low = _tr_lower(name)
    for h in TURKISH_HIPPODROMES:
        if h in low:
            return h
    return low.split()[0] if low else "unknown"


# ============================================================
# SOURCE 1: agftablosu.com
# ============================================================
def fetch_source_agftablosu() -> Dict:
    """Return {status, altilis: [(hippo, alt_no, time, n_legs)], raw_count}."""
    out = {"name": "agftablosu", "status": "FAIL",
           "altilis": [], "error": None, "raw_count": 0}
    try:
        resp = requests.get("https://www.agftablosu.com/agf-tablosu",
                             headers=STRONG_HEADERS, timeout=15)
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code}"
            return out

        soup = BeautifulSoup(resp.text, "html.parser")
        headers = soup.find_all("h3")
        for h in headers:
            txt = h.get_text(strip=True)
            if "AGF" not in txt or "lt" not in txt.lower():
                continue
            if not any(c in txt.lower() for c in TURKISH_HIPPODROMES + ["i̇stanbul"]):
                continue

            # Parse: "24 Nisan 2026 Cuma 13:30 Bursa AGF Tablosu 1. Altılı"
            m = re.search(
                r"(\d{1,2}:\d{2})\s+(.+?)\s+AGF\s+Tablosu\s+(\d+)",
                txt, re.IGNORECASE
            )
            if not m:
                continue

            time_str = m.group(1)
            hippo_raw = m.group(2).strip()
            alt_no = int(m.group(3))
            hippo = _normalize_hippo(hippo_raw)

            # Count tables between this h3 and next
            n_tables = 0
            sibling = h.find_next_sibling()
            while sibling:
                if sibling.name == "h3":
                    break
                if sibling.name == "table":
                    n_tables += 1
                elif hasattr(sibling, "find_all"):
                    n_tables += len(sibling.find_all("table"))
                sibling = sibling.find_next_sibling()

            out["altilis"].append({
                "hippodrome": hippo,
                "altili_no": alt_no,
                "time": time_str,
                "n_legs": min(n_tables, 6),
            })
            out["raw_count"] += 1
        out["status"] = "OK"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


# ============================================================
# SOURCE 2: TJK resmi sitesi
# ============================================================
def fetch_source_tjk_official() -> Dict:
    """Scrape www.tjk.org daily program; find altili markers."""
    out = {"name": "tjk_official", "status": "FAIL",
           "altilis": [], "error": None, "raw_count": 0}
    try:
        # Main daily program page
        resp = requests.get(
            "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami",
            headers=STRONG_HEADERS, timeout=15
        )
        if resp.status_code != 200:
            out["error"] = f"HTTP {resp.status_code}"
            return out

        # TJK page has links to each hippodrome's program
        # Pattern: "Bursa (4. Y.G.)" "İstanbul (5. Y.G.)"
        text = resp.text
        # Look for "X. 6'LI GANYAN Bu koşudan başlar" markers
        # Combined with hippodrome anchors in the page

        # Find hippodrome anchors
        soup = BeautifulSoup(text, "html.parser")

        # Search for pattern like "Bursa" followed by race info
        # TJK page structure: hippodromes are linked; click opens detail
        # We'll count "X. 6'LI GANYAN" markers per hippodrome in plain text
        for hippo in TURKISH_HIPPODROMES:
            # Case-insensitive search in page
            hippo_idx = _tr_lower(text).find(hippo)
            if hippo_idx == -1:
                continue

            # Try the hippodrome-specific program page
            try:
                hippo_capitalized = hippo.capitalize()
                # TJK has per-hippodrome pages like:
                # /TR/YarisSever/Info/Page/GunlukYarisProgrami?HippodromId=N
                # But simpler: scrape the all-races page, count altili markers
                pass
            except Exception:
                pass

            # Count "6'LI GANYAN" mentions near this hippodrome name
            # Each "1. 6'LI GANYAN" or "2. 6'LI GANYAN" = one altili
            window_start = max(0, hippo_idx - 500)
            window_end = min(len(text), hippo_idx + 50000)
            window = text[window_start:window_end]

            altili_matches = re.findall(
                r"(\d+)\.\s*6'LI\s+GANYAN",
                window, re.IGNORECASE
            )
            n_altili = len(set(altili_matches))

            if n_altili > 0:
                for alt_str in set(altili_matches):
                    out["altilis"].append({
                        "hippodrome": hippo,
                        "altili_no": int(alt_str),
                        "time": None,  # TJK program lists per-race times, not altili start
                        "n_legs": 6,
                    })
                    out["raw_count"] += 1
        out["status"] = "OK"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


# ============================================================
# SOURCE 3: horseturk.com
# ============================================================
def fetch_source_horseturk() -> Dict:
    """HorseTurk has per-hippodrome prediction pages."""
    out = {"name": "horseturk", "status": "FAIL",
           "altilis": [], "error": None, "raw_count": 0}
    try:
        today = date.today()
        # Turkish month names
        months = ["ocak", "subat", "mart", "nisan", "mayis", "haziran",
                  "temmuz", "agustos", "eylul", "ekim", "kasim", "aralik"]
        day = today.day
        month = months[today.month - 1]
        year = today.year

        # URL pattern: /at-yarisi-tahminleri-{hippo}-{d}-{month}-{year}/
        for hippo in ["bursa", "istanbul", "ankara", "izmir",
                       "adana", "elazig", "diyarbakir", "sanliurfa"]:
            try:
                url = f"https://www.horseturk.com/at-yarisi-tahminleri-{hippo}-{day}-{month}-{year}/"
                r = requests.get(url, headers=STRONG_HEADERS, timeout=10)
                if r.status_code != 200:
                    continue

                text = r.text
                # Count altili mentions in page
                altili_matches = re.findall(
                    r"(\d+)\.\s*Alt[ıi]l[ıi]",
                    text, re.IGNORECASE
                )
                unique_altilis = set(altili_matches)

                # HorseTurk usually only predicts 1st altili per hippo
                # but it's still a 3rd confirmation that the hippo is racing
                if unique_altilis:
                    for alt_str in unique_altilis:
                        out["altilis"].append({
                            "hippodrome": hippo,
                            "altili_no": int(alt_str),
                            "time": None,
                            "n_legs": 6,
                        })
                        out["raw_count"] += 1
                elif "kosu" in text.lower() or "at yarisi" in text.lower():
                    # Page exists, hippo is racing, but altili not directly marked
                    # Assume at least 1 altili exists
                    out["altilis"].append({
                        "hippodrome": hippo,
                        "altili_no": 1,
                        "time": None,
                        "n_legs": 6,
                    })
                    out["raw_count"] += 1
            except Exception:
                continue
        out["status"] = "OK"
    except Exception as e:
        out["error"] = str(e)[:200]
    return out


# ============================================================
# VALIDATOR
# ============================================================
def validate_sources() -> Dict:
    """Fetch all 3 sources, cross-check, return consensus.

    Returns:
        {
          "sources": {
            "agftablosu": {status, altilis, error, raw_count},
            "tjk_official": {...},
            "horseturk": {...}
          },
          "consensus_altilis": [  # in >=2 sources
            {"hippodrome": "bursa", "altili_no": 1,
             "confirmed_by": ["agftablosu","tjk_official"], "times": [...]}
          ],
          "single_source_altilis": [...],  # only in 1 source
          "conflicts": [...],  # same (hippo,alt) with different times
          "confidence": "HIGH" | "MEDIUM" | "LOW",
        }
    """
    sources = {
        "agftablosu": fetch_source_agftablosu(),
        "tjk_official": fetch_source_tjk_official(),
        "horseturk": fetch_source_horseturk(),
    }

    # Build index: (hippo, altili_no) -> [source_name, ...]
    key_to_sources = {}
    key_to_times = {}
    for sname, sdata in sources.items():
        for alt in sdata.get("altilis", []):
            key = (alt["hippodrome"], alt["altili_no"])
            key_to_sources.setdefault(key, []).append(sname)
            if alt.get("time"):
                key_to_times.setdefault(key, []).append(
                    (sname, alt["time"])
                )

    consensus_altilis = []
    single_source_altilis = []
    conflicts = []

    for key, src_list in key_to_sources.items():
        hippo, alt_no = key
        times = key_to_times.get(key, [])
        entry = {
            "hippodrome": hippo,
            "altili_no": alt_no,
            "confirmed_by": src_list,
            "times_reported": times,
        }
        # Check for time conflicts
        distinct_times = set(t[1] for t in times)
        if len(distinct_times) > 1:
            conflicts.append({
                **entry,
                "conflict": "time_mismatch",
                "distinct_times": list(distinct_times),
            })

        if len(src_list) >= 2:
            consensus_altilis.append(entry)
        else:
            single_source_altilis.append(entry)

    # Confidence based on how many sources are alive
    alive = sum(1 for s in sources.values() if s["status"] == "OK")
    if alive >= 3 and len(consensus_altilis) >= 1:
        confidence = "HIGH"
    elif alive >= 2 and len(consensus_altilis) >= 1:
        confidence = "MEDIUM"
    elif alive >= 1:
        confidence = "LOW"
    else:
        confidence = "NONE"

    return {
        "sources": sources,
        "consensus_altilis": consensus_altilis,
        "single_source_altilis": single_source_altilis,
        "conflicts": conflicts,
        "alive_source_count": alive,
        "confidence": confidence,
    }
