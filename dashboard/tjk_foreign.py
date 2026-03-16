"""
TJK Yabanci Yaris Scraper v2
=============================
agftahmin.com'dan yabanci yarislari + AGF oranlarini ceker.
TJK.org JS render gerektiriyor, agftahmin.com temiz HTML.

Kaynaklar:
  Yaris karti: agftahmin.com/at-yarisi/{hipodrom-slug}
  AGF tablolari: agftahmin.com/agf-tablosu (tek sayfa, tum hipodromlar)
"""
import requests, re, logging
from datetime import datetime
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.agftahmin.com"
AGF_URL = f"{BASE}/agf-tablosu"
BULTEN_URL = f"{BASE}/at-yarisi"
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DOMESTIC = ["adana","bursa","istanbul","ankara","izmir","elazig",
            "sanliurfa","diyarbakir","antalya","kocaeli","samsun"]

COUNTRY_MAP = {
    "abd":"USA","fransa":"FRA","ingiltere":"GBR","uk":"GBR",
    "avustralya":"AUS","dubai":"UAE","bae":"UAE","malezya":"MYS",
    "singapur":"SGP","hong kong":"HKG","japonya":"JPN",
}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","MYS":"\U0001f1f2\U0001f1fe","UNK":"\U0001f3c1"}

SOURCE_MAP = {
    "USA":["twinspires","betfair","oddschk"],
    "FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"],
    "AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"],
    "HKG":["betfair","oddschk"],
    "UNK":["oddschk"],
}

def is_foreign(name):
    slug = name.lower().replace(" ","-")
    for d in DOMESTIC:
        if d in slug: return False
    return True

def detect_country(name):
    low = name.lower()
    for k, v in COUNTRY_MAP.items():
        if k in low: return v
    return "UNK"

def name_to_slug(name):
    """Hipodrom adini URL slug'a cevir: 'Mahoning Valley ABD' -> 'mahoning-valley-abd'"""
    import unicodedata
    s = name.lower().strip()
    # Turkce karakter donusumu
    tr = {"\u0131":"i","\u00e7":"c","\u015f":"s","\u011f":"g","\u00fc":"u","\u00f6":"o",
          "\u0130":"i","\u00c7":"c","\u015e":"s","\u011e":"g","\u00dc":"u","\u00d6":"o"}
    for old, new in tr.items():
        s = s.replace(old, new)
    s = re.sub(r"[^a-z0-9\s-]", "", s)
    s = re.sub(r"[\s]+", "-", s).strip("-")
    return s

