"""
TJK Program Scraper — PDF CDN Version
=======================================
TJK sitesi 403 verdiği için medya-cdn.tjk.org'dan PDF çeker.
main.py ile aynı interface'i korur.

PDF Pattern:
https://medya-cdn.tjk.org/raporftp/TJKPDF/{YYYY}/{YYYY-MM-DD}/PDFOzet/GunlukYarisProgrami/{DD.MM.YYYY}-{Sehir}-GunlukYarisProgrami-TR.pdf
"""
import requests
import pdfplumber
import re
import io
import os
import logging
from datetime import date, datetime
from typing import Optional, List, Dict

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

TJK_CDN_BASE = "https://medya-cdn.tjk.org/raporftp/TJKPDF"

HIPODROM_MAP = {
    "Istanbul":   ["İstanbul", "istanbul"],
    "Ankara":     ["Ankara", "ankara"],
    "Izmir":      ["İzmir", "izmir"],
    "Bursa":      ["Bursa", "bursa"],
    "Adana":      ["Adana", "adana"],
    "Elazig":     ["Elazığ", "elazig"],
    "Diyarbakir": ["Diyarbakır", "diyarbakir"],
    "Sanliurfa":  ["Şanlıurfa", "sanliurfa"],
    "Antalya":    ["Antalya", "antalya"],
    "Kocaeli":    ["Kocaeli", "kocaeli"],
}

# Display names for Telegram messages
DISPLAY_NAMES = {
    "Istanbul": "İstanbul",
    "Ankara": "Ankara",
    "Izmir": "İzmir",
    "Bursa": "Bursa",
    "Adana": "Adana",
    "Elazig": "Elazığ",
    "Diyarbakir": "Diyarbakır",
    "Sanliurfa": "Şanlıurfa",
    "Antalya": "Antalya",
    "Kocaeli": "Kocaeli",
}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'application/pdf,*/*',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8',
})

