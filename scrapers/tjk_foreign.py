"""
TJK Yabanci Yaris Scraper
tjk.org'dan yabanci yarislari ve AGF oranlarini ceker.
URL: tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami?QueryParameter_Tarih=DD/MM/YYYY&SehirAdi=HIPODROM
"""
import requests, re, json, logging
from datetime import datetime
from bs4 import BeautifulSoup
from difflib import SequenceMatcher

logger = logging.getLogger(__name__)

TJK_BASE = "https://www.tjk.org"
TJK_PROGRAM = "https://www.tjk.org/TR/YarisSever/Info/Page/GunlukYarisProgrami"
TJK_AGF = "https://www.tjk.org/TR/YarisSever/Info/Sehir/GunlukAgfTablosu"
HEADERS = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DOMESTIC = ["ADANA","BURSA","ISTANBUL","ANKARA","IZMIR","ELAZIG",
            "SANLIURFA","DIYARBAKIR","ANTALYA","KOCAELI","SAMSUN"]

COUNTRY_MAP = {
    "ABD":"USA","Fransa":"FRA","Ingiltere":"GBR","UK":"GBR",
    "Avustralya":"AUS","Dubai":"UAE","BAE":"UAE",
    "Malezya":"MYS","Singapur":"SGP","Hong Kong":"HKG",
    "Japonya":"JPN","Guney Afrika":"ZAF",
}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","MYS":"\U0001f1f2\U0001f1fe","SGP":"\U0001f1f8\U0001f1ec",
         "ZAF":"\U0001f1ff\U0001f1e6","UNK":"\U0001f3c1"}

SOURCE_MAP = {
    "USA":["twinspires","betfair","oddschk"],
    "FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"],
    "AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"],
    "HKG":["betfair","oddschk"],
    "UNK":["oddschk"],
}

def get_today():
    return datetime.now().strftime("%d/%m/%Y")

def is_foreign(name):
    for d in DOMESTIC:
        if d in name.upper():
            return False
    return True

def detect_country(name):
    for key, code in COUNTRY_MAP.items():
        if key.upper() in name.upper():
            return code
    return "UNK"

def fuzzy_match(n1, n2, threshold=0.6):
    r = SequenceMatcher(None, n1.upper().strip(), n2.upper().strip()).ratio()
    return r if r >= threshold else 0.0

def fetch_program_page(tarih=None):
    """TJK ana program sayfasini cek, yabanci hipodromlari bul."""
    if not tarih: tarih = get_today()
    url = f"{TJK_PROGRAM}?QueryParameter_Tarih={tarih}"
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return resp.text
    except Exception as e:
        logger.error(f"TJK program hatasi: {e}")
        return None

def extract_foreign_hippodromes(html):
    """HTML'den yabanci hipodromlari cikart."""
    soup = BeautifulSoup(html, "html.parser")
    hippodromes = []
    
    # TJK'da sehir linkleri
    for link in soup.find_all("a", href=True):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        match = re.search(r"SehirAdi=([^&]+)", href)
        if match:
            sehir = requests.utils.unquote(match.group(1))
            if is_foreign(sehir):
                full_url = TJK_BASE + href if href.startswith("/") else href
                hippodromes.append({"name": sehir, "display": text, "url": full_url})
    
    # Deduplicate
    seen = set()
    unique = []
    for h in hippodromes:
        if h["name"] not in seen:
            seen.add(h["name"])
            unique.append(h)
    
    return unique

def fetch_race_card(hippodrome, tarih=None):
    """Hipodrom yaris programini cek ve parse et."""
    if not tarih: tarih = get_today()
    encoded = requests.utils.quote(hippodrome)
    url = f"{TJK_PROGRAM}?QueryParameter_Tarih={tarih}&SehirAdi={encoded}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return parse_races(resp.text)
    except Exception as e:
        logger.error(f"Yaris karti hatasi ({hippodrome}): {e}")
        return []