def fetch_hippodromes():
    """agftahmin.com/at-yarisi sayfasindan bugunku hipodromlari al."""
    try:
        r = requests.get(BULTEN_URL, headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        hips = []
        for link in soup.find_all("a", href=True):
            href = link.get("href","")
            text = link.get_text(strip=True)
            if "/at-yarisi/" in href and "Bulten" in text:
                # Extract hipodrom adi: "Mahoning Valley ABD At Yarisi Bulteni" -> "Mahoning Valley ABD"
                name = text.replace("At Yarisi Bulteni","").replace("At Yarisi Bülteni","").strip()
                slug = href.split("/at-yarisi/")[-1].strip("/")
                if name and slug:
                    hips.append({"name":name, "slug":slug, "url":BASE+"/at-yarisi/"+slug})
        
        logger.info(f"agftahmin.com: {len(hips)} hipodrom bulundu")
        return hips
    except Exception as e:
        logger.error(f"Hipodrom listesi hatasi: {e}")
        return []

def fetch_racecard(slug):
    """Bir hipodromun yaris kartini agftahmin.com'dan cek.
    Temiz HTML tablolar, kolay parse."""
    url = f"{BASE}/at-yarisi/{slug}"
    try:
        r = requests.get(url, headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        races = []
        # Her tablo bir kosu
        tables = soup.find_all("table")
        
        for idx, table in enumerate(tables):
            horses = []
            rows = table.find_all("tr")
            
            # Header row'u atla
            for row in rows[1:]:
                cells = row.find_all("td")
                if len(cells) < 6: continue
                
                texts = [c.get_text(strip=True) for c in cells]
                
                try:
                    num = int(texts[0]) if texts[0].isdigit() else 0
                    name = texts[1].strip()
                    age = texts[2].strip() if len(texts) > 2 else ""
                    weight = texts[4].strip() if len(texts) > 4 else ""
                    jockey = texts[5].strip() if len(texts) > 5 else ""
                    trainer = texts[7].strip() if len(texts) > 7 else ""
                    form = texts[10].strip() if len(texts) > 10 else ""
                    
                    if name and num > 0:
                        horses.append({
                            "num": num,
                            "name": name,
                            "jockey": jockey,
                            "trainer": trainer,
                            "age": age,
                            "weight": weight,
                            "form": form,
                            "tjk": 0,  # AGF sonra eslestirilecek
                        })
                except (ValueError, IndexError):
                    continue
            
            if horses:
                # Kosu numarasi: tablonun ustundeki basliktan
                header = table.find_previous(["h3","h2","h4"])
                race_num = idx + 1
                race_time = ""
                if header:
                    ht = header.get_text(strip=True)
                    nm = re.search(r"(\d+)\.\s*[Kk]o", ht)
                    if nm: race_num = int(nm.group(1))
                    tm = re.search(r"(\d{2}[:\.\s]\d{2})", ht)
                    if tm: race_time = tm.group(1).replace(".",":").replace(" ",":")
                
                races.append({
                    "number": race_num,
                    "time": race_time,
                    "distance": "",
                    "type": "",
                    "pool_tl": 0,
                    "horses": horses,
                })
        
        logger.info(f"  {slug}: {len(races)} yaris, {sum(len(r['horses']) for r in races)} at")
        return races
    
    except Exception as e:
        logger.error(f"Yaris karti hatasi ({slug}): {e}")
        return []

def fetch_agf_all():
    """agftahmin.com/agf-tablosu'ndan TUM AGF oranlarini cek.
    Tek sayfa, tum hipodromlar. Format: at_numarasi (%yuzde)
    
    Returns: {hipodrom_adi: {kosu_num: {at_num: agf_yuzde}}}
    """
    try:
        r = requests.get(AGF_URL, headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        agf_data = {}
        current_hip = ""
        current_altili = ""
        
        # H3 basliklar: "2026-03-16 - 15:55 Chantilly Fransa AGF Tahmin 1. Altili"
        for section in soup.find_all("h3"):
            title = section.get_text(strip=True)
            
            # Hipodrom adini cikart
            # Format: "YYYY-MM-DD - HH:MM HipodromAdi AGF Tahmin N. Altili"
            m = re.search(r"\d{4}-\d{2}-\d{2}\s*-\s*\d{2}:\d{2}\s+(.+?)\s+AGF", title)
            if not m: continue
            hip_name = m.group(1).strip()
            
            # Altili numarasi
            alt_m = re.search(r"(\d+)\.\s*Alt", title)
            altili_num = int(alt_m.group(1)) if alt_m else 1
            
            if hip_name not in agf_data:
                agf_data[hip_name] = {}
            
            # Bu basliktan sonraki tablolari bul (AYAK tablolari)
            sibling = section.find_next_sibling()
            leg_num = 0
            
            while sibling:
                if sibling.name == "h3": break  # Sonraki hipodrom
                
                if sibling.name == "table" or (sibling.name == "div" and sibling.find("table")):
                    tbl = sibling if sibling.name == "table" else sibling.find("table")
                    if not tbl:
                        sibling = sibling.find_next_sibling()
                        continue
                    
                    leg_num += 1
                    leg_data = {}
                    
                    for row in tbl.find_all("tr"):
                        cell_text = row.get_text(strip=True)
                        # AYAK basligini atla
                        if "AYAK" in cell_text: continue
                        
                        # Format: "4 (%30.53)" veya "1 (%23.02)"
                        matches = re.findall(r"(\d+)\s*\(%?([\d\.]+)%?\)", cell_text)
                        for at_num_str, pct_str in matches:
                            try:
                                at_num = int(at_num_str)
                                pct = float(pct_str)
                                if 0 < pct <= 100:
                                    leg_data[at_num] = pct
                            except ValueError:
                                pass
                    
                    if leg_data:
                        # AGF yuzdesini odds'a cevir: odds = 100 / pct
                        kosu_key = f"altili{altili_num}_leg{leg_num}"
                        agf_data[hip_name][kosu_key] = leg_data
                
                sibling = sibling.find_next_sibling()
        
        logger.info(f"AGF data: {list(agf_data.keys())}")
        return agf_data
    
    except Exception as e:
        logger.error(f"AGF tablosu hatasi: {e}")
        return {}

def pct_to_odds(pct):
    """AGF yuzdesini TJK odds'a cevir. pct=25 -> odds=4.0"""
    if pct <= 0: return 0
    return round(100.0 / pct, 2)

def match_agf_to_races(races, agf_hip_data):
    """AGF oranlarini at numaralarina gore eslestir.
    
    AGF altili bacaklari = kosu sirasi. 
    1. altili genelde ilk 6 kosu, 2. altili son 6 kosu.
    """
    if not agf_hip_data: return
    
    # Basit eslestirme: kosu numarasina gore
    # AGF leg numaralari kosulara mapped
    for key, leg_data in agf_hip_data.items():
        # key: "altili1_leg3" -> altili 1, bacak 3
        m = re.match(r"altili(\d+)_leg(\d+)", key)
        if not m: continue
        altili = int(m.group(1))
        leg = int(m.group(2))
        
        # Altili 1 -> kosular 1-6 (veya 3-8), altili 2 -> kosular 5-10 (veya 7-12)
        # Basit mapping: leg N -> kosu N (1. altili) veya kosu N+offset (2. altili)
        # Gercek mapping hipodroma gore degisir, simdilik sirayla deneriz
        
        for race in races:
            # At numaralarina gore eslestir (agf at_num == race horse num)
            for at_num, pct in leg_data.items():
                for horse in race["horses"]:
                    if horse["num"] == at_num and horse["tjk"] == 0:
                        horse["tjk"] = pct_to_odds(pct)
                        horse["agf_pct"] = pct

def fetch_foreign_races(tarih=None):
    """ANA: Bugunku yabanci yarislari + AGF oranlarini dondur."""
    logger.info("agftahmin.com'dan yabanci yaris taramasi")
    
    # 1. Hipodromlari al
    hips = fetch_hippodromes()
    if not hips:
        logger.warning("Hipodrom bulunamadi")
        return []
    
    # 2. Yabancilari filtrele
    foreign = [h for h in hips if is_foreign(h["name"])]
    logger.info(f"Yabanci: {[h['name'] for h in foreign]}")
    
    if not foreign:
        logger.warning("Yabanci yaris yok")
        return []
    
    # 3. AGF tablolarini tek seferde cek
    agf_all = fetch_agf_all()
    
    # 4. Her yabanci hipodrom icin yaris karti cek
    results = []
    for hip in foreign:
        country = detect_country(hip["name"])
        races = fetch_racecard(hip["slug"])
        
        # AGF eslestir
        hip_agf = agf_all.get(hip["name"], {})
        if hip_agf and races:
            match_agf_to_races(races, hip_agf)
            # Eslestirme basariliysa log
            matched = sum(1 for r in races for h in r["horses"] if h.get("tjk",0) > 0)
            total = sum(len(r["horses"]) for r in races)
            logger.info(f"  AGF eslestirme: {matched}/{total} at")
        
        results.append({
            "id": hip["slug"],
            "name": hip["name"],
            "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races,
        })
    
    return results
