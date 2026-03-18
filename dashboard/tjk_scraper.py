# -*- coding: utf-8 -*-
"""
TJK Scraper v5 — agftahmin.com
Hem yerli hem yabanci yarislar, tek kaynak.
AGF sayfasindan H3 parse + yaris karti ayri sayfa.
"""
import requests, re, logging, json
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE = "https://www.agftahmin.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36",
       "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
       "Accept-Language": "tr-TR,tr;q=0.9,en-US;q=0.8,en;q=0.7"}

DOMESTIC_NAMES = ["adana","bursa","istanbul","ankara","izmir","elazig",
                  "sanliurfa","diyarbakir","antalya","kocaeli","samsun"]

COUNTRY_MAP = {"abd":"USA","fransa":"FRA","ingiltere":"GBR","avustralya":"AUS",
    "dubai":"UAE","bae":"UAE","malezya":"MYS","singapur":"SGP","hong kong":"HKG","japonya":"JPN"}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","TR":"\U0001f1f9\U0001f1f7","UNK":"\U0001f3c1"}

SOURCE_MAP = {"USA":["twinspires","betfair","oddschk"],"FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"],"AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"],"TR":[],"UNK":["oddschk"]}


def is_domestic(name):
    low = name.lower()
    for d in DOMESTIC_NAMES:
        if d in low: return True
    return False


def detect_country(name):
    if is_domestic(name): return "TR"
    low = name.lower()
    for k, v in COUNTRY_MAP.items():
        if k in low: return v
    return "UNK"


def name_to_slug(name):
    s = name.lower().strip()
    for old, new in [("\u0131","i"),("\u00e7","c"),("\u015f","s"),("\u011f","g"),
                     ("\u00fc","u"),("\u00f6","o"),("\u0130","i"),("\u00c7","c"),
                     ("\u015e","s"),("\u011e","g"),("\u00dc","u"),("\u00d6","o")]:
        s = s.replace(old, new)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def pct_to_odds(pct):
    if pct <= 0: return 0
    return round(100.0 / pct, 2)


def fetch_agf_page():
    """AGF sayfasini cek — bugunun TUM hipodromlari burada."""
    try:
        url = f"{BASE}/agf-tablosu"
        logger.info(f"AGF fetch: {url}")
        r = requests.get(url, headers=HDR, timeout=20)
        r.raise_for_status()
        logger.info(f"AGF OK: {len(r.text)} char")
        return r.text
    except Exception as e:
        logger.error(f"AGF sayfa hatasi: {e}")
        return None


def parse_agf_page(html):
    """H3 basliklarindan hipodromlar + tablolardan AGF yuzdeleri.
    
    Returns: list of {
        name: "Chantilly Fransa",
        time: "15:55",
        altili: 1,
        legs: {1: {at_num: pct}, 2: {...}, ...}
    }
    """
    soup = BeautifulSoup(html, "html.parser")
    entries = []
    
    h3s = soup.find_all("h3")
    logger.info(f"H3 sayisi: {len(h3s)}")
    
    for h3 in h3s:
        title = h3.get_text(strip=True)
        
        # "2026-03-17 - 14:30 Bursa AGF Tahmin 1. Altili"
        m = re.search(r"(\d{2}[:.]\d{2})\s+(.+?)\s+AGF", title)
        if not m:
            continue
        
        time_str = m.group(1).replace(".", ":")
        hip_name = m.group(2).strip()
        
        alt_m = re.search(r"(\d+)\.", title.split("AGF")[-1])
        altili = int(alt_m.group(1)) if alt_m else 1
        
        logger.info(f"  H3 parsed: {hip_name} altili#{altili} saat={time_str}")
        
        # Sonraki tablolar = ayaklar
        legs = {}
        leg = 0
        elem = h3.find_next_sibling()
        
        while elem:
            if elem.name == "h3": break
            
            tbl = None
            if elem.name == "table": tbl = elem
            elif hasattr(elem, "find") and elem.find("table"): tbl = elem.find("table")
            
            if tbl:
                leg += 1
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
                    legs[leg] = leg_data
            
            elem = elem.find_next_sibling()
        
        if legs:
            entries.append({"name": hip_name, "time": time_str, "altili": altili, "legs": legs})
    
    logger.info(f"AGF parsed: {len(entries)} altili ({[e['name'] for e in entries]})")
    return entries


