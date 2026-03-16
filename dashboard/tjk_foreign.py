"""
TJK Yabanci Yaris Scraper — Dashboard icinde
tjk.org'dan yabanci yarislari + AGF oranlarini ceker.
"""
import requests, re, logging
from datetime import datetime
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)
TJK_PROGRAM = "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami"
TJK_AGF = "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukAgfTablosu"
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DOMESTIC = ["ADANA","BURSA","ISTANBUL","ANKARA","IZMIR","ELAZIG",
            "SANLIURFA","DIYARBAKIR","ANTALYA","KOCAELI","SAMSUN"]

COUNTRY_MAP = {"ABD":"USA","Fransa":"FRA","Ingiltere":"GBR","UK":"GBR",
    "Avustralya":"AUS","Dubai":"UAE","BAE":"UAE","Malezya":"MYS",
    "Singapur":"SGP","Hong Kong":"HKG","Japonya":"JPN"}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","MYS":"\U0001f1f2\U0001f1fe","SGP":"\U0001f1f8\U0001f1ec",
         "ZAF":"\U0001f1ff\U0001f1e6","UNK":"\U0001f3c1"}

SOURCE_MAP = {"USA":["twinspires","betfair","oddschk"],"FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"],"AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"],"HKG":["betfair","oddschk"],"UNK":["oddschk"]}

def get_today():
    return datetime.now().strftime("%d/%m/%Y")

def is_foreign(name):
    for d in DOMESTIC:
        if d in name.upper(): return False
    return True

def detect_country(name):
    for k, v in COUNTRY_MAP.items():
        if k.upper() in name.upper(): return v
    return "UNK"

def fuzzy(n1, n2, th=0.6):
    r = SequenceMatcher(None, n1.upper().strip(), n2.upper().strip()).ratio()
    return r if r >= th else 0.0

def fetch_program(tarih=None):
    if not tarih: tarih = get_today()
    try:
        r = requests.get(f"{TJK_PROGRAM}?QueryParameter_Tarih={tarih}", headers=HDR, timeout=15)
        r.raise_for_status()
        return r.text
    except Exception as e:
        logger.error(f"TJK program hatasi: {e}")
        return None

def extract_foreign(html):
    soup = BeautifulSoup(html, "html.parser")
    hips = []
    seen = set()
    for link in soup.find_all("a", href=True):
        href = link.get("href","")
        m = re.search(r"SehirAdi=([^&]+)", href)
        if m:
            sehir = requests.utils.unquote(m.group(1))
            if is_foreign(sehir) and sehir not in seen:
                seen.add(sehir)
                hips.append({"name":sehir, "url":"https://www.tjk.org"+href if href.startswith("/") else href})
    return hips

def fetch_racecard(hip, tarih=None):
    if not tarih: tarih = get_today()
    enc = requests.utils.quote(hip)
    try:
        r = requests.get(f"{TJK_PROGRAM}?QueryParameter_Tarih={tarih}&SehirAdi={enc}", headers=HDR, timeout=15)
        r.raise_for_status()
        return parse_races(r.text)
    except Exception as e:
        logger.error(f"Yaris karti hatasi ({hip}): {e}")
        return []

