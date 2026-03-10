"""
TJK HTML Scraper — Full Data from tjk.org
==========================================
PDF özet yetersiz (5/12 koşu, pedigree yok).
TJK web sayfası HER ŞEYİ veriyor:
  - 8 koşu (tam program)
  - Baba, Anne, Anababa (pedigree)
  - Jokey, Antrenör, Sahip
  - Form (Son 6 Yarış), HP, KGS, s20
  - Equipment, AGF, En İyi Derece

Fallback chain: HTML → CSV → Özet PDF (mevcut)

URL pattern:
  Main:   https://www.tjk.org/TR/yarissever/Info/Page/GunlukYarisProgrami
  Detail: https://www.tjk.org/TR/yarissever/Info/Sehir/GunlukYarisProgrami?SehirId={id}&QueryParameter_Tarih={date}&SehirAdi={city}&Era=today
  CSV:    https://medya-cdn.tjk.org/.../CSV/GunlukYarisProgrami/{date}-{city}-GunlukYarisProgrami-TR.csv
"""
import requests
import re
import csv
import io
import logging
from datetime import date, datetime
from typing import Optional, List, Dict
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# CONFIG
# ═══════════════════════════════════════════════════════════════

TJK_BASE = "https://www.tjk.org"
TJK_PROGRAM_URL = f"{TJK_BASE}/TR/yarissever/Info/Page/GunlukYarisProgrami"
TJK_DETAIL_URL = f"{TJK_BASE}/TR/yarissever/Info/Sehir/GunlukYarisProgrami"
TJK_CDN_BASE = "https://medya-cdn.tjk.org/raporftp/TJKPDF"

# TJK'nın SehirId'leri
SEHIR_IDS = {
    'Adana': 1, 'Ankara': 2, 'Bursa': 4, 'Diyarbakır': 5,
    'Elazığ': 6, 'İstanbul': 7, 'İzmir': 8, 'Kocaeli': 9,
    'Antalya': 10, 'Şanlıurfa': 11,
}

# Reverse mapping for display names
SEHIR_DISPLAY = {v: k for k, v in SEHIR_IDS.items()}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8',
})


# ═══════════════════════════════════════════════════════════════
# STEP 1: DISCOVER HIPPODROMES
# ═══════════════════════════════════════════════════════════════

def _discover_hippodromes(target_date):
    """Ana sayfadan bugün yarış olan Türkiye hipodromlarını bul."""
    date_str = target_date.strftime('%d/%m/%Y')
    url = f"{TJK_PROGRAM_URL}?QueryParameter_Tarih={date_str}&Era=today"

    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')

        hippodromes = []
        # Hipodrom linkleri: "SehirId=X" içerenler
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'SehirId=' not in href:
                continue
            # Sadece Türkiye hipodromları (yabancıları atla)
            text = link.get_text(strip=True)
            if any(x in text for x in ['ABD', 'Fransa', 'Afrika', 'Birleşik']):
                continue

            sehir_match = re.search(r'SehirId=(\d+)', href)
            name_match = re.search(r'SehirAdi=([^&]+)', href)
            if sehir_match:
                sehir_id = int(sehir_match.group(1))
                sehir_name = name_match.group(1) if name_match else str(sehir_id)
                # URL decode
                from urllib.parse import unquote
                sehir_name = unquote(sehir_name)
                hippodromes.append({
                    'sehir_id': sehir_id,
                    'sehir_name': sehir_name,
                    'display_text': text,
                })

        # Deduplicate by sehir_id
        seen = set()
        unique = []
        for h in hippodromes:
            if h['sehir_id'] not in seen:
                seen.add(h['sehir_id'])
                unique.append(h)

        logger.info(f"HTML: {len(unique)} Türkiye hipodromu bulundu: "
                    f"{[h['sehir_name'] for h in unique]}")
        return unique

    except Exception as e:
        logger.warning(f"HTML hippodrome discovery failed: {e}")
        return []


# ═══════════════════════════════════════════════════════════════
# STEP 2: PARSE HIPPODROME DETAIL PAGE
# ═══════════════════════════════════════════════════════════════

def _fetch_hippodrome_html(sehir_id, sehir_name, target_date):
    """Bir hipodromun detay sayfasını çek."""
    date_str = target_date.strftime('%d/%m/%Y')
    url = (f"{TJK_DETAIL_URL}?SehirId={sehir_id}"
           f"&QueryParameter_Tarih={date_str}"
           f"&SehirAdi={sehir_name}&Era=today")

    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        logger.info(f"HTML page fetched for {sehir_name}: {len(resp.text)} chars")
        return resp.text
    except Exception as e:
        logger.warning(f"HTML fetch failed for {sehir_name}: {e}")
        return None