def parse_races(html):
    """HTML'den yarislari ve atlari cikart."""
    soup = BeautifulSoup(html, "html.parser")
    races = []
    
    # TJK tablosundan atlari bul
    tables = soup.find_all("table")
    for table in tables:
        rows = table.find_all("tr")
        horses = []
        
        for row in rows[1:]:  # Header atla
            cells = row.find_all(["td","th"])
            if len(cells) < 5: continue
            texts = [c.get_text(strip=True) for c in cells]
            
            num = 0
            name = ""
            jockey = ""
            
            for i, t in enumerate(texts):
                if t.isdigit() and 0 < int(t) <= 30 and num == 0:
                    num = int(t)
                elif len(t) > 2 and not t.isdigit() and not name:
                    if t not in ["Forma","N","At","Yas","At Ismi"]:
                        name = t
            
            if len(texts) >= 7:
                for j in range(5, min(8, len(texts))):
                    if len(texts[j]) > 2 and not texts[j].isdigit():
                        jockey = texts[j]
                        break
            
            if name and num > 0:
                horses.append({"num":num, "name":name, "jockey":jockey})
        
        if horses:
            # Kosu numarasi
            header = table.find_previous(["h2","h3","div","span"], string=re.compile(r"\d+\.\s*[Kk]o"))
            race_num = 0
            race_time = ""
            if header:
                nm = re.search(r"(\d+)\.\s*[Kk]o", header.get_text())
                if nm: race_num = int(nm.group(1))
                tm = re.search(r"(\d{2}:\d{2})", header.get_text())
                if tm: race_time = tm.group(1)
            
            if race_num == 0:
                race_num = len(races) + 1
            
            races.append({"number":race_num, "time":race_time, "distance":"", "type":"", "pool_tl":0, "horses":horses})
    
    return races

def fetch_agf(hippodrome, tarih=None):
    """AGF oranlarini cek."""
    if not tarih: tarih = get_today()
    encoded = requests.utils.quote(hippodrome)
    url = f"{TJK_AGF}?QueryParameter_Tarih={tarih}&SehirAdi={encoded}"
    
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15)
        resp.raise_for_status()
        return parse_agf(resp.text)
    except Exception as e:
        logger.error(f"AGF hatasi ({hippodrome}): {e}")
        return {}

def parse_agf(html):
    """AGF tablosundan oranlari cikart. {at_ismi: oran}"""
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
                        name = texts[i-1] if i > 0 else ""
                        if name and len(name) > 2 and not name.replace(",","").replace(".","").isdigit():
                            agf[name] = val
                except (ValueError, IndexError):
                    pass
    
    return agf

def fetch_foreign_races(tarih=None):
    """ANA FONKSIYON: Bugunku yabanci yarislari ve AGF oranlarini dondur."""
    if not tarih: tarih = get_today()
    logger.info(f"TJK yabanci yaris taramasi: {tarih}")
    
    html = fetch_program_page(tarih)
    if not html:
        return []
    
    foreign_hips = extract_foreign_hippodromes(html)
    logger.info(f"Yabanci hipodromlar: {[h['name'] for h in foreign_hips]}")
    
    if not foreign_hips:
        return []
    
    results = []
    for hip in foreign_hips:
        country = detect_country(hip["name"])
        races = fetch_race_card(hip["name"], tarih)
        agf = fetch_agf(hip["name"], tarih)
        
        # AGF'yi atlara esle
        if agf and races:
            for race in races:
                for horse in race["horses"]:
                    if horse["name"] in agf:
                        horse["tjk"] = agf[horse["name"]]
                    else:
                        best = 0
                        best_odds = 0
                        for an, ao in agf.items():
                            s = fuzzy_match(horse["name"], an)
                            if s > best:
                                best = s
                                best_odds = ao
                        horse["tjk"] = best_odds if best >= 0.6 else 0
        
        results.append({
            "id": hip["name"].lower().replace(" ","_"),
            "name": hip["name"],
            "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races,
        })
        logger.info(f"  {hip['name']} ({country}): {len(races)} yaris")
    
    return results

if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    races = fetch_foreign_races()
    for t in races:
        print(f"\n{t['flag']} {t['name']} ({t['country']}): {len(t['races'])} yaris")
        for r in t["races"]:
            print(f"  R{r['number']}: {len(r['horses'])} at")
            for h in r["horses"][:3]:
                print(f"    {h['num']}. {h['name']} AGF:{h.get('tjk',0)}")
