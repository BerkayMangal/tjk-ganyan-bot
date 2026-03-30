# -*- coding: utf-8 -*-
"""
TJK Scraper v6 — agftahmin.com
Turkce karakter fix, yerli/yabanci ayrim, AGF eslestirme iyilestirildi.
"""
import requests, re, logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE = "https://www.agftahmin.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
       "Accept": "text/html,application/xhtml+xml", "Accept-Language": "tr-TR,tr;q=0.9"}

# ─── TURKCE KARAKTER NORMALIZE ───
def tr_lower(s):
    """Turkce-safe lowercase. Python'da 'I'.lower()='i' ama 'I'.lower()='i' (noktasiz).
    Turkce: I->i, I->i, S->s, G->g, U->u, O->o, C->c"""
    table = str.maketrans({
        '\u0130': 'i',   # I (noktalI buyuk) -> i
        '\u0049': 'i',   # I -> i (ASCII I)
        '\u00dc': 'u',   # U -> u
        '\u00d6': 'o',   # O -> o
        '\u015e': 's',   # S -> s
        '\u011e': 'g',   # G -> g
        '\u00c7': 'c',   # C -> c
        '\u0131': 'i',   # i (noktasiz kucuk) -> i
        '\u00fc': 'u',   # u -> u
        '\u00f6': 'o',   # o -> o
        '\u015f': 's',   # s -> s
        '\u011f': 'g',   # g -> g
        '\u00e7': 'c',   # c -> c
    })
    return s.translate(table).lower()


# ─── YERLI HIPODROMLAR (normalize edilmis) ───
DOMESTIC = ["adana", "bursa", "istanbul", "ankara", "izmir", "elazig",
            "sanliurfa", "diyarbakir", "antalya", "kocaeli", "samsun",
            "konya", "elazi", "urfa"]  # kisaltmalar da

COUNTRY_MAP = {"abd":"USA", "fransa":"FRA", "ingiltere":"GBR", "avustralya":"AUS",
    "dubai":"UAE", "bae":"UAE", "malezya":"MYS", "singapur":"SGP",
    "hong kong":"HKG", "japonya":"JPN", "guney afrika":"ZAF",
    "arjantin":"ARG", "peru":"PER"}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8", "FRA":"\U0001f1eb\U0001f1f7", "GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa", "UAE":"\U0001f1e6\U0001f1ea", "HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5", "ZAF":"\U0001f1ff\U0001f1e6", "ARG":"\U0001f1e6\U0001f1f7",
         "TR":"\U0001f1f9\U0001f1f7", "UNK":"\U0001f3c1"}

SOURCE_MAP = {"USA":["twinspires","betfair","oddschk"], "FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"], "AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"], "ZAF":["oddschk"], "ARG":["oddschk"],
    "TR":[], "UNK":["oddschk"]}


def is_domestic(name):
    """Turkce karakter safe yerli kontrolu."""
    normalized = tr_lower(name)
    for d in DOMESTIC:
        if d in normalized:
            return True
    return False


def detect_country(name):
    if is_domestic(name):
        return "TR"
    normalized = tr_lower(name)
    for k, v in COUNTRY_MAP.items():
        if k in normalized:
            return v
    # Bilinen yabanci hipodromlar (ulke eki olmayan)
    known_foreign = {"lingfield":"GBR","ascot":"GBR","kempton":"GBR","newmarket":"GBR",
                     "wolverhampton":"GBR","perth ascot":"AUS","flemington":"AUS",
                     "cranbourne":"AUS","meydan":"UAE","sha tin":"HKG","happy valley":"HKG",
                     "gulfstream":"USA","tampa bay":"USA","santa anita":"USA"}
    for k, v in known_foreign.items():
        if k in normalized:
            return v
    return "UNK"


def name_to_slug(name):
    s = tr_lower(name)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def pct_to_odds(pct):
    if pct <= 0: return 0
    return round(100.0 / pct, 2)


def fetch_agf_page():
    try:
        r = requests.get(f"{BASE}/agf-tablosu", headers=HDR, timeout=20)
        r.raise_for_status()
        logger.info(f"AGF OK: {len(r.text)} char")
        return r.text
    except Exception as e:
        logger.error(f"AGF hatasi: {e}")
        return None


def parse_agf_page(html):
    """H3 basliklarindan hipodromlar + AGF yuzdeleri.
    V7 fix: find_all('table') ile TUM tablolari topla (6 ayak fix)."""
    soup = BeautifulSoup(html, "html.parser")
    entries = []

    for h3 in soup.find_all("h3"):
        title = h3.get_text(strip=True)
        m = re.search(r"(\d{2}[:.]\d{2})\s+(.+?)\s+AGF", title)
        if not m: continue

        time_str = m.group(1).replace(".", ":")
        hip_name = m.group(2).strip()
        alt_m = re.search(r"(\d+)\.", title.split("AGF")[-1])
        altili = int(alt_m.group(1)) if alt_m else 1

        # V7 FIX: Collect ALL tables between H3s (like proper scraper)
        tables = []
        elem = h3.find_next_sibling()
        while elem:
            if elem.name == "h3": break
            if elem.name == "table":
                tables.append(elem)
            elif hasattr(elem, "find_all"):
                inner_tables = elem.find_all("table")
                tables.extend(inner_tables)
            elem = elem.find_next_sibling()

        # Parse each table as a leg
        legs = {}
        for leg_idx, tbl in enumerate(tables, 1):
            leg_data = {}
            for row in tbl.find_all("tr"):
                txt = row.get_text(strip=True)
                if "AYAK" in txt: continue
                for match in re.finditer(r"(\d+)\s*\(%?([\d.]+)%?\)", txt):
                    try:
                        at_num = int(match.group(1))
                        pct = float(match.group(2))
                        if 0 < pct <= 100 and 0 < at_num <= 30:
                            leg_data[at_num] = pct
                    except ValueError: pass
            if leg_data:
                legs[leg_idx] = leg_data

        if legs:
            entries.append({"name": hip_name, "time": time_str, "altili": altili, "legs": legs})
            logger.info(f"  {hip_name} a#{altili}: {len(legs)} ayak, yerli={is_domestic(hip_name)}")

    logger.info(f"Toplam: {len(entries)} altili")
    return entries



