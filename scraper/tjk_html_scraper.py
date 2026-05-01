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
from urllib.parse import unquote, quote
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


# PATCH_FAZ2_TR_WHITELIST_v1: Turkish hippodrome whitelist (BUG 1)
_TR_HIPPODROMES_WHITELIST = frozenset({
    'istanbul', 'ankara', 'izmir', 'adana', 'bursa',
    'şanlıurfa', 'sanliurfa', 'şanliurfa', 'sanlıurfa', 'urfa',
    'diyarbakır', 'diyarbakir',
    'elazığ', 'elazig',
    'kocaeli',
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
            # PATCH_FAZ2_TR_WHITELIST_v1: WHITELIST Turkish hippodromes (BUG 1)
            text_lower = text.lower()
            if not any(t in text_lower for t in _TR_HIPPODROMES_WHITELIST):
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
           f"&QueryParameter_Tarih={date_str}&SehirAdi={quote(sehir_name)}&Era=today")
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
            # Race number 0 ise sıralı numara ata (TJK HTML'de heading yoksa oluyor)
            race_num = race_info.get('race_number', 0)
            if race_num == 0:
                race_num = len(races) + 1
            race = {
                'race_number': race_num,
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
    """Map TJK table headers to standardized keys.
    
    Known headers: Forma, N, At İsmi, Yaş, Orijin(Baba - Anne), Sıklet,
    Jokey, Sahip, Antrenör, St, HP, Son 6 Y., KGS, s20, En İyi D., Gny, AGF, İdm
    """
    # Normalize: strip + handle Turkish İ→i, Ş→s etc.
    def norm(s):
        return (s.strip()
                .replace('İ', 'I').replace('ı', 'i')
                .replace('Ş', 'S').replace('ş', 's')
                .replace('Ö', 'O').replace('ö', 'o')
                .replace('Ü', 'U').replace('ü', 'u')
                .replace('Ç', 'C').replace('ç', 'c')
                .replace('Ğ', 'G').replace('ğ', 'g')
                .lower())

    # Exact known mappings (TJK headers are consistent)
    EXACT = {
        'n': 'number',
        'at ismi': 'name',
        'yas': 'age',
        'siklet': 'weight',
        'jokey': 'jockey',
        'antrenor': 'trainer',
        'sahip': 'sahip',
        'st': 'start',
        'hp': 'handicap',
        'son 6 y.': 'form',
        'kgs': 'kgs',
        's20': 's20',
        'agf': 'agf',
        'gny': 'gny',
    }

    col = {}
    for i, h in enumerate(headers):
        hn = norm(h)
        # Exact match first
        if hn in EXACT:
            col[EXACT[hn]] = i
        # Pedigree column: contains "orijin" or "baba"
        elif 'orijin' in hn or 'baba' in hn:
            col['pedigree'] = i
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
        # Fallback: TJK "Baba - Anne / AnneBabasi" formatindan parse et
        if not dam_sire:
            pedigree_text = pc.get_text(strip=True)
            if '/' in pedigree_text:
                after_slash = pedigree_text.split('/')[-1].strip()
                if after_slash and len(after_slash) > 1:
                    dam_sire = after_slash

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
    """Tablonun öncesindeki heading elementlerinden koşu bilgilerini çıkarır.
    
    TJK HTML'de koşu bilgisi birden fazla elemente yayılmış olabiliyor:
      - Bir H3'te koşu numarası ve saat
      - Başka bir H3/H4/H5'te grup adı, mesafe, pist türü
    
    ÖNEMLİ: div/span aramıyoruz çünkü bunlar tabloyu wrap eden container
    olabiliyor ve get_text() tüm tablo içeriğini döndürüyor (garbage veri).
    """
    info = {'race_number': 0, 'distance': 0, 'track_type': '', 'group_name': '', 'time': ''}
    
    found_race_num = False
    found_distance = False
    checked = 0
    
    # Sadece heading elementlerine bak — div/span tablo wrapper'ı olabiliyor
    for prev in table.find_all_previous(['h3', 'h4', 'h5']):
        checked += 1
        if checked > 10:
            break
            
        text = prev.get_text(strip=True)
        # Kısa veya çok uzun metin atla — gerçek heading'ler < 200 karakter olur
        if not text or len(text) < 2 or len(text) > 200:
            continue
        
        # Tablo başlığı mı? (Forma, N, At İsmi, ... gibi) — atla
        if 'At İsmi' in text or 'Jokey' in text or 'Antrenör' in text or 'Sıklet' in text:
            continue
        
        # 1. Koşu numarası ve saat (ör: "3. Koşu 14:30")
        if not found_race_num:
            m = re.match(r'(\d+)\.\s*Ko[sş]u[:\s]*(\d{2}[.:]\d{2})?', text, re.IGNORECASE)
            if m:
                info['race_number'] = int(m.group(1))
                if m.group(2):
                    info['time'] = m.group(2).replace('.', ':')
                found_race_num = True
                # Bu element aynı zamanda mesafe/pist de içerebilir
                dm = re.search(r'(\d{3,4})\s*(?:m\.?\s*)?(Kum|[CÇ]im|Sentetik|kum|[cç]im|sentetik)', text, re.IGNORECASE)
                if dm and not found_distance:
                    info['distance'] = int(dm.group(1))
                    track_raw = dm.group(2).lower()
                    if 'kum' in track_raw:
                        info['track_type'] = 'Kum'
                    elif 'im' in track_raw:
                        info['track_type'] = 'Çim'
                    elif 'sentetik' in track_raw:
                        info['track_type'] = 'Sentetik'
                    found_distance = True
                if found_race_num and found_distance and info['group_name']:
                    break
                continue
        
        # 2. Mesafe ve pist türü (ör: "900 Çim" veya "1400 Kum")
        if not found_distance:
            dm = re.search(r'(\d{3,4})\s*(?:m\.?\s*)?(Kum|[CÇ]im|Sentetik|kum|[cç]im|sentetik)', text, re.IGNORECASE)
            if dm:
                info['distance'] = int(dm.group(1))
                track_raw = dm.group(2).lower()
                if 'kum' in track_raw:
                    info['track_type'] = 'Kum'
                elif 'im' in track_raw:
                    info['track_type'] = 'Çim'
                elif 'sentetik' in track_raw:
                    info['track_type'] = 'Sentetik'
                found_distance = True
        
        # 3. Grup adı — breed, sınıf, koşu koşulları bilgisi
        if not info['group_name']:
            gn_lower = text.lower()
            breed_keywords = ['ingiliz', 'ngiliz', 'arap', 'arab']
            class_keywords = ['maiden', 'bakire', 'handikap', 'handicap', 'şartl', 'sartl',
                             'graded', 'listed', 'aprantiler', 'taylar',
                             'dişi', 'disi', 'kısrak', 'kisrak',
                             'dhöw', 'dhow', 'e.i.d']
            has_keyword = any(kw in gn_lower for kw in breed_keywords + class_keywords)
            has_distance_info = bool(re.search(r'\d{3,4}\s*(Kum|[CÇ]im|Sentetik)', text, re.IGNORECASE))
            
            if has_keyword or has_distance_info:
                if not re.match(r'^\d+\.\s*Ko[sş]u', text, re.IGNORECASE):
                    info['group_name'] = text[:120]
        
        if found_race_num and found_distance and info['group_name']:
            break
    
    # Fallback: H3'te koşu numarası bulunamadıysa, tablonun hemen öncesindeki
    # sibling'e bak (bazı TJK sayfalarında koşu bilgisi <p> veya <div class=...> olabiliyor)
    if not found_race_num:
        prev_sib = table.find_previous_sibling()
        if prev_sib:
            sib_text = prev_sib.get_text(strip=True)
            if sib_text and len(sib_text) < 200:
                m = re.match(r'(\d+)\.\s*Ko[sş]u[:\s]*(\d{2}[.:]\d{2})?', sib_text, re.IGNORECASE)
                if m:
                    info['race_number'] = int(m.group(1))
                    if m.group(2):
                        info['time'] = m.group(2).replace('.', ':')
                # Mesafe/pist de olabilir
                dm = re.search(r'(\d{3,4})\s*(?:m\.?\s*)?(Kum|[CÇ]im|Sentetik)', sib_text, re.IGNORECASE)
                if dm and not info['distance']:
                    info['distance'] = int(dm.group(1))
                    track_raw = dm.group(2).lower()
                    if 'kum' in track_raw:
                        info['track_type'] = 'Kum'
                    elif 'im' in track_raw:
                        info['track_type'] = 'Çim'
                    elif 'sentetik' in track_raw:
                        info['track_type'] = 'Sentetik'
                # Grup adı olabilir
                if not info['group_name'] and len(sib_text) > 5:
                    gn_lower = sib_text.lower()
                    if any(kw in gn_lower for kw in ['arap', 'ingiliz', 'ngiliz', 'handikap',
                                                       'şartl', 'sartl', 'maiden', 'bakire']):
                        info['group_name'] = sib_text[:120]
    
    if info['race_number'] > 0:
        logger.debug(f"Race info: #{info['race_number']} {info['distance']}m "
                     f"{info['track_type']} group='{info['group_name'][:60]}'")
    
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
        'sire': find_col('orijin(baba', 'baba', 'sire'),
        'dam': find_col('orijin(anne', 'anne', 'dam'),
        'dam_sire': find_col('anne babası', 'anababa', 'damsire', 'orijin(anne baba'),
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
            'dam_name': get(row, 'dam').split('/')[0].strip() if '/' in get(row, 'dam') else get(row, 'dam'),
            'dam_sire_name': get(row, 'dam').split('/')[-1].strip() if '/' in get(row, 'dam') else get(row, 'dam_sire'),
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
