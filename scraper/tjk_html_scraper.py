"""
TJK HTML Scraper — Full Data from tjk.org
==========================================
Fallback chain: HTML → CSV → Özet PDF (mevcut)
"""
import requests
import re
import csv
import io
import logging
from datetime import date
from typing import Optional, List, Dict
from urllib.parse import unquote
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

TJK_BASE = "https://www.tjk.org"
TJK_PROGRAM_URL = f"{TJK_BASE}/TR/yarissever/Info/Page/GunlukYarisProgrami"
TJK_DETAIL_URL = f"{TJK_BASE}/TR/yarissever/Info/Sehir/GunlukYarisProgrami"
TJK_CDN_BASE = "https://medya-cdn.tjk.org/raporftp/TJKPDF"

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'tr-TR,tr;q=0.9',
})


def _discover_hippodromes(target_date):
    date_str = target_date.strftime('%d/%m/%Y')
    url = f"{TJK_PROGRAM_URL}?QueryParameter_Tarih={date_str}&Era=today"
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        soup = BeautifulSoup(resp.text, 'html.parser')
        hippodromes = []
        seen = set()
        for link in soup.find_all('a', href=True):
            href = link['href']
            if 'SehirId=' not in href:
                continue
            text = link.get_text(strip=True)
            if any(x in text for x in ['ABD', 'Fransa', 'Afrika', 'Birleşik']):
                continue
            sm = re.search(r'SehirId=(\d+)', href)
            nm = re.search(r'SehirAdi=([^&]+)', href)
            if sm:
                sid = int(sm.group(1))
                if sid in seen:
                    continue
                seen.add(sid)
                sname = unquote(nm.group(1)) if nm else str(sid)
                hippodromes.append({'sehir_id': sid, 'sehir_name': sname})
        logger.info(f"HTML: {len(hippodromes)} Türkiye hipodromu: {[h['sehir_name'] for h in hippodromes]}")
        return hippodromes
    except Exception as e:
        logger.warning(f"HTML hippodrome discovery failed: {e}")
        return []


def _fetch_and_parse_html(sehir_id, sehir_name, target_date):
    """Bir hipodromun HTML sayfasını çek ve parse et."""
    date_str = target_date.strftime('%d/%m/%Y')
    url = (f"{TJK_DETAIL_URL}?SehirId={sehir_id}"
           f"&QueryParameter_Tarih={date_str}&SehirAdi={sehir_name}&Era=today")
    try:
        resp = SESSION.get(url, timeout=30)
        resp.raise_for_status()
        html = resp.text
        logger.info(f"HTML fetched for {sehir_name}: {len(html)} chars")

        soup = BeautifulSoup(html, 'html.parser')

        # Find ALL tables — look for ones with "At İsmi" or "Jokey" in header
        races = []
        tables = soup.find_all('table')
        logger.info(f"  Found {len(tables)} tables in HTML")

        for table in tables:
            # Get all header cells from first row or thead
            header_cells = []
            thead = table.find('thead')
            if thead:
                header_cells = thead.find_all(['th', 'td'])
            if not header_cells:
                first_tr = table.find('tr')
                if first_tr:
                    header_cells = first_tr.find_all(['th', 'td'])

            headers = [h.get_text(strip=True) for h in header_cells]
            joined = ' '.join(headers).lower()

            # Must have horse-related columns
            if not ('jokey' in joined or 'at' in joined):
                continue

            # Log what we found for debugging
            logger.info(f"  Race table found! Headers ({len(headers)}): {headers[:8]}...")

            # Build column index map
            col = _build_col_map(headers)
            if 'name' not in col:
                logger.info(f"  Skipping table — no 'name' column in: {headers}")
                continue

            # Parse data rows
            horses = []
            all_rows = table.find_all('tr')
            for row in all_rows:
                tds = row.find_all('td')
                if len(tds) < 5:
                    continue
                h = _parse_html_horse(tds, col)
                if h:
                    horses.append(h)

            if not horses:
                continue

            # Match race info from preceding h3
            race_info = _get_race_info_from_h3(table, soup)
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
            logger.info(f"  {race['race_number']}. Koşu: {len(horses)} at")

        logger.info(f"HTML parsed: {sehir_name} — {len(races)} races")
        return races if races else None

    except Exception as e:
        logger.warning(f"HTML parse failed for {sehir_name}: {e}")
        import traceback; traceback.print_exc()
        return None