CACHE_DIR = os.path.join(os.path.dirname(__file__), '..', 'data', 'pdf_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# PDF URL + DOWNLOAD
# ═══════════════════════════════════════════════════════════════

def _build_pdf_url(dt: date, hipodrom_url: str) -> str:
    yyyy = dt.strftime("%Y")
    yyyy_mm_dd = dt.strftime("%Y-%m-%d")
    dd_mm_yyyy = dt.strftime("%d.%m.%Y")
    return (
        f"{TJK_CDN_BASE}/{yyyy}/{yyyy_mm_dd}/PDFOzet/"
        f"GunlukYarisProgrami/{dd_mm_yyyy}-{hipodrom_url}-GunlukYarisProgrami-TR.pdf"
    )


def _download_pdf(dt: date, hipodrom_url: str) -> Optional[bytes]:
    url = _build_pdf_url(dt, hipodrom_url)
    cache_key = url.split("/")[-1]
    cache_path = os.path.join(CACHE_DIR, cache_key)

    if os.path.exists(cache_path):
        logger.info(f"PDF cache hit: {cache_key}")
        with open(cache_path, "rb") as f:
            return f.read()

    logger.info(f"PDF downloading: {url}")
    try:
        resp = SESSION.get(url, timeout=30)
        if resp.status_code == 200:
            ct = resp.headers.get('content-type', '')
            if 'pdf' in ct or len(resp.content) > 10000:
                with open(cache_path, "wb") as f:
                    f.write(resp.content)
                logger.info(f"PDF OK: {len(resp.content)} bytes")
                return resp.content
        logger.debug(f"PDF not found: {resp.status_code} {url}")
        return None
    except Exception as e:
        logger.warning(f"PDF download error: {e}")
        return None


def _discover_hipodromlar(dt: date) -> List[str]:
    """HEAD request ile hangi hipodromlarda yarış var bul."""
    found = []
    for hip_url in HIPODROM_MAP.keys():
        url = _build_pdf_url(dt, hip_url)
        try:
            resp = SESSION.head(url, timeout=10)
            if resp.status_code == 200:
                found.append(hip_url)
                logger.info(f"Found races at {hip_url}")
        except Exception:
            pass
    return found


# ═══════════════════════════════════════════════════════════════
# PDF PARSER
# ═══════════════════════════════════════════════════════════════

def _parse_pdf(pdf_bytes: bytes, hipodrom_url: str, dt: date) -> Optional[Dict]:
    """
    PDF'den hipodrom verisini çıkar.

    Returns main.py'nin beklediği format:
    {
        'hippodrome': 'İstanbul Hipodromu',
        'date': '09.03.2026',
        'races': [
            {
                'race_number': 1,
                'distance': 1200,
                'group_name': '3 Yaş Maiden (Arap)',
                'track_type': 'Kum',
                'prize': 150000,
                'time': '13:00',
                'horses': [
                    {
                        'horse_number': 1,
                        'horse_name': 'STORM RUNNER',
                        'age': 4,
                        'weight': 57.0,
                        'jockey_name': 'A.Çelik',
                        'trainer_name': 'M.Kaya',
                        'owner_name': 'Ahmet Bey',
                        'sire_name': 'Bold Runner',
                        'dam_name': 'Storm Lady',
                        'form': '1-3-2-5-0-1',
                        'handicap_rating': 0,
                    },
                    ...
                ]
            },
            ...
        ]
    }
    """
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            logger.info(f"PDF opened: {len(pdf.pages)} pages")

            all_text = []
            all_tables = []

            for page_num, page in enumerate(pdf.pages):
                text = page.extract_text() or ""
                all_text.append(text)

                tables = page.extract_tables() or []
                for table in tables:
                    all_tables.append({'page': page_num + 1, 'data': table})

            full_text = "\n".join(all_text)

            # Parse races from text
            races = _parse_races_text(full_text)

            # Enrich from tables
            if all_tables:
                _enrich_from_tables(races, all_tables)

            if not races:
                logger.warning(f"No races parsed from PDF ({hipodrom_url})")
                return None

            display_name = DISPLAY_NAMES.get(hipodrom_url, hipodrom_url)
            date_str = dt.strftime("%d.%m.%Y")

            logger.info(f"Parsed {len(races)} races, "
                       f"{sum(len(r['horses']) for r in races)} horses total")

            return {
                'hippodrome': f"{display_name} Hipodromu",
                'date': date_str,
                'races': races,
            }

    except Exception as e:
        logger.error(f"PDF parse error: {e}")
        import traceback
        traceback.print_exc()
        return None


def _parse_races_text(text: str) -> List[Dict]:
    """Text'den koşuları çıkar."""
    races = []

    race_header_patterns = [
        r'(\d+)\s*\.\s*KOŞU',
        r'KOŞU\s*[\-:]\s*(\d+)',
        r'(\d+)\s*\.\s*[Kk]oşu',
    ]

    saat_pat = r'(?:Saat|SAAT|saat)\s*[:\-]?\s*(\d{2}[:.]\d{2})'
    mesafe_pat = r'(?:Mesafe|MES\.?|mesafe)\s*[:\-]?\s*(\d{3,4})\s*(?:m|M)?'
    pist_pat = r'(?:Pist|PİST|pist)\s*[:\-]?\s*(Çim|Kum|Sentetik|çim|kum|sentetik|ÇİM|KUM|SENTETİK)'
    ikramiye_pat = r'(?:İkramiye|IKRAMIYE|ikramiye)\s*[:\-]?\s*([\d.,]+)\s*(?:TL)?'
    grup_pat = r'(?:Grup|GRUP|grup)\s*[:\-]?\s*(.+?)(?:\s{2,}|$)'

    lines = text.split('\n')
    current_race = None
    horse_lines = []

    for line in lines:
        line = line.strip()
        if not line:
            continue

        # Race header?
        race_match = None
        for pat in race_header_patterns:
            m = re.search(pat, line)
            if m:
                race_match = m
                break

        if race_match:
            # Save previous race
            if current_race is not None:
                current_race['horses'] = _parse_horse_lines(horse_lines)
                if current_race['horses']:
                    races.append(current_race)
                horse_lines = []

            kosu_no = int(race_match.group(1))
            current_race = {
                'race_number': kosu_no,
                'distance': 0,
                'group_name': '',
                'track_type': '',
                'prize': 0,
                'time': '',
                'horses': [],
            }

            # Extract info from same line
            m = re.search(saat_pat, line)
            if m:
                current_race['time'] = m.group(1).replace('.', ':')

            m = re.search(mesafe_pat, line)
            if m:
                current_race['distance'] = int(m.group(1))

            m = re.search(pist_pat, line, re.IGNORECASE)
            if m:
                current_race['track_type'] = m.group(1).capitalize()

            m = re.search(ikramiye_pat, line)
            if m:
                current_race['prize'] = float(m.group(1).replace('.', '').replace(',', '.'))

            m = re.search(grup_pat, line)
            if m:
                current_race['group_name'] = m.group(1).strip()

            continue

        # Inside a race
        if current_race is not None:
            # Horse line? (starts with number)
            if re.match(r'^\s*\d{1,2}\s', line):
                horse_lines.append(line)
            else:
                # Extra race info on following lines
                if not current_race['time']:
                    m = re.search(saat_pat, line)
                    if m:
                        current_race['time'] = m.group(1).replace('.', ':')

                if not current_race['distance']:
                    m = re.search(mesafe_pat, line)
                    if m:
                        current_race['distance'] = int(m.group(1))

                if not current_race['track_type']:
                    m = re.search(pist_pat, line, re.IGNORECASE)
                    if m:
                        current_race['track_type'] = m.group(1).capitalize()

                if not current_race['group_name']:
                    m = re.search(grup_pat, line)
                    if m:
                        current_race['group_name'] = m.group(1).strip()

    # Save last race
    if current_race is not None:
        current_race['horses'] = _parse_horse_lines(horse_lines)
        if current_race['horses']:
            races.append(current_race)

    return races


def _parse_horse_lines(lines: List[str]) -> List[Dict]:
    """At satırlarını main.py'nin beklediği dict formatında parse et."""
    horses = []
    for line in lines:
        h = _parse_one_horse(line)
        if h:
            horses.append(h)
    return horses


def _parse_one_horse(line: str) -> Optional[Dict]:
    """Tek at satırı → dict."""
    if len(line.strip()) < 5:
        return None

    parts = line.split()
    if len(parts) < 2:
        return None

    try:
        no = int(parts[0])
    except ValueError:
        return None

    if no < 1 or no > 20:
        return None

    # Horse name: collect non-numeric parts after number
    name_parts = []
    idx = 1
    while idx < len(parts):
        if re.match(r'^\d+\.?\d*$', parts[idx]):
            break
        if re.match(r'^[2-9]$', parts[idx]) and idx > 1:
            break
        name_parts.append(parts[idx])
        idx += 1

    name = " ".join(name_parts).strip()
    if not name:
        return None

    remaining = parts[idx:]

    # Age
    age = 0
    for p in remaining:
        if re.match(r'^[2-9]$', p):
            age = int(p)
            break

    # Weight
    weight = 0.0
    for p in remaining:
        if re.match(r'^\d{2}\.\d$', p):
            weight = float(p)
            break
        elif re.match(r'^\d{2}$', p):
            v = int(p)
            if 48 <= v <= 62:
                weight = float(v)
                break

    # Form (son 6)
    form = ''
    for p in remaining:
        if re.match(r'^[\d\-]{5,}$', p) and '-' in p:
            form = p
            break

    # Jockey — text after weight, before form
    jockey = ''
    found_weight = False
    for p in remaining:
        if re.match(r'^\d{2}\.?\d?$', p):
            found_weight = True
            continue
        if found_weight and not re.match(r'^[\d\-]+$', p):
            jockey = p
            break

    return {
        'horse_number': no,
        'horse_name': name,
        'age': age,
        'weight': weight,
        'jockey_name': jockey,
        'trainer_name': '',
        'owner_name': '',
        'sire_name': '',
        'dam_name': '',
        'form': form,
        'handicap_rating': 0,
    }


def _enrich_from_tables(races: List[Dict], tables: List[Dict]):
    """pdfplumber tablolarından at bilgilerini zenginleştir."""
    for table_info in tables:
        data = table_info['data']
        if not data or len(data) < 2:
            continue

        header = [str(c).strip().lower() if c else "" for c in data[0]]

        # Is this a horse table?
        horse_keywords = ['no', 'at', 'ad', 'yaş', 'kg', 'kilo', 'jokey']
        if not any(any(kw in h for kw in horse_keywords) for h in header if h):
            continue

        col_map = {}
        kw_map = {
            'no': ['no', '#', 'sıra'],
            'ad': ['at', 'ad', 'adı', 'isim', 'at adı'],
            'yas': ['yaş', 'yas'],
            'kg': ['kg', 'kilo', 'ağırlık'],
            'jokey': ['jokey', 'jockey', 'binici'],
            'sahip': ['sahip', 'sahibi'],
            'antrenor': ['antrenör', 'antrenor', 'ant.'],
            'baba': ['baba', 'sire'],
            'anne': ['anne', 'dam'],
            'form': ['son 6', 'son6', 'form', 'son altı'],
            'handikap': ['hp', 'handikap'],
        }

        for ci, h in enumerate(header):
            for fname, kws in kw_map.items():
                if any(k in h for k in kws):
                    col_map[fname] = ci
                    break

        for row in data[1:]:
            if not row or not any(row):
                continue

            no_idx = col_map.get('no', 0)
            no_val = str(row[no_idx]).strip() if row[no_idx] else ""
            if not no_val.isdigit():
                continue

            horse_no = int(no_val)

            # Find which race this belongs to (heuristic: page -> race)
            page = table_info['page']
            race_idx = min(page - 1, len(races) - 1)
            if race_idx < 0 or race_idx >= len(races):
                continue

            race = races[race_idx]

            # Find or create horse
            existing = None
            for h in race['horses']:
                if h['horse_number'] == horse_no:
                    existing = h
                    break

            if existing is None:
                existing = {
                    'horse_number': horse_no,
                    'horse_name': '',
                    'age': 0,
                    'weight': 0.0,
                    'jockey_name': '',
                    'trainer_name': '',
                    'owner_name': '',
                    'sire_name': '',
                    'dam_name': '',
                    'form': '',
                    'handicap_rating': 0,
                }
                race['horses'].append(existing)

            # Fill missing fields
            def _safe(r, i):
                return str(r[i]).strip() if i < len(r) and r[i] else ""

            if 'ad' in col_map and not existing['horse_name']:
                existing['horse_name'] = _safe(row, col_map['ad'])
            if 'yas' in col_map and not existing['age']:
                try: existing['age'] = int(_safe(row, col_map['yas']))
                except: pass
            if 'kg' in col_map and not existing['weight']:
                try: existing['weight'] = float(_safe(row, col_map['kg']).replace(',', '.'))
                except: pass
            if 'jokey' in col_map and not existing['jockey_name']:
                existing['jockey_name'] = _safe(row, col_map['jokey'])
            if 'sahip' in col_map and not existing['owner_name']:
                existing['owner_name'] = _safe(row, col_map['sahip'])
            if 'antrenor' in col_map and not existing['trainer_name']:
                existing['trainer_name'] = _safe(row, col_map['antrenor'])
            if 'baba' in col_map and not existing['sire_name']:
                existing['sire_name'] = _safe(row, col_map['baba'])
            if 'anne' in col_map and not existing['dam_name']:
                existing['dam_name'] = _safe(row, col_map['anne'])
            if 'form' in col_map and not existing['form']:
                existing['form'] = _safe(row, col_map['form'])
            if 'handikap' in col_map and not existing['handicap_rating']:
                try: existing['handicap_rating'] = int(_safe(row, col_map['handikap']))
                except: pass


# ═══════════════════════════════════════════════════════════════
# PUBLIC API — main.py bu iki fonksiyonu import eder
# ═══════════════════════════════════════════════════════════════

def get_todays_races(target_date: date = None) -> List[Dict]:
    """
    Günün yarış programını TJK CDN'den çek.

    Returns: list of hippodrome dicts (main.py beklediği format)
    """
    if target_date is None:
        target_date = date.today()

    dt = target_date
    date_str = dt.strftime("%d.%m.%Y")

    logger.info(f"Fetching TJK program for {date_str} (PDF CDN)")

    # Hangi hipodromlarda yarış var?
    hipodromlar = _discover_hipodromlar(dt)

    if not hipodromlar:
        logger.warning(f"No races found for {date_str}")
        return []

    logger.info(f"Found hippodromes: {hipodromlar}")

    results = []
    for hip_url in hipodromlar:
        pdf_bytes = _download_pdf(dt, hip_url)
        if not pdf_bytes:
            continue

        hippo_data = _parse_pdf(pdf_bytes, hip_url, dt)
        if hippo_data and hippo_data['races']:
            results.append(hippo_data)
            logger.info(f"  {hip_url}: {len(hippo_data['races'])} races, "
                       f"{sum(len(r['horses']) for r in hippo_data['races'])} horses")

    return results


def identify_altili_sequences(hippo_data: Dict) -> List[Dict]:
    """
    Hipodrom verisinden altılı ganyan dizilerini çıkar.
    Genelde son 6 koşu altılı ganyan olur.

    Returns: list of sequence dicts:
    {
        'hippodrome': 'İstanbul Hipodromu',
        'altili_no': 1,
        'races': [...last 6 races...]
    }
    """
    races = hippo_data.get('races', [])

    if len(races) < 6:
        logger.warning(f"{hippo_data.get('hippodrome', '?')}: Only {len(races)} races, need 6 for altili")
        return []

    # Son 6 koşu = altılı ganyan
    altili_races = races[-6:]

    return [{
        'hippodrome': hippo_data['hippodrome'],
        'altili_no': 1,
        'races': altili_races,
    }]