def _parse_hippodrome_html(html_text, sehir_name):
    """HTML'den koşu + at bilgilerini parse et."""
    soup = BeautifulSoup(html_text, 'html.parser')
    races = []

    # Her koşu bir <h3> başlığı + <table> ile tanımlı
    # Koşu başlıkları: "1. Koşu:14.30", "2. Koşu 15.00" vs.
    # Tablo: <table> içinde at satırları

    # Find all tables that have horse data (with AGF column etc.)
    tables = soup.find_all('table')

    race_headers = []
    # Find race header elements
    for h3 in soup.find_all('h3'):
        text = h3.get_text(strip=True)
        # Match "N. Koşu" or "N. Koşu:HH.MM"
        m = re.match(r'(\d+)\.\s*Koşu[:\s]*(\d{2}[.:]\d{2})?', text)
        if m:
            race_num = int(m.group(1))
            race_time = m.group(2).replace('.', ':') if m.group(2) else ''
            race_headers.append({
                'race_number': race_num,
                'time': race_time,
                'element': h3,
            })

    # Also look for race info in h3 siblings (race type, distance, track)
    for rh in race_headers:
        # The race type/distance info is usually in the next h3 sibling
        next_h3 = rh['element'].find_next('h3')
        if next_h3:
            info_text = next_h3.get_text(strip=True)
            # Extract distance
            dist_m = re.search(r'(\d{3,4})\s*(Kum|Çim|Sentetik)', info_text, re.IGNORECASE)
            if dist_m:
                rh['distance'] = int(dist_m.group(1))
                rh['track_type'] = dist_m.group(2).capitalize()
            else:
                # Try just distance
                dist_m2 = re.search(r'(\d{3,4})', info_text)
                if dist_m2:
                    rh['distance'] = int(dist_m2.group(1))

            rh['group_name'] = info_text[:80]

    # Parse each table for horse data
    for table in tables:
        # Check if this is a race table (has headers like N, At İsmi, etc.)
        headers = []
        thead = table.find('thead') or table.find('tr')
        if thead:
            for th in thead.find_all(['th', 'td']):
                headers.append(th.get_text(strip=True))

        # Check for key column names
        header_text = ' '.join(headers).lower()
        if 'at' not in header_text and 'jokey' not in header_text:
            continue

        # Map column indices
        col_map = {}
        for i, h in enumerate(headers):
            h_lower = h.lower().strip()
            if h_lower == 'n':
                col_map['number'] = i
            elif 'at' in h_lower and 'ismi' in h_lower:
                col_map['name'] = i
            elif h_lower == 'yaş':
                col_map['age'] = i
            elif 'orijin' in h_lower or 'baba' in h_lower:
                col_map['pedigree'] = i
            elif 'sıklet' in h_lower or 'kilo' in h_lower:
                col_map['weight'] = i
            elif 'jokey' in h_lower:
                col_map['jockey'] = i
            elif 'antrenör' in h_lower:
                col_map['trainer'] = i
            elif h_lower == 'st':
                col_map['start'] = i
            elif h_lower == 'hp':
                col_map['handicap'] = i
            elif 'son' in h_lower and ('6' in h_lower or 'yarış' in h_lower.replace('ı', 'i')):
                col_map['form'] = i
            elif h_lower == 'kgs':
                col_map['kgs'] = i
            elif h_lower == 's20':
                col_map['s20'] = i
            elif h_lower == 'agf':
                col_map['agf'] = i

        if 'name' not in col_map and 'number' not in col_map:
            continue

        # Parse horse rows
        horses = []
        rows = table.find_all('tr')
        for row in rows:
            cells = row.find_all('td')
            if len(cells) < 5:
                continue

            horse = _parse_horse_row(cells, col_map)
            if horse:
                horses.append(horse)

        if horses:
            # Match with race header
            race_info = _match_race_header(table, race_headers)
            race = {
                'race_number': race_info.get('race_number', len(races) + 1),
                'distance': race_info.get('distance', 0),
                'track_type': race_info.get('track_type', ''),
                'group_name': race_info.get('group_name', ''),
                'time': race_info.get('time', ''),
                'prize': 0,
                'horses': horses,
            }
            races.append(race)
            logger.info(f"  {race['race_number']}. Koşu: {len(horses)} at, "
                        f"{race['distance']}m {race['track_type']} {race['time']}")

    logger.info(f"HTML parsed: {sehir_name} — {len(races)} races, "
                f"{sum(len(r['horses']) for r in races)} horses")
    return races


