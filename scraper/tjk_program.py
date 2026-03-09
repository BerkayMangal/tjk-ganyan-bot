"""
TJK Program Scraper — PDF CDN Version
=======================================
TJK sitesi 403 verdiği için medya-cdn.tjk.org'dan PDF çeker.
main.py ile aynı interface'i korur.

PDF Pattern:
https://medya-cdn.tjk.org/raporftp/TJKPDF/{YYYY}/{YYYY-MM-DD}/PDFOzet/GunlukYarisProgrami/{DD.MM.YYYY}-{Sehir}-GunlukYarisProgrami-TR.pdf

Gerçek PDF formatı (örnek):
  1.Koşu
  14.00
  Maiden/DHÖ, 4 Yaşlı Araplar, 58.00 kg
  1300m. Kum İkramiye: 1.)545.000TL 2.)218.000TL ...
  1(7) EMİRHAT KG DB SK GKR 4y 58 R.KETME ÖME. ALTIN 31 21 16 7-54436
  2(1) KAPGAN KAĞAN KG SK 4y 58 O.YILDIZ ÖMÜ. ÇALIŞKAN 17 96 17 858
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

HIPODROM_LIST = [
    "Istanbul", "Ankara", "Izmir", "Bursa", "Adana",
    "Elazig", "Diyarbakir", "Sanliurfa", "Antalya", "Kocaeli",
]

DISPLAY_NAMES = {
    "Istanbul": "İstanbul", "Ankara": "Ankara", "Izmir": "İzmir",
    "Bursa": "Bursa", "Adana": "Adana", "Elazig": "Elazığ",
    "Diyarbakir": "Diyarbakır", "Sanliurfa": "Şanlıurfa",
    "Antalya": "Antalya", "Kocaeli": "Kocaeli",
}

# At satırlarında çıkabilecek takı/özellik kodları
HORSE_TAGS = {'KG', 'K', 'DB', 'SK', 'SKG', 'GKR', 'OG', 'DG', 'G', 'SG', 'B', 'AL'}

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': '*/*',
    'Accept-Language': 'tr-TR,tr;q=0.9,en-US;q=0.8',
})

CACHE_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'data', 'pdf_cache')
os.makedirs(CACHE_DIR, exist_ok=True)


# ═══════════════════════════════════════════════════════════════
# PDF URL + DOWNLOAD
# ═══════════════════════════════════════════════════════════════

def _build_pdf_url(dt, hipodrom_url):
    yyyy = dt.strftime("%Y")
    yyyy_mm_dd = dt.strftime("%Y-%m-%d")
    dd_mm_yyyy = dt.strftime("%d.%m.%Y")
    return (
        f"{TJK_CDN_BASE}/{yyyy}/{yyyy_mm_dd}/PDFOzet/"
        f"GunlukYarisProgrami/{dd_mm_yyyy}-{hipodrom_url}-GunlukYarisProgrami-TR.pdf"
    )


def _download_pdf(dt, hipodrom_url):
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
        if resp.status_code == 200 and len(resp.content) > 5000:
            with open(cache_path, "wb") as f:
                f.write(resp.content)
            logger.info(f"PDF OK: {len(resp.content)} bytes")
            return resp.content
        logger.debug(f"PDF not found: {resp.status_code}")
        return None
    except Exception as e:
        logger.warning(f"PDF download error: {e}")
        return None


def _discover_hipodromlar(dt):
    found = []
    for hip_url in HIPODROM_LIST:
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
# PDF PARSER — TJK gerçek formatına göre
# ═══════════════════════════════════════════════════════════════

def _parse_pdf(pdf_bytes, hipodrom_url, dt):
    """PDF'den yarış verisi çıkar — main.py'nin beklediği formatta."""
    try:
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            logger.info(f"PDF opened: {len(pdf.pages)} pages")
            all_text = ""
            for page in pdf.pages:
                t = page.extract_text()
                if t:
                    all_text += t + "\n"

            if not all_text.strip():
                logger.warning("PDF text extraction returned empty")
                return None

            logger.info(f"Extracted {len(all_text)} chars from PDF")
            # Debug: ilk 500 karakter logla
            logger.debug(f"PDF text preview: {all_text[:500]}")

            races = _parse_races(all_text)

            if not races:
                logger.warning(f"No races parsed from PDF ({hipodrom_url})")
                # Extra debug: log first 1000 chars
                logger.info(f"PDF text first 1000 chars: {all_text[:1000]}")
                return None

            display_name = DISPLAY_NAMES.get(hipodrom_url, hipodrom_url)

            total_horses = sum(len(r['horses']) for r in races)
            logger.info(f"Parsed {len(races)} races, {total_horses} horses")

            return {
                'hippodrome': f"{display_name} Hipodromu",
                'date': dt.strftime("%d.%m.%Y"),
                'races': races,
            }

    except Exception as e:
        logger.error(f"PDF parse error: {e}")
        import traceback
        traceback.print_exc()
        return None


def _parse_races(text):
    """
    Gerçek TJK PDF formatını parse et.

    Koşu başlığı pattern: "1.Koşu" veya "1. Koşu" (satır başı)
    Sonraki satır: saat (14.00)
    Sonraki: grup bilgisi (Maiden/DHÖ, 4 Yaşlı Araplar, 58.00 kg)
    Sonraki: mesafe + pist + ikramiye (1300m. Kum İkramiye: ...)
    Sonra: at satırları: 1(7) EMİRHAT KG DB SK GKR 4y 58 R.KETME ...
    """
    races = []
    lines = text.split('\n')

    logger.info(f"Parsing {len(lines)} lines from PDF text")

    # Koşu başlık pattern: "1.Koşu" veya "2. Koşu" veya "3.KOŞU" vs.
    race_header_re = re.compile(r'(\d+)\s*\.\s*[Kk]o[şs]u', re.IGNORECASE)

    # Also try: "N. Koşu" inside longer lines, e.g. "blah 4.Koşu blah"
    # And handle "KoşuS." footer line (skip it)

    # At satırı pattern
    horse_line_re = re.compile(r'(\d{1,2})\s*\((\d{1,2})\)\s*')

    # Saat pattern: "14.00" veya "14:00" (tek başına veya satır başında)
    time_re = re.compile(r'^(\d{2})[.:]+(\d{2})\s*$')

    # Debug: log any line containing "oşu" or "KOŞU"
    for i, raw_line in enumerate(lines):
        if 'oşu' in raw_line.lower() or 'kosu' in raw_line.lower():
            logger.info(f"  Line {i}: {raw_line.strip()[:80]}")

    # Mesafe pattern: "1300m" veya "1200m."
    dist_re = re.compile(r'(\d{3,4})\s*m[\.\s]')

    # Pist pattern: "Kum" veya "Çim" veya "Sentetik" (mesafe satırında)
    track_re = re.compile(r'(\d{3,4})\s*m[\.\s]+\s*(Kum|Çim|Sentetik|KUM|ÇİM|SENTETİK)', re.IGNORECASE)

    # İkramiye pattern: "1.)545.000TL"
    prize_re = re.compile(r'1\.\)\s*([\d.]+)\s*TL')

    # Grup/tür satırı: "Maiden/DHÖ, 4 Yaşlı Araplar" veya "Handikap 15..."
    group_re = re.compile(r'(Maiden|Handikap|ŞARTLI|KV|Kosul|Koşul|KoşuL)', re.IGNORECASE)

    current_race = None
    horse_lines_buf = []
    state = 'scanning'  # scanning, header_found, collecting_info, collecting_horses

    for i, raw_line in enumerate(lines):
        line = raw_line.strip()
        if not line:
            continue

        # --- Koşu başlığı mı? ---
        hm = race_header_re.search(line)
        if hm and 'KoşuS' not in line and 'Koşul' not in line:
            # Önceki koşuyu kaydet
            if current_race is not None:
                current_race['horses'] = _parse_horse_lines(horse_lines_buf)
                if current_race['horses']:
                    races.append(current_race)
                horse_lines_buf = []

            kosu_no = int(hm.group(1))
            current_race = {
                'race_number': kosu_no,
                'distance': 0,
                'group_name': '',
                'track_type': '',
                'prize': 0,
                'time': '',
                'horses': [],
            }
            state = 'header_found'
            continue

        if current_race is None:
            continue

        # --- At satırı mı? ---
        if horse_line_re.match(line):
            horse_lines_buf.append(line)
            state = 'collecting_horses'
            continue

        # --- Bahis bilgisi satırı (atla) ---
        if 'GANYAN' in line or 'ÇİFTE' in line or 'PLASE' in line or 'BAHİS' in line:
            continue

        # --- Eküri bilgisi (atla) ---
        if 'ekuridir' in line.lower():
            continue

        # --- Koşu bilgilerini topla ---
        if state in ('header_found', 'collecting_info'):
            state = 'collecting_info'

            # Saat
            tm = time_re.match(line)
            if tm and not current_race['time']:
                current_race['time'] = f"{tm.group(1)}:{tm.group(2)}"
                continue

            # Mesafe + Pist
            dm = dist_re.search(line)
            if dm and not current_race['distance']:
                current_race['distance'] = int(dm.group(1))

            trm = track_re.search(line)
            if trm and not current_race['track_type']:
                current_race['track_type'] = trm.group(2).capitalize()

            # İkramiye
            pm = prize_re.search(line)
            if pm and not current_race['prize']:
                prize_str = pm.group(1).replace('.', '')
                try:
                    current_race['prize'] = float(prize_str)
                except ValueError:
                    pass

            # Grup/tür
            gm = group_re.search(line)
            if gm and not current_race['group_name']:
                # Tüm satırı grup bilgisi olarak al
                current_race['group_name'] = line.strip()

    # Son koşuyu kaydet
    if current_race is not None:
        current_race['horses'] = _parse_horse_lines(horse_lines_buf)
        if current_race['horses']:
            races.append(current_race)

    return races


def _parse_horse_lines(lines):
    """At satırlarını parse et — gerçek TJK formatı."""
    horses = []
    for line in lines:
        h = _parse_one_horse(line)
        if h:
            horses.append(h)
    return horses


def _parse_one_horse(line):
    """
    Tek at satırını parse et.

    Gerçek format:
    1(7) EMİRHAT KG DB SK GKR 4y 58 R.KETME ÖME. ALTIN 31 21 16 7-54436
    2(1) KAPGAN KAĞAN KG SK 4y 58 O.YILDIZ ÖMÜ. ÇALIŞKAN 17 96 17 858
    11(14)GENÇAYNALAN KG K DB 5y 57 C.PASO C. ERD. KOPAL 33 86 11 792850

    Pattern:
    - no(start_no) — at numarası ve start pozisyonu
    - İSİM + TAKILAR (KG, DB, SK, vs.) — yaş pattern'ine kadar
    - Ny — yaş (3y, 4y, 5y, 6y, 7y)
    - kilo — sayı (58, 60.5, 52,5)
    - JOKEY — genelde kısa format (R.KETME, O.YILDIZ)
    - SAHİP/ANTRENÖR — sonraki text
    - SAYILAR — handikap, çim, kum puanları
    - FORM — en sondaki tire içeren sayı dizisi (7-54436, 858, 0-00)
    """
    line = line.strip()

    # At numarası ve start pozisyonu
    m = re.match(r'^(\d{1,2})\s*\((\d{1,2})\)\s*', line)
    if not m:
        return None

    horse_no = int(m.group(1))
    start_no = int(m.group(2))
    rest = line[m.end():]

    # Yaş pattern'ini bul: "4y" veya "3y" vs.
    age_m = re.search(r'\b(\d)y\b', rest)
    if not age_m:
        return None

    age = int(age_m.group(1))

    # Yaş'tan önceki kısım = at adı + takılar
    before_age = rest[:age_m.start()].strip()
    after_age = rest[age_m.end():].strip()

    # At adını takılardan ayır
    name_parts = []
    for word in before_age.split():
        if word.upper() in HORSE_TAGS:
            continue  # Takı, atla
        name_parts.append(word)

    horse_name = " ".join(name_parts).strip()
    if not horse_name:
        return None

    # Kilo: yaştan sonraki ilk sayı
    weight = 0.0
    kilo_m = re.match(r'^([\d]+[,.]?\d*)\s', after_age)
    if kilo_m:
        w_str = kilo_m.group(1).replace(',', '.')
        try:
            weight = float(w_str)
        except ValueError:
            pass
        after_kilo = after_age[kilo_m.end():].strip()
    else:
        after_kilo = after_age

    # Form: en sondaki sayı-tire dizisi
    form = ''
    form_m = re.search(r'([\d][\d\-]*[\d\-])$', after_kilo)
    if form_m:
        candidate = form_m.group(1)
        # En az 3 karakter ve sadece sayı+tire
        if len(candidate) >= 3:
            form = candidate
    else:
        # Sadece sayılardan oluşan son token (tire olmadan)
        tokens = after_kilo.split()
        if tokens:
            last = tokens[-1]
            if re.match(r'^[\d\-]+$', last) and len(last) >= 3:
                form = last

    # Jokey: kilodan sonraki ilk text bloğu (genelde "A.B.SOYİSİM" formatında)
    jockey = ''
    after_kilo_parts = after_kilo.split()
    for part in after_kilo_parts:
        # Jokey adı genelde nokta içerir veya büyük harfle başlar
        if re.match(r'^[A-ZÇĞIİÖŞÜ]', part) and not re.match(r'^[\d\-]+$', part):
            jockey = part
            break

    return {
        'horse_number': horse_no,
        'horse_name': horse_name,
        'age': age,
        'weight': weight,
        'jockey_name': jockey,
        'trainer_name': '',
        'owner_name': '',
        'sire_name': '',
        'dam_name': '',
        'form': form,
        'handicap_rating': 0,
        'start_position': start_no,
    }


# ═══════════════════════════════════════════════════════════════
# PUBLIC API — main.py bu iki fonksiyonu import eder
# ═══════════════════════════════════════════════════════════════

def get_todays_races(target_date=None):
    """
    Günün yarış programını TJK CDN'den çek.
    Returns: list of hippodrome dicts
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime("%d.%m.%Y")
    logger.info(f"Fetching TJK program for {date_str} (PDF CDN)")

    hipodromlar = _discover_hipodromlar(target_date)
    if not hipodromlar:
        logger.warning(f"No races found for {date_str}")
        return []

    logger.info(f"Found hippodromes: {hipodromlar}")

    results = []
    for hip_url in hipodromlar:
        pdf_bytes = _download_pdf(target_date, hip_url)
        if not pdf_bytes:
            continue

        hippo_data = _parse_pdf(pdf_bytes, hip_url, target_date)
        if hippo_data and hippo_data['races']:
            results.append(hippo_data)
            n_horses = sum(len(r['horses']) for r in hippo_data['races'])
            logger.info(f"  {hip_url}: {len(hippo_data['races'])} races, {n_horses} horses")

    return results


def identify_altili_sequences(hippo_data):
    """
    Hipodrom verisinden altılı ganyan dizilerini çıkar.

    TJK PDF'lerinde "6'LI GANYAN Bu koşudan başlar" ibaresi var.
    Eğer bulamazsak son 6 koşuyu alırız.
    """
    races = hippo_data.get('races', [])

    if len(races) < 6:
        logger.warning(f"{hippo_data.get('hippodrome', '?')}: {len(races)} races, need 6")
        return []

    # Son 6 koşu = altılı ganyan
    altili_races = races[-6:]

    return [{
        'hippodrome': hippo_data['hippodrome'],
        'altili_no': 1,
        'races': altili_races,
    }]