def _build_col_map(headers):
    col = {}
    for i, h in enumerate(headers):
        hl = h.lower().strip()
        if hl == 'n' or hl == 'no':
            col['number'] = i
        elif 'at' in hl and ('ismi' in hl or 'adı' in hl or hl == 'at'):
            col['name'] = i
        elif hl in ('yaş', 'yas'):
            col['age'] = i
        elif 'orijin' in hl or ('baba' in hl and 'anne' in hl):
            col['pedigree'] = i
        elif hl in ('sıklet', 'siklet', 'kilo', 'kg'):
            col['weight'] = i
        elif 'jokey' in hl:
            col['jockey'] = i
        elif 'antrenör' in hl or 'antrenor' in hl:
            col['trainer'] = i
        elif hl == 'st':
            col['start'] = i
        elif hl == 'hp':
            col['handicap'] = i
        elif 'son' in hl and ('6' in hl or 'y.' in hl):
            col['form'] = i
        elif hl == 'kgs':
            col['kgs'] = i
        elif hl == 's20':
            col['s20'] = i
        elif hl == 'agf':
            col['agf'] = i
        elif 'gny' in hl or 'ganyan' in hl:
            col['gny'] = i
    return col


def _parse_html_horse(cells, col):
    def cell(key):
        idx = col.get(key)
        return cells[idx] if idx is not None and idx < len(cells) else None

    def text(key, default=''):
        c = cell(key)
        return c.get_text(strip=True) if c else default

    # Number
    num_t = text('number', '0')
    m = re.search(r'\d+', num_t)
    if not m:
        return None
    horse_number = int(m.group())

    # Name
    nc = cell('name')
    if not nc:
        return None
    nl = nc.find('a')
    horse_name = nl.get_text(strip=True) if nl else text('name')
    if not horse_name or len(horse_name) < 2:
        return None

    # Equipment from name cell text
    name_full = nc.get_text(' ', strip=True)
    equip_codes = ['SKG', 'KG', 'DB', 'SK', 'OG', 'DG', 'GKR', 'AL']
    equipment = ' '.join(c for c in equip_codes if c in name_full)

    # Age
    age_text = text('age', '4y')
    am = re.search(r'(\d)', age_text)
    age = int(am.group(1)) if am else 4

    # Pedigree
    sire, dam, dam_sire = '', '', ''
    pc = cell('pedigree')
    if pc:
        links = pc.find_all('a')
        if len(links) >= 1:
            sire = links[0].get_text(strip=True)
        if len(links) >= 2:
            dam = links[1].get_text(strip=True)
        if len(links) >= 3:
            dam_sire = links[2].get_text(strip=True)

    # Weight
    wt = text('weight', '57')
    wm = re.search(r'[\d]+[,.]?\d*', wt)
    weight = float(wm.group().replace(',', '.')) if wm else 57.0

    # Jockey (from title attr or text)
    jc = cell('jockey')
    jockey = ''
    if jc:
        jl = jc.find('a')
        jockey = (jl.get('title', '') or jl.get_text(strip=True)) if jl else jc.get_text(strip=True)

    # Trainer
    tc = cell('trainer')
    trainer = ''
    if tc:
        tl = tc.find('a')
        trainer = (tl.get('title', '') or tl.get_text(strip=True)) if tl else tc.get_text(strip=True)

    # Start position
    st = text('start', '0')
    sm = re.search(r'(\d+)', st)
    start_pos = int(sm.group(1)) if sm else horse_number

    # Handicap
    hp = text('handicap', '0')
    hm = re.search(r'(\d+)', hp)
    handicap = int(hm.group(1)) if hm else 0

    # Form
    form = ''
    fc = cell('form')
    if fc:
        bolds = fc.find_all(['b', 'strong'])
        if bolds:
            form = ''.join(b.get_text(strip=True) for b in bolds)
        if not form:
            form = re.sub(r'[^\d\-]', '', fc.get_text(strip=True))
        form = form.strip('-')

    # KGS
    kgs_t = text('kgs', '0')
    km = re.search(r'(\d+)', kgs_t)
    kgs = int(km.group(1)) if km else 0

    # s20
    s20_t = text('s20', '0')
    s20m = re.search(r'(\d+)', s20_t)
    s20 = int(s20m.group(1)) if s20m else 0

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
    }