def fetch_racecard(slug):
    """agftahmin.com/at-yarisi/{slug} den yaris karti cek."""
    url = f"{BASE}/at-yarisi/{slug}"
    try:
        r = requests.get(url, headers=HDR, timeout=15)
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
                races.append({"number":race_num, "time":"", "distance":"", "type":"",
                              "pool_tl":0, "horses":horses})
        
        logger.info(f"  Racecard {slug}: {len(races)} yaris, {sum(len(r['horses']) for r in races)} at")
        return races
    except Exception as e:
        logger.error(f"  Racecard hatasi ({slug}): {e}")
        return []


def build_all_tracks(agf_entries, only_foreign=True):
    """AGF verisinden track listesi olustur."""
    # Ayni hipodromu birlestir (1. altili + 2. altili)
    hip_map = {}
    for entry in agf_entries:
        name = entry["name"]
        if name not in hip_map:
            hip_map[name] = {"time": entry["time"], "legs": []}
        for leg_num in sorted(entry["legs"].keys()):
            hip_map[name]["legs"].append(entry["legs"][leg_num])
    
    logger.info(f"Hipodromlar: {list(hip_map.keys())}")
    
    # Filtrele
    if only_foreign:
        names = [n for n in hip_map if not is_domestic(n)]
    else:
        names = list(hip_map.keys())
    
    logger.info(f"{'Yabanci' if only_foreign else 'Tum'}: {names}")
    
    tracks = []
    for hip_name in names:
        info = hip_map[hip_name]
        country = detect_country(hip_name)
        slug = name_to_slug(hip_name)
        
        # Yaris karti cek
        races = fetch_racecard(slug)
        
        # AGF eslestir
        matched = 0
        for i, race in enumerate(races):
            if i >= len(info["legs"]): break
            leg = info["legs"][i]
            for horse in race["horses"]:
                pct = leg.get(horse["num"], 0)
                if pct > 0:
                    horse["tjk"] = pct_to_odds(pct)
                    horse["agf_pct"] = pct
                    matched += 1
        
        if matched > 0:
            logger.info(f"  {hip_name}: {matched} at AGF eslesti")
        
        tracks.append({
            "id": slug,
            "name": hip_name,
            "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races,
            "agf_time": info["time"],
        })
    
    return tracks


def fetch_foreign_races(tarih=None):
    """Yabanci yarislari dondur."""
    logger.info("=== YABANCI YARIS TARAMA ===")
    html = fetch_agf_page()
    if not html: return []
    entries = parse_agf_page(html)
    if not entries: return []
    return build_all_tracks(entries, only_foreign=True)


def fetch_domestic_races(tarih=None):
    """Yerli yarislari dondur."""
    logger.info("=== YERLI YARIS TARAMA ===")
    html = fetch_agf_page()
    if not html: return []
    entries = parse_agf_page(html)
    if not entries: return []
    return build_all_tracks(entries, only_foreign=False)


def fetch_all_races(tarih=None):
    """Hepsini dondur: yerli + yabanci ayri ayri."""
    logger.info("=== TUM YARISLAR ===")
    html = fetch_agf_page()
    if not html:
        return {"foreign": [], "domestic": []}
    entries = parse_agf_page(html)
    if not entries:
        return {"foreign": [], "domestic": []}
    
    foreign = build_all_tracks(entries, only_foreign=True)
    domestic_entries = [e for e in entries if is_domestic(e["name"])]
    domestic = build_all_tracks(entries, only_foreign=False)
    # domestic'ten yabancilari cikar
    domestic = [t for t in domestic if is_domestic(t["name"])]
    
    return {"foreign": foreign, "domestic": domestic}
