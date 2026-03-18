# -*- coding: utf-8 -*-
"""
TJK Yabanci Yaris Scraper v4
=============================
Tek sayfa: agftahmin.com/agf-tablosu
H3 basliklarindan hipodromlar, tablolardan AGF yuzdeleri.
Ayrica: agftahmin.com/at-yarisi/{slug} den yaris karti.
Hipodrom listesi sayfasi KULLANILMIYOR (bug source'u idi).
"""
import requests, re, logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)
BASE = "https://www.agftahmin.com"
HDR = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"}

DOMESTIC = ["adana", "bursa", "istanbul", "ankara", "izmir", "elazig",
            "sanliurfa", "diyarbakir", "antalya", "kocaeli", "samsun"]

COUNTRY_MAP = {"abd":"USA", "fransa":"FRA", "ingiltere":"GBR",
    "avustralya":"AUS", "dubai":"UAE", "bae":"UAE", "malezya":"MYS",
    "singapur":"SGP", "hong kong":"HKG", "japonya":"JPN"}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","UNK":"\U0001f3c1"}

SOURCE_MAP = {"USA":["twinspires","betfair","oddschk"], "FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"], "AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"], "HKG":["betfair","oddschk"], "UNK":["oddschk"]}


def is_foreign(name):
    low = name.lower()
    for d in DOMESTIC:
        if d in low:
            return False
    return True


def detect_country(name):
    low = name.lower()
    for k, v in COUNTRY_MAP.items():
        if k in low:
            return v
    return "UNK"


def name_to_slug(name):
    s = name.lower().strip()
    tr_map = {"\u0131":"i","\u00e7":"c","\u015f":"s","\u011f":"g","\u00fc":"u","\u00f6":"o",
              "\u0130":"i","\u00c7":"c","\u015e":"s","\u011e":"g","\u00dc":"u","\u00d6":"o"}
    for old, new in tr_map.items():
        s = s.replace(old, new)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"\s+", "-", s).strip("-")
    return s


def fetch_agf_page():
    """agftahmin.com/agf-tablosu sayfasini cek.
    Bu TEK SAYFA'da bugunun TUM hipodromlari + AGF oranlari var."""
    try:
        url = f"{BASE}/agf-tablosu"
        logger.info(f"Fetching: {url}")
        r = requests.get(url, headers=HDR, timeout=20)
        r.raise_for_status()
        logger.info(f"AGF sayfa OK: {len(r.text)} char, status={r.status_code}")
        return r.text
    except Exception as e:
        logger.error(f"AGF sayfa hatasi: {e}")
        return None


def parse_agf_page(html):
    """AGF sayfasindan hipodromlari VE oranlari cikart.
    
    Sayfa yapisi (gercek):
      <h3>2026-03-16 - 15:55 Chantilly Fransa AGF Tahmin 1. Altili</h3>
      <table>  <- 1. AYAK
        <tr><td>8 (%18.01)</td></tr>
        ...
      </table>
      <table>  <- 2. AYAK
        ...
      </table>
      ... 6 ayak ...
      <h3>... sonraki hipodrom ...</h3>
    
    Returns: dict {
        hipodrom_adi: {
            "time": "15:55",
            "legs": {1: {at_num: pct, ...}, 2: {...}, ...}
        }
    }
    """
    soup = BeautifulSoup(html, "html.parser")
    result = {}
    
    h3s = soup.find_all("h3")
    logger.info(f"Sayfada {len(h3s)} h3 baslik bulundu")
    
    for h3 in h3s:
        title = h3.get_text(strip=True)
        logger.info(f"  H3: {title[:80]}")
        
        # Format: "2026-03-17 - 15:55 Chantilly Fransa AGF Tahmin 1. Altili"
        m = re.search(r"(\d{2}[:\.]\d{2})\s+(.+?)\s+AGF", title)
        if not m:
            logger.info(f"    -> SKIP (AGF pattern yok)")
            continue
        
        time_str = m.group(1).replace(".", ":")
        hip_name = m.group(2).strip()
        
        # Altili numarasi
        alt_m = re.search(r"(\d+)\.", title.split("AGF")[-1])
        altili = int(alt_m.group(1)) if alt_m else 1
        
        key = f"{hip_name}_{altili}"
        
        # H3'ten sonraki tablolari tara
        legs = {}
        leg = 0
        elem = h3.find_next_sibling()
        
        while elem:
            if elem.name == "h3":
                break
            
            tbl = None
            if elem.name == "table":
                tbl = elem
            elif hasattr(elem, "find") and elem.find("table"):
                tbl = elem.find("table")
            
            if tbl:
                leg += 1
                leg_data = {}
                
                for row in tbl.find_all("tr"):
                    txt = row.get_text(strip=True)
                    if "AYAK" in txt:
                        continue
                    
                    # "4 (%30.53)" veya "1 (%23.02)"
                    for match in re.finditer(r"(\d+)\s*\(%([\d.]+)%?\)", txt):
                        try:
                            at_num = int(match.group(1))
                            pct = float(match.group(2))
                            if 0 < pct <= 100 and 0 < at_num <= 30:
                                leg_data[at_num] = pct
                        except ValueError:
                            pass
                
                if leg_data:
                    legs[leg] = leg_data
            
            elem = elem.find_next_sibling()
        
        if legs:
            result[key] = {"name": hip_name, "time": time_str, "altili": altili, "legs": legs}
            logger.info(f"    -> {hip_name} altili#{altili}: {len(legs)} ayak")
    
    return result