def _get_race_info_from_h3(table, soup):
    """Find race number/time from preceding h3 elements."""
    info = {'race_number': 0, 'distance': 0, 'track_type': '', 'group_name': '', 'time': ''}
    # Walk backwards from table to find h3
    for prev in table.find_all_previous(['h3']):
        text = prev.get_text(strip=True)
        m = re.match(r'(\d+)\.\s*Koşu[:\s]*(\d{2}[.:]\d{2})?', text)
        if m:
            info['race_number'] = int(m.group(1))
            if m.group(2):
                info['time'] = m.group(2).replace('.', ':')
            break
        # Check for distance/track in race type header
        dm = re.search(r'(\d{3,4})\s*(Kum|Çim|Sentetik)', text, re.IGNORECASE)
        if dm:
            info['distance'] = int(dm.group(1))
            info['track_type'] = dm.group(2).capitalize()
            info['group_name'] = text[:80]
    return info


# ═══════════════════════════════════════════════════════════════
# CSV FALLBACK
# ═══════════════════════════════════════════════════════════════

def _try_csv(target_date, sehir_name):
    yyyy = target_date.strftime('%Y')
    yyyy_mm_dd = target_date.strftime('%Y-%m-%d')
    dd_mm_yyyy = target_date.strftime('%d.%m.%Y')

    url_map = {'İstanbul': 'Istanbul', 'İzmir': 'Izmir', 'Şanlıurfa': 'Sanliurfa',
               'Elazığ': 'Elazig', 'Diyarbakır': 'Diyarbakir'}
    url_name = url_map.get(sehir_name, sehir_name)

    csv_url = (f"{TJK_CDN_BASE}/{yyyy}/{yyyy_mm_dd}/CSV/"
               f"GunlukYarisProgrami/{dd_mm_yyyy}-{url_name}-GunlukYarisProgrami-TR.csv")

    try:
        resp = SESSION.get(csv_url, timeout=20)
        if resp.status_code != 200:
            return None

        for enc in ['utf-8', 'windows-1254', 'iso-8859-9', 'latin-1']:
            try:
                text = resp.content.decode(enc)
                break
            except (UnicodeDecodeError, LookupError):
                continue
        else:
            return None

        # Try both ; and , as delimiter
        for delim in [';', ',', '\t']:
            try:
                reader = csv.reader(io.StringIO(text), delimiter=delim)
                rows = list(reader)
                if len(rows) > 2 and len(rows[0]) > 5:
                    break
            except:
                continue
        else:
            return None

        if len(rows) < 2:
            return None

        logger.info(f"CSV loaded for {sehir_name}: {len(rows)} rows, {len(rows[0])} cols")
        logger.info(f"  CSV headers: {rows[0][:10]}")
        return _parse_csv_to_races(rows)

    except Exception as e:
        logger.debug(f"CSV failed for {sehir_name}: {e}")
        return None