def parse_races(html):
    soup = BeautifulSoup(html, "html.parser")
    races = []
    
    # TJK kosu basliklari
    headers = soup.find_all(string=re.compile(r"\d+\.\s*[Kk]o[sş]"))
    if not headers:
        headers = soup.find_all(["h2","h3","div","span"], string=re.compile(r"\d+"))
    
    tables = soup.find_all("table")
    race_num = 0
    
    for table in tables:
        rows = table.find_all("tr")
        horses = []
        
        for row in rows:
            cells = row.find_all(["td"])
            if len(cells) < 3: continue
            texts = [c.get_text(strip=True) for c in cells]
            
            num = 0
            name = ""
            jockey = ""
            
            # Numara bul
            for t in texts:
                if t.isdigit() and 0 < int(t) <= 30 and num == 0:
                    num = int(t)
                    break
            
            # At ismi bul (en uzun non-numeric text)
            candidates = [(i,t) for i,t in enumerate(texts) if len(t) > 2 and not t.isdigit()
                         and t not in ["Forma","N","At Ismi","Yas","Orijin","Siklet","Jokey","Sahip"]]
            if candidates:
                name = candidates[0][1]
            
            # Jokey (genelde 6-7. hucre)
            if len(texts) >= 7:
                for j in range(5, min(9, len(texts))):
                    if len(texts[j]) > 2 and not texts[j].isdigit() and texts[j] != name:
                        jockey = texts[j]
                        break
            
            if name and num > 0:
                horses.append({"num":num,"name":name,"jockey":jockey})
        
        if horses:
            race_num += 1
            # Zaman bilgisi bulmaya calis
            prev = table.find_previous(string=re.compile(r"\d{2}:\d{2}"))
            race_time = ""
            if prev:
                tm = re.search(r"(\d{2}:\d{2})", str(prev))
                if tm: race_time = tm.group(1)
            
            races.append({"number":race_num,"time":race_time,"distance":"","type":"","pool_tl":0,"horses":horses})
    
    return races

def fetch_agf(hip, tarih=None):
    if not tarih: tarih = get_today()
    enc = requests.utils.quote(hip)
    try:
        r = requests.get(f"{TJK_AGF}?QueryParameter_Tarih={tarih}&SehirAdi={enc}", headers=HDR, timeout=15)
        r.raise_for_status()
        return parse_agf(r.text)
    except Exception as e:
        logger.error(f"AGF hatasi ({hip}): {e}")
        return {}

def parse_agf(html):
    soup = BeautifulSoup(html, "html.parser")
    agf = {}
    for table in soup.find_all("table"):
        for row in table.find_all("tr"):
            cells = row.find_all(["td","th"])
            texts = [c.get_text(strip=True) for c in cells]
            for i, t in enumerate(texts):
                try:
                    val = float(t.replace(",","."))
                    if 1.01 < val < 500 and i > 0:
                        nm = texts[i-1]
                        if nm and len(nm) > 2 and not nm.replace(",","").replace(".","").isdigit():
                            agf[nm] = val
                except (ValueError, IndexError):
                    pass
    return agf

def fetch_foreign_races(tarih=None):
    """ANA: Bugunku yabanci yarislar + AGF."""
    if not tarih: tarih = get_today()
    logger.info(f"TJK yabanci tarama: {tarih}")
    
    html = fetch_program(tarih)
    if not html:
        logger.error("TJK sayfa alinamadi")
        return []
    
    foreign = extract_foreign(html)
    logger.info(f"Yabanci hipodromlar: {[h['name'] for h in foreign]}")
    
    if not foreign:
        logger.warning("Bugun yabanci yaris yok")
        return []
    
    results = []
    for hip in foreign:
        country = detect_country(hip["name"])
        races = fetch_racecard(hip["name"], tarih)
        agf = fetch_agf(hip["name"], tarih)
        
        # AGF eslestir
        if agf and races:
            for race in races:
                for h in race["horses"]:
                    if h["name"] in agf:
                        h["tjk"] = agf[h["name"]]
                    else:
                        best, best_o = 0, 0
                        for an, ao in agf.items():
                            s = fuzzy(h["name"], an)
                            if s > best: best, best_o = s, ao
                        h["tjk"] = best_o if best >= 0.6 else 0
        
        results.append({
            "id":hip["name"].lower().replace(" ","_"),
            "name":hip["name"],
            "country":country,
            "flag":FLAGS.get(country, FLAGS["UNK"]),
            "sources":SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races":races,
        })
        logger.info(f"  {hip['name']} ({country}): {len(races)} yaris")
    
    return results