def _parse_horse_row(cells, col_map):
    """Tek at satırını parse et."""
    def get_cell(key):
        idx = col_map.get(key)
        if idx is not None and idx < len(cells):
            return cells[idx]
        return None

    def get_text(key, default=''):
        cell = get_cell(key)
        return cell.get_text(strip=True) if cell else default

    # At numarası
    num_text = get_text('number', '0')
    try:
        horse_number = int(re.search(r'\d+', num_text).group())
    except (AttributeError, ValueError):
        return None

    # At ismi
    name_cell = get_cell('name')
    if not name_cell:
        return None
    # Name is in first link usually
    name_link = name_cell.find('a')
    horse_name = name_link.get_text(strip=True) if name_link else get_text('name')
    if not horse_name:
        return None

    # Equipment from name cell (KG, DB, SK etc. in description)
    name_full = name_cell.get_text(' ', strip=True)
    equipment = ''
    equip_codes = ['KG', 'DB', 'SK', 'SKG', 'OG', 'DG', 'K', 'B', 'AL', 'GKR']
    found_equip = [code for code in equip_codes if code in name_full]
    equipment = ' '.join(found_equip)

    # Yaş
    age_text = get_text('age', '4y')
    age_m = re.search(r'(\d)', age_text)
    age = int(age_m.group(1)) if age_m else 4

    # Pedigree: "BABA (COUNTRY) - ANNE / ANABABA"
    pedigree_cell = get_cell('pedigree')
    sire, dam, dam_sire = '', '', ''
    if pedigree_cell:
        ped_text = pedigree_cell.get_text(' ', strip=True)
        # Links contain individual names
        ped_links = pedigree_cell.find_all('a')
        if len(ped_links) >= 2:
            sire = ped_links[0].get_text(strip=True)
            dam = ped_links[1].get_text(strip=True)
        if len(ped_links) >= 3:
            dam_sire = ped_links[2].get_text(strip=True)
        # Fallback: parse text
        if not sire:
            parts = re.split(r'\s*[-–]\s*', ped_text, maxsplit=1)
            if parts:
                sire = parts[0].strip()
            if len(parts) > 1:
                anne_parts = re.split(r'\s*/\s*', parts[1])
                dam = anne_parts[0].strip()
                if len(anne_parts) > 1:
                    dam_sire = anne_parts[1].strip()

    # Sıklet
    weight_text = get_text('weight', '57')
    weight_m = re.search(r'[\d]+[,.]?\d*', weight_text)
    weight = float(weight_m.group().replace(',', '.')) if weight_m else 57.0

    # Jokey
    jockey_cell = get_cell('jockey')
    jockey = ''
    if jockey_cell:
        j_link = jockey_cell.find('a')
        if j_link:
            jockey = j_link.get('title', '') or j_link.get_text(strip=True)
        else:
            jockey = jockey_cell.get_text(strip=True)

    # Antrenör
    trainer_cell = get_cell('trainer')
    trainer = ''
    if trainer_cell:
        t_link = trainer_cell.find('a')
        if t_link:
            trainer = t_link.get('title', '') or t_link.get_text(strip=True)
        else:
            trainer = trainer_cell.get_text(strip=True)

    # Start pozisyonu
    start_text = get_text('start', '0')
    start_m = re.search(r'(\d+)', start_text)
    start_pos = int(start_m.group(1)) if start_m else horse_number

    # HP
    hp_text = get_text('handicap', '0')
    hp_m = re.search(r'(\d+)', hp_text)
    handicap = int(hp_m.group(1)) if hp_m else 0

    # Son 6 Yarış (form)
    form_cell = get_cell('form')
    form = ''
    if form_cell:
        # Form digits are often in <b> or <strong> tags
        bolds = form_cell.find_all(['b', 'strong'])
        if bolds:
            form = ''.join(b.get_text(strip=True) for b in bolds)
        else:
            form = re.sub(r'[^\d\-]', '', form_cell.get_text(strip=True))
        # Clean: remove leading/trailing dashes
        form = form.strip('-')

    # KGS
    kgs_text = get_text('kgs', '0')
    kgs_m = re.search(r'(\d+)', kgs_text)
    kgs = int(kgs_m.group(1)) if kgs_m else 0

    # s20
    s20_text = get_text('s20', '0')
    s20_m = re.search(r'(\d+)', s20_text)
    s20 = int(s20_m.group(1)) if s20_m else 0

    # AGF
    agf_text = get_text('agf', '')
    agf_m = re.search(r'%(\d+)', agf_text)
    agf_pct = int(agf_m.group(1)) if agf_m else 0

    return {
        'horse_number': horse_number,
        'horse_name': horse_name,
        'age': age,
        'age_text': age_text,
        'weight': weight,
        'jockey_name': jockey,
        'trainer_name': trainer,
        'sire_name': sire,
        'dam_name': dam,
        'dam_sire_name': dam_sire,
        'form': form,
        'equipment': equipment,
        'kgs': kgs,
        'last_20_score': s20,
        'handicap_rating': handicap,
        'start_position': start_pos,
        'agf_pct': agf_pct,
    }