def fetch_racecard(slug):
    """Yaris karti cek."""
    try:
        r = requests.get(f"{BASE}/at-yarisi/{slug}", headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")

        races = []
        for idx, table in enumerate(soup.find_all("table")):
            horses = []
            for row in table.find_all("tr")[1:]:
                cells = row.find_all("td")
                if len(cells) < 2: continue
                texts = [c.get_text(strip=True) for c in cells]
                try:
                    num = int(texts[0]) if texts[0].isdigit() else 0
                    name = texts[1].strip() if len(texts) > 1 else ""
                    jockey = texts[5].strip() if len(texts) > 5 else ""
                    if name and num > 0:
                        horses.append({"num":num, "name":name, "jockey":jockey, "tjk":0})
                except (ValueError, IndexError): continue

            if horses:
                race_num = idx + 1
                hdr = table.find_previous("h3")
                if hdr:
                    nm = re.search(r"(\d+)\.", hdr.get_text())
                    if nm: race_num = int(nm.group(1))
                races.append({"number":race_num, "time":"", "horses":horses})

        return races
    except Exception as e:
        logger.error(f"Racecard hatasi ({slug}): {e}")
        return []


def build_tracks(agf_entries, domestic_only):
    """AGF'den track listesi olustur.
    V8: Her altılı AYRI track olarak islenır (1. ve 2. altılı ayrı).
    """
    # Group by hipodrom+altılı — NOT just hipodrom
    hip_map = {}
    for entry in agf_entries:
        name = entry["name"]
        dom = is_domestic(name)
        altili_no = entry.get("altili", 1)

        if domestic_only and not dom: continue
        if not domestic_only and dom: continue

        # Key = name + altili_no → 1. ve 2. altılı AYRI
        key = f"{name}__a{altili_no}"
        if key not in hip_map:
            hip_map[key] = {
                "name": name,
                "altili_no": altili_no,
                "time": entry["time"],
                "legs": [],
            }
        for leg_num in sorted(entry["legs"].keys()):
            hip_map[key]["legs"].append(entry["legs"][leg_num])

    # Fetch racecard per unique hipodrom (not per altılı — same racecard)
    racecard_cache = {}
    tracks = []

    for key, info in hip_map.items():
        hip_name = info["name"]
        altili_no = info["altili_no"]
        country = detect_country(hip_name)
        slug = name_to_slug(hip_name)

        # Cache racecard — same hipodrom 1. ve 2. altılı aynı racecard kullanır
        if slug not in racecard_cache:
            racecard_cache[slug] = fetch_racecard(slug)
        races = racecard_cache[slug]

        # AGF eslestir — sadece bu altılının leg'leri
        matched = 0
        n_legs = len(info["legs"])
        for i, race in enumerate(races):
            if i >= n_legs: break
            leg = info["legs"][i]
            for horse in race["horses"]:
                pct = leg.get(horse["num"], 0)
                if pct > 0:
                    horse["tjk"] = pct_to_odds(pct)
                    horse["agf_pct"] = pct
                    matched += 1

        logger.info(f"  {hip_name} a#{altili_no} ({country}): {len(races)} yaris, {n_legs} ayak, {matched} AGF eslesme")

        tracks.append({
            "id": slug, "name": hip_name, "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races, "agf_time": info["time"],
            "altili_info": [{"altili": altili_no, "leg_count": n_legs}],
        })

    return tracks


def fetch_foreign_races(tarih=None):
    logger.info("=== YABANCI YARIS ===")
    html = fetch_agf_page()
    if not html: return []
    entries = parse_agf_page(html)
    if not entries: return []
    return build_tracks(entries, domestic_only=False)


def fetch_domestic_races(tarih=None):
    logger.info("=== YERLI YARIS ===")
    html = fetch_agf_page()
    if not html: return []
    entries = parse_agf_page(html)
    if not entries: return []
    return build_tracks(entries, domestic_only=True)


def fetch_all_races(tarih=None):
    logger.info("=== TUM YARISLAR ===")
    html = fetch_agf_page()
    if not html: return {"foreign":[], "domestic":[]}
    entries = parse_agf_page(html)
    if not entries: return {"foreign":[], "domestic":[]}
    return {
        "foreign": build_tracks(entries, domestic_only=False),
        "domestic": build_tracks(entries, domestic_only=True),
    }