def fetch_racecard(slug):
    """Hipodrom yaris karti: at isimleri, jokeyler."""
    url = f"{BASE}/at-yarisi/{slug}"
    try:
        logger.info(f"  Racecard: {url}")
        r = requests.get(url, headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        races = []
        tables = soup.find_all("table")
        logger.info(f"  Racecard sayfada {len(tables)} tablo")
        
        for idx, table in enumerate(tables):
            horses = []
            rows = table.find_all("tr")
            
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) < 2:
                    continue
                texts = [c.get_text(strip=True) for c in cells]
                
                try:
                    num = int(texts[0]) if texts[0].isdigit() else 0
                    name = texts[1].strip() if len(texts) > 1 else ""
                    jockey = texts[5].strip() if len(texts) > 5 else ""
                    trainer = texts[7].strip() if len(texts) > 7 else ""
                    form = texts[10].strip() if len(texts) > 10 else ""
                    
                    if name and num > 0:
                        horses.append({"num":num, "name":name, "jockey":jockey,
                                       "trainer":trainer, "form":form, "tjk":0})
                except (ValueError, IndexError):
                    continue
            
            if horses:
                race_num = idx + 1
                header = table.find_previous("h3")
                if header:
                    nm = re.search(r"(\d+)\.", header.get_text())
                    if nm:
                        race_num = int(nm.group(1))
                
                races.append({"number":race_num, "time":"", "distance":"",
                              "type":"", "pool_tl":0, "horses":horses})
        
        logger.info(f"  Racecard: {len(races)} yaris, {sum(len(r['horses']) for r in races)} at")
        return races
    
    except Exception as e:
        logger.error(f"  Racecard hatasi ({slug}): {e}")
        return []


def pct_to_odds(pct):
    if pct <= 0: return 0
    return round(100.0 / pct, 2)


def build_tracks(agf_data):
    """AGF verisinden track listesi olustur, yaris kartlari cek, AGF eslestir."""
    
    # Unique hipodromlari bul
    hip_map = {}  # name -> {time, all_legs}
    for key, data in agf_data.items():
        name = data["name"]
        if name not in hip_map:
            hip_map[name] = {"time": data["time"], "all_legs": {}}
        # Altili bacaklarini birlestir
        for leg_num, leg_data in data["legs"].items():
            global_leg = len(hip_map[name]["all_legs"]) + 1
            hip_map[name]["all_legs"][global_leg] = leg_data
    
    logger.info(f"Unique hipodromlar: {list(hip_map.keys())}")
    
    # Yabancilari filtrele
    foreign_names = [n for n in hip_map.keys() if is_foreign(n)]
    logger.info(f"Yabanci: {foreign_names}")
    
    if not foreign_names:
        logger.warning("Yabanci hipodrom yok")
        return []
    
    tracks = []
    for hip_name in foreign_names:
        hip_info = hip_map[hip_name]
        country = detect_country(hip_name)
        slug = name_to_slug(hip_name)
        
        # Yaris karti cek
        races = fetch_racecard(slug)
        
        # AGF oranlarini eslestir (bacak sirasi = kosu sirasi)
        all_legs = hip_info["all_legs"]
        matched_total = 0
        
        for i, race in enumerate(races):
            leg_num = i + 1
            if leg_num not in all_legs:
                continue
            
            leg_data = all_legs[leg_num]
            for horse in race["horses"]:
                pct = leg_data.get(horse["num"], 0)
                if pct > 0:
                    horse["tjk"] = pct_to_odds(pct)
                    horse["agf_pct"] = pct
                    matched_total += 1
        
        if matched_total > 0:
            logger.info(f"  {hip_name}: {matched_total} at AGF eslestirildi")
        
        tracks.append({
            "id": slug,
            "name": hip_name,
            "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races,
        })
    
    return tracks


def fetch_foreign_races(tarih=None):
    """ANA FONKSIYON: Bugunun yabanci yarislarini dondur."""
    logger.info("=== TJK ARB Scraper v4 basliyor ===")
    
    # Adim 1: AGF sayfasini cek (TEK SAYFA, her sey burada)
    html = fetch_agf_page()
    if not html:
        logger.error("AGF sayfasi alinamadi")
        return []
    
    # Adim 2: H3 basliklarindan hipodromlar + AGF oranlari parse et
    agf_data = parse_agf_page(html)
    if not agf_data:
        logger.warning("AGF verisi parse edilemedi")
        return []
    
    # Adim 3: Yabanci hipodromlar icin yaris karti cek + AGF eslestir
    tracks = build_tracks(agf_data)
    
    total_races = sum(len(t["races"]) for t in tracks)
    total_horses = sum(len(h) for t in tracks for r in t["races"] for h in [r["horses"]])
    logger.info(f"=== SONUC: {len(tracks)} hipodrom, {total_races} yaris, {total_horses} at ===")
    
    return tracks