def _parse_csv_to_races(rows):
    """Parse CSV into standardized race/horse format."""
    header = rows[0]
    hl = [h.strip().lower() for h in header]

    # Map CSV column indices
    def find_col(*names):
        for n in names:
            for i, h in enumerate(hl):
                if n in h:
                    return i
        return None

    ci = {
        'race': find_col('koşu no', 'kosu no', 'koşu', 'race'),
        'number': find_col('at no', 'no', 'numara'),
        'name': find_col('at adı', 'at adi', 'isim', 'name'),
        'age': find_col('yaş', 'yas', 'age'),
        'sire': find_col('baba', 'sire'),
        'dam': find_col('anne', 'dam'),
        'dam_sire': find_col('anne babası', 'anababa', 'damsire'),
        'weight': find_col('kilo', 'sıklet', 'weight'),
        'jockey': find_col('jokey', 'jockey'),
        'trainer': find_col('antrenör', 'antrenor', 'trainer'),
        'form': find_col('son 6', 'form'),
        'kgs': find_col('kgs'),
        'hp': find_col('hp', 'handikap', 'handicap'),
        'start': find_col('st', 'start'),
        'distance': find_col('mesafe', 'distance'),
        'track': find_col('pist', 'track'),
    }

    def get(row, key, default=''):
        idx = ci.get(key)
        if idx is not None and idx < len(row):
            return row[idx].strip()
        return default

    races = {}
    for row in rows[1:]:
        if len(row) < 3:
            continue

        race_num = 0
        rn = get(row, 'race')
        if rn:
            rm = re.search(r'\d+', rn)
            race_num = int(rm.group()) if rm else 0

        # Horse number
        num_s = get(row, 'number', '0')
        nm = re.search(r'\d+', num_s)
        if not nm:
            continue
        horse_number = int(nm.group())

        horse_name = get(row, 'name')
        if not horse_name:
            continue

        # Weight
        wt = get(row, 'weight', '57')
        wm = re.search(r'[\d]+[,.]?\d*', wt)
        weight = float(wm.group().replace(',', '.')) if wm else 57.0

        # Age
        at = get(row, 'age', '4')
        am = re.search(r'(\d)', at)
        age = int(am.group(1)) if am else 4

        # KGS
        kgs_s = get(row, 'kgs', '0')
        km = re.search(r'\d+', kgs_s)
        kgs = int(km.group()) if km else 0

        # HP
        hp_s = get(row, 'hp', '0')
        hm = re.search(r'\d+', hp_s)
        hp = int(hm.group()) if hm else 0

        horse = {
            'horse_number': horse_number,
            'horse_name': horse_name,
            'age': age,
            'age_text': get(row, 'age'),
            'weight': weight,
            'jockey_name': get(row, 'jockey'),
            'trainer_name': get(row, 'trainer'),
            'sire_name': get(row, 'sire'),
            'dam_name': get(row, 'dam'),
            'dam_sire_name': get(row, 'dam_sire'),
            'form': get(row, 'form'),
            'equipment': '',
            'kgs': kgs,
            'last_20_score': 0,
            'handicap_rating': hp,
            'start_position': horse_number,
        }

        if race_num not in races:
            dist_s = get(row, 'distance', '0')
            dm = re.search(r'\d+', dist_s)
            races[race_num] = {
                'race_number': race_num,
                'distance': int(dm.group()) if dm else 0,
                'track_type': get(row, 'track'),
                'group_name': '',
                'time': '',
                'prize': 0,
                'horses': [],
            }

        races[race_num]['horses'].append(horse)

    result = sorted(races.values(), key=lambda r: r['race_number'])
    logger.info(f"  CSV parsed: {len(result)} races, "
                f"{sum(len(r['horses']) for r in result)} horses")
    return result if result else None


# ═══════════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════════

def get_todays_races_html(target_date=None):
    if target_date is None:
        target_date = date.today()

    logger.info(f"HTML scraper: fetching program for {target_date.strftime('%d.%m.%Y')}")

    hippodromes = _discover_hippodromes(target_date)
    if not hippodromes:
        logger.warning("HTML: No hippodromes found")
        return None

    results = []
    for hippo in hippodromes:
        sid = hippo['sehir_id']
        sname = hippo['sehir_name']

        # Try HTML
        races = _fetch_and_parse_html(sid, sname, target_date)
        source = 'html' if races else None

        # Fallback: CSV
        if not races:
            races = _try_csv(target_date, sname)
            source = 'csv' if races else None

        if races:
            display = f"{sname} Hipodromu" if 'Hipodromu' not in sname else sname
            total = sum(len(r['horses']) for r in races)
            logger.info(f"  {sname} ({source}): {len(races)} races, {total} horses")
            results.append({
                'hippodrome': display,
                'date': target_date.strftime('%d.%m.%Y'),
                'races': races,
                'source': source,
            })

    return results if results else None