def _match_race_header(table, race_headers):
    """Tablo ile en yakın koşu başlığını eşleştir."""
    # Find the preceding h3 element
    prev = table.find_previous('h3')
    if prev:
        text = prev.get_text(strip=True)
        m = re.match(r'(\d+)\.\s*Koşu', text)
        if m:
            race_num = int(m.group(1))
            for rh in race_headers:
                if rh['race_number'] == race_num:
                    return rh
    return {'race_number': 0}


# ═══════════════════════════════════════════════════════════════
# STEP 3: CSV FALLBACK
# ═══════════════════════════════════════════════════════════════

def _try_csv(target_date, sehir_name):
    """CSV'den veri çek — HTML başarısız olursa fallback."""
    yyyy = target_date.strftime('%Y')
    yyyy_mm_dd = target_date.strftime('%Y-%m-%d')
    dd_mm_yyyy = target_date.strftime('%d.%m.%Y')

    # URL name mapping
    url_name = sehir_name
    url_names_map = {
        'İstanbul': 'Istanbul', 'İzmir': 'Izmir', 'Şanlıurfa': 'Sanliurfa',
        'Elazığ': 'Elazig', 'Diyarbakır': 'Diyarbakir',
    }
    url_name = url_names_map.get(sehir_name, sehir_name)

    csv_url = (f"{TJK_CDN_BASE}/{yyyy}/{yyyy_mm_dd}/CSV/"
               f"GunlukYarisProgrami/{dd_mm_yyyy}-{url_name}-GunlukYarisProgrami-TR.csv")

    try:
        resp = SESSION.get(csv_url, timeout=20)
        if resp.status_code != 200:
            return None

        # Try different encodings
        for enc in ['utf-8', 'windows-1254', 'iso-8859-9', 'latin-1']:
            try:
                text = resp.content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            return None

        reader = csv.reader(io.StringIO(text), delimiter=';')
        rows = list(reader)

        if len(rows) < 2:
            return None

        logger.info(f"CSV loaded for {sehir_name}: {len(rows)} rows")
        return _parse_csv_rows(rows)

    except Exception as e:
        logger.debug(f"CSV fallback failed for {sehir_name}: {e}")
        return None


def _parse_csv_rows(rows):
    """CSV satırlarından koşu bilgilerini çıkar."""
    # CSV structure varies — detect columns from header
    header = [h.strip().lower() for h in rows[0]] if rows else []
    races = {}

    for row in rows[1:]:
        if len(row) < 5:
            continue

        # Try to find race number column
        race_num = 0
        for i, cell in enumerate(row):
            if i < len(header) and 'koşu' in header[i]:
                try:
                    race_num = int(cell.strip())
                except ValueError:
                    pass
                break

        if race_num not in races:
            races[race_num] = {
                'race_number': race_num,
                'distance': 0,
                'track_type': '',
                'group_name': '',
                'time': '',
                'prize': 0,
                'horses': [],
            }

        # Build horse dict from row
        horse = {}
        for i, cell in enumerate(row):
            if i < len(header):
                horse[header[i]] = cell.strip()
        races[race_num]['horses'].append(horse)

    return list(races.values())


# ═══════════════════════════════════════════════════════════════
# PUBLIC API — Drop-in replacement for tjk_program.get_todays_races()
# ═══════════════════════════════════════════════════════════════

def get_todays_races_html(target_date=None):
    """
    Günün yarış programını TJK HTML'den çek.
    Fallback: CSV → mevcut PDF parser.

    Returns: list of hippodrome dicts (same format as tjk_program.get_todays_races)
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d.%m.%Y')
    logger.info(f"HTML scraper: fetching program for {date_str}")

    # Step 1: Discover hippodromes
    hippodromes = _discover_hippodromes(target_date)
    if not hippodromes:
        logger.warning("HTML: No hippodromes found, falling back to PDF")
        return None  # Caller should try PDF fallback

    results = []
    for hippo in hippodromes:
        sehir_id = hippo['sehir_id']
        sehir_name = hippo['sehir_name']

        # Try HTML first
        html = _fetch_hippodrome_html(sehir_id, sehir_name, target_date)
        races = None
        source = 'none'

        if html:
            races = _parse_hippodrome_html(html, sehir_name)
            if races:
                source = 'html'

        # Fallback to CSV
        if not races:
            races = _try_csv(target_date, sehir_name)
            if races:
                source = 'csv'

        if races:
            # Build display name
            display = sehir_name
            if 'Hipodromu' not in display:
                display = f"{display} Hipodromu"

            total_horses = sum(len(r['horses']) for r in races)
            logger.info(f"  {sehir_name} ({source}): {len(races)} races, {total_horses} horses")

            results.append({
                'hippodrome': display,
                'date': date_str,
                'races': races,
                'source': source,
            })

    return results if results else None
