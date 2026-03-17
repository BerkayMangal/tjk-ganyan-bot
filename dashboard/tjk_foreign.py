# -*- coding: utf-8 -*-
"""
TJK Yabanci Yaris Scraper v3 — agftahmin.com
Temiz HTML, JS yok, Turkce karakter sorunu cozuldu.
"""
import requests, re, logging
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

BASE = "https://www.agftahmin.com"
HDR = {"User-Agent":"Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}

DOMESTIC_SLUGS = ["adana","bursa","istanbul","ankara","izmir","elazig",
                  "sanliurfa","diyarbakir","antalya","kocaeli","samsun"]

COUNTRY_MAP = {"abd":"USA","fransa":"FRA","ingiltere":"GBR",
    "avustralya":"AUS","dubai":"UAE","bae":"UAE","malezya":"MYS",
    "singapur":"SGP","hong-kong":"HKG","japonya":"JPN"}

FLAGS = {"USA":"\U0001f1fa\U0001f1f8","FRA":"\U0001f1eb\U0001f1f7","GBR":"\U0001f1ec\U0001f1e7",
         "AUS":"\U0001f1e6\U0001f1fa","UAE":"\U0001f1e6\U0001f1ea","HKG":"\U0001f1ed\U0001f1f0",
         "JPN":"\U0001f1ef\U0001f1f5","UNK":"\U0001f3c1"}

SOURCE_MAP = {"USA":["twinspires","betfair","oddschk"],"FRA":["betfair_uk","oddschk"],
    "GBR":["betfair_uk","oddschk"],"AUS":["tab_au","betfair","oddschk"],
    "UAE":["betfair_uk","oddschk"],"HKG":["betfair","oddschk"],"UNK":["oddschk"]}


def is_foreign_slug(slug):
    """Slug yerli mi yabanci mi?"""
    for d in DOMESTIC_SLUGS:
        if d in slug:
            return False
    return True


def detect_country(slug):
    for k, v in COUNTRY_MAP.items():
        if k in slug:
            return v
    return "UNK"


def slug_to_name(slug):
    """'mahoning-valley-abd' -> 'Mahoning Valley ABD'"""
    parts = slug.split("-")
    return " ".join(p.upper() if p in ["abd","bae","uk"] else p.capitalize() for p in parts)


def fetch_hippodromes():
    """agftahmin.com/at-yarisi sayfasindan bugunku hipodromlari al.
    
    Sayfa yapisi (gercek HTML'den):
      <a href="https://www.agftahmin.com/at-yarisi/mahoning-valley-abd">
        Mahoning Valley ABD At Yarisi Bulteni
      </a>
    
    NOT: "Bulteni" Turkce u ile "B\xfclteni" olabilir.
    Bu yuzden text'e bakmiyoruz, sadece href yapisina bakiyoruz.
    """
    try:
        r = requests.get(f"{BASE}/at-yarisi", headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        hips = []
        seen = set()
        
        for link in soup.find_all("a", href=True):
            href = link.get("href", "")
            
            # /at-yarisi/SLUG formatindaki linkleri bul
            # Hem relative (/at-yarisi/xxx) hem absolute (https://...com/at-yarisi/xxx) destekle
            match = re.search(r"/at-yarisi/([a-z0-9-]+)$", href)
            if not match:
                continue
            
            slug = match.group(1)
            
            # Gecersiz slug'lari atla
            if not slug or len(slug) < 3:
                continue
            if slug in seen:
                continue
            # Sorting/filtering parametreleri atla
            if "siralama" in slug or "sayfa" in slug:
                continue
                
            seen.add(slug)
            name = slug_to_name(slug)
            hips.append({"name": name, "slug": slug})
        
        logger.info(f"agftahmin.com: {len(hips)} hipodrom: {[h['slug'] for h in hips]}")
        return hips
        
    except Exception as e:
        logger.error(f"Hipodrom listesi hatasi: {e}")
        return []


def fetch_racecard(slug):
    """Bir hipodromun yaris kartini cek. Her tablo = bir kosu."""
    url = f"{BASE}/at-yarisi/{slug}"
    try:
        r = requests.get(url, headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        races = []
        tables = soup.find_all("table")
        
        for idx, table in enumerate(tables):
            horses = []
            rows = table.find_all("tr")
            
            for row in rows[1:]:  # Header atla
                cells = row.find_all("td")
                if len(cells) < 6:
                    continue
                
                texts = [c.get_text(strip=True) for c in cells]
                
                try:
                    num = int(texts[0]) if texts[0].isdigit() else 0
                    name = texts[1].strip()
                    jockey = texts[5].strip() if len(texts) > 5 else ""
                    trainer = texts[7].strip() if len(texts) > 7 else ""
                    form = texts[10].strip() if len(texts) > 10 else ""
                    
                    if name and num > 0:
                        horses.append({
                            "num": num,
                            "name": name,
                            "jockey": jockey,
                            "trainer": trainer,
                            "form": form,
                            "tjk": 0,
                        })
                except (ValueError, IndexError):
                    continue
            
            if horses:
                # Kosu numarasi basliktan
                header = table.find_previous("h3")
                race_num = idx + 1
                if header:
                    nm = re.search(r"(\d+)\.", header.get_text())
                    if nm:
                        race_num = int(nm.group(1))
                
                races.append({
                    "number": race_num,
                    "time": "",
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
    """AGF tablolarini tek seferde cek.
    
    H3 format: '2026-03-16 - 15:55 Chantilly Fransa AGF Tahmin 1. Altili'
    Tablo format: '4 (%30.53)' veya '1 (%23.02)'
    
    Returns: {slug: {kosu_idx: {at_num: agf_pct}}}
    """
    try:
        r = requests.get(f"{BASE}/agf-tablosu", headers=HDR, timeout=15)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        
        agf_data = {}
        
        for h3 in soup.find_all("h3"):
            title = h3.get_text(strip=True)
            
            # "2026-03-16 - 11:30 Adana AGF Tahmin 2. Altili" formatini parse et
            m = re.search(r"\d{4}-\d{2}-\d{2}\s*-\s*[\d:]+\s+(.+?)\s+AGF", title)
            if not m:
                continue
            
            hip_name = m.group(1).strip()
            
            # Altili numarasi
            alt_m = re.search(r"(\d+)\.", title.split("AGF")[-1])
            altili_num = int(alt_m.group(1)) if alt_m else 1
            
            if hip_name not in agf_data:
                agf_data[hip_name] = {}
            
            # H3'ten sonraki tablolari tara (her tablo = 1 ayak)
            elem = h3.find_next_sibling()
            leg = 0
            
            while elem:
                if elem.name == "h3":
                    break  # Sonraki hipodrom
                
                tbl = None
                if elem.name == "table":
                    tbl = elem
                elif elem.find("table"):
                    tbl = elem.find("table")
                
                if tbl:
                    leg += 1
                    leg_data = {}
                    
                    for row in tbl.find_all("tr"):
                        txt = row.get_text(strip=True)
                        if "AYAK" in txt:
                            continue
                        # "4 (%30.53)" formatini yakala
                        for at_str, pct_str in re.findall(r"(\d+)\s*\(?%?([\d.]+)%?\)?", txt):
                            try:
                                at_num = int(at_str)
                                pct = float(pct_str)
                                if 0 < pct <= 100 and 0 < at_num <= 30:
                                    leg_data[at_num] = pct
                            except ValueError:
                                pass
                    
                    if leg_data:
                        key = f"a{altili_num}_l{leg}"
                        agf_data[hip_name][key] = leg_data
                
                elem = elem.find_next_sibling()
        
        total_legs = sum(len(v) for v in agf_data.values())
        logger.info(f"AGF: {list(agf_data.keys())} ({total_legs} ayak toplam)")
        return agf_data
    
    except Exception as e:
        logger.error(f"AGF hatasi: {e}")
        return {}


def match_agf_to_races(races, hip_agf):
    """AGF yuzdeleri -> races[horse][tjk] odds olarak eslestir.
    
    AGF'de at numarasi var, race'lerde de at numarasi var.
    Eslestirme: ayni numara = ayni at.
    AGF pct -> odds: odds = 100 / pct
    """
    if not hip_agf:
        return
    
    # Tum leg data'larini topla
    all_legs = []
    for key in sorted(hip_agf.keys()):
        all_legs.append(hip_agf[key])
    
    # Her race'e sirali eslestir
    for i, race in enumerate(races):
        if i >= len(all_legs):
            break
        
        leg_data = all_legs[i]
        matched = 0
        
        for horse in race["horses"]:
            pct = leg_data.get(horse["num"], 0)
            if pct > 0:
                horse["tjk"] = round(100.0 / pct, 2)
                horse["agf_pct"] = pct
                matched += 1
        
        if matched > 0:
            logger.info(f"    R{race['number']}: {matched}/{len(race['horses'])} at AGF eslestirildi")


def fetch_foreign_races(tarih=None):
    """ANA: Yabanci yarislari + AGF cek, analiz icin hazirla."""
    logger.info("agftahmin.com tarama basliyor")
    
    # 1. Hipodromlari al
    hips = fetch_hippodromes()
    if not hips:
        logger.warning("Hipodrom bulunamadi")
        return []
    
    # 2. Yabancilari filtrele
    foreign = [h for h in hips if is_foreign_slug(h["slug"])]
    logger.info(f"Yabanci: {[h['name'] for h in foreign]}")
    
    if not foreign:
        logger.warning("Yabanci yaris yok")
        return []
    
    # 3. AGF tablolarini tek seferde cek
    agf_all = fetch_agf_all()
    
    # 4. Her yabanci hipodrom icin yaris karti cek
    results = []
    for hip in foreign:
        country = detect_country(hip["slug"])
        races = fetch_racecard(hip["slug"])
        
        # AGF eslestir — hip name ile AGF basligini match et
        # AGF baslik: "Chantilly Fransa", hip name: "Chantilly Fransa"
        hip_agf = agf_all.get(hip["name"], {})
        
        # Fuzzy fallback: slug ile baslik eslestir
        if not hip_agf:
            for agf_name, agf_data in agf_all.items():
                # "Chantilly Fransa" -> "chantilly-fransa" ve karsilastir
                agf_slug = agf_name.lower().replace(" ","-")
                agf_slug = re.sub(r"[^a-z0-9-]", "", agf_slug)
                if hip["slug"] in agf_slug or agf_slug in hip["slug"]:
                    hip_agf = agf_data
                    logger.info(f"  AGF fuzzy match: {agf_name} -> {hip['slug']}")
                    break
        
        if hip_agf and races:
            match_agf_to_races(races, hip_agf)
        
        results.append({
            "id": hip["slug"],
            "name": hip["name"],
            "country": country,
            "flag": FLAGS.get(country, FLAGS["UNK"]),
            "sources": SOURCE_MAP.get(country, SOURCE_MAP["UNK"]),
            "races": races,
        })
    
    logger.info(f"Toplam: {len(results)} yabanci hipodrom, "
                f"{sum(len(r) for t in results for r in t['races'])} yaris")
    return results
