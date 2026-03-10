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

            # Strategy 1: extract words with coordinates, split into left/right columns
            col_text = _extract_column_split(pdf)

            # Strategy 2: simple extract_text as fallback
            simple_text = ""
            for page in pdf.pages:
                t = page.extract_text() or ""
                simple_text += t + "\n"

            # Count race headers in each strategy, use the one with more
            import re as _re
            header_re = _re.compile(r'\d+\s*\.\s*[Kk]o[şs]u(?!\s*S\.)(?!l)', _re.IGNORECASE)
            col_count = len(header_re.findall(col_text))
            simple_count = len(header_re.findall(simple_text))

            logger.info(f"Extraction: column-split={len(col_text)} chars/{col_count} races, "
                        f"simple={len(simple_text)} chars/{simple_count} races")

            # Use whichever found more races
            if simple_count > col_count:
                all_text = simple_text
                logger.info("Using simple extraction (more races found)")
            else:
                all_text = col_text
                logger.info("Using column-split extraction")

            if not all_text.strip():
                logger.warning("PDF text extraction returned empty")
                return None

            races = _parse_races(all_text)

            if not races:
                logger.warning(f"No races parsed from PDF ({hipodrom_url})")
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


def _extract_column_split(pdf):
    """Column-aware extraction: left column first, then right."""
    from collections import defaultdict
    all_text = ""
    for page in pdf.pages:
        width = page.width
        mid_x = width / 2

        words = page.extract_words(keep_blank_chars=True) or []
        if not words:
            t = page.extract_text()
            if t:
                all_text += t + "\n"
            continue

        lines_by_y = defaultdict(list)
        for w in words:
            y_key = round(w['top'] / 4) * 4
            lines_by_y[y_key].append(w)

        left_lines = []
        right_lines = []

        for y_key in sorted(lines_by_y.keys()):
            line_words = sorted(lines_by_y[y_key], key=lambda w: w['x0'])

            left_words = [w for w in line_words if w['x0'] < mid_x]
            right_words = [w for w in line_words if w['x0'] >= mid_x]

            if left_words:
                left_lines.append(" ".join(w['text'] for w in left_words))
            if right_words:
                right_lines.append(" ".join(w['text'] for w in right_words))

        all_text += "\n".join(left_lines) + "\n" + "\n".join(right_lines) + "\n"

    return all_text


def _parse_races(text):
    """
    Gerçek TJK PDF formatını parse et.

    PDF çok sütunlu olabilir — pdfplumber satırları birleştirir.
    Örn: "1. Koşu ... 5. Koşu ..." tek satırda.
    Bu yüzden koşu başlıklarını full text'te bulup bölümlere ayırıyoruz.
    """
    # Step 1: Koşu başlıklarını full text'te bul
    # "KoşuS." (footer) ve "Koşul" (tür adı) hariç
    race_header_re = re.compile(r'(\d+)\s*\.\s*[Kk]o[şs]u(?!\s*S\.)(?!l)', re.IGNORECASE)

    matches = list(race_header_re.finditer(text))

    logger.info(f"Found {len(matches)} race headers in {len(text)} chars")
    for m in matches:
        ctx = text[m.start():m.start()+50].replace('\n', ' ')
        logger.info(f"  {int(m.group(1))}. Koşu at pos {m.start()}: '{ctx}'")

    if not matches:
        logger.warning("No race headers found!")
        return []

    # Step 2: Text'i koşu bölümlerine ayır
    sections = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        sections.append((int(m.group(1)), text[start:end]))

    # Step 3: Her bölümü parse et
    horse_line_re = re.compile(r'(\d{1,2})\s*\((\d{1,2})\)')
    dist_re = re.compile(r'(\d{3,4})\s*m[\.\s]')
    track_re = re.compile(r'(\d{3,4})\s*m[\.\s]+\s*(Kum|Çim|Sentetik)', re.IGNORECASE)
    prize_re = re.compile(r'1\.\)\s*([\d.]+)\s*TL')
    time_re = re.compile(r'(?:^|\n)\s*(\d{2})[.:](\d{2})\s*(?:\n|$)')
    group_keywords = ['Maiden', 'Handikap', 'ŞARTLI', 'KV-']

    races = []

    for kosu_no, section in sections:
        race = {
            'race_number': kosu_no,
            'distance': 0,
            'group_name': '',
            'track_type': '',
            'prize': 0,
            'time': '',
            'horses': [],
        }

        # Saat: koşu başlığından hemen sonraki satırda
        tm = time_re.search(section)
        if tm:
            h, mn = int(tm.group(1)), int(tm.group(2))
            if 10 <= h <= 22:
                race['time'] = f"{h:02d}:{mn:02d}"

        # Mesafe
        dm = dist_re.search(section)
        if dm:
            race['distance'] = int(dm.group(1))

        # Pist
        trm = track_re.search(section)
        if trm:
            race['track_type'] = trm.group(2).capitalize()

        # İkramiye
        pm = prize_re.search(section)
        if pm:
            try:
                race['prize'] = float(pm.group(1).replace('.', ''))
            except ValueError:
                pass

        # Grup
        for kw in group_keywords:
            if kw.lower() in section.lower():
                # İlgili satırı bul
                for line in section.split('\n'):
                    if kw.lower() in line.lower():
                        race['group_name'] = line.strip()[:80]
                        break
                break

        # At satırları: section içinde numara(numara) pattern'i ara
        horse_lines = []
        for line in section.split('\n'):
            line = line.strip()
            if not line:
                continue
            if horse_line_re.match(line):
                # Satırda başka koşu başlığı varsa kes
                inner_race = race_header_re.search(line)
                if inner_race and inner_race.start() > 10:
                    line = line[:inner_race.start()].strip()
                if line:
                    horse_lines.append(line)

        race['horses'] = _parse_horse_lines(horse_lines)

        if race['horses']:
            races.append(race)
            logger.info(f"  {kosu_no}. Koşu: {len(race['horses'])} at, "
                       f"{race['distance']}m {race['track_type']} {race['time']}")

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
    - JOKEY — ilk text token (R.KETME, O.YILDIZ)
    - ANTRENÖR/SAHİP — kalan text token'lar (ÖME. ALTIN)
    - SAYILAR — KGS, çim, kum puanları (31 21 16)
    - FORM — en sondaki tire/rakam dizisi (7-54436, 858, 0-00)
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

    # At adını takılardan ayır, equipment'ı yakala
    name_parts = []
    equipment_parts = []
    for word in before_age.split():
        if word.upper() in HORSE_TAGS:
            equipment_parts.append(word.upper())
        else:
            name_parts.append(word)

    horse_name = " ".join(name_parts).strip()
    equipment = " ".join(equipment_parts)
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

    # Token'lara ayır, sondan form'u çıkar
    tokens = after_kilo.split()

    # Form: son token (3+ karakter, rakam/tire)
    form = ''
    if tokens:
        last = tokens[-1]
        if re.match(r'^[\d][\d\-]*$', last) and len(last) >= 3:
            form = last
            tokens = tokens[:-1]

    # Token'ları TEXT ve NUM olarak ayır (sondan başa)
    # NUM'lar = KGS, çim puanı, kum puanı (genelde 2-3 adet)
    # TEXT'ler = jokey + trainer/sahip
    text_tokens = []
    num_tokens = []
    # Sondan geriye git: ardışık NUM'ları topla, ilk TEXT'e gelince dur
    i = len(tokens) - 1
    while i >= 0 and re.match(r'^\d+$', tokens[i]):
        num_tokens.insert(0, tokens[i])
        i -= 1
    text_tokens = tokens[:i + 1]

    # Jokey = ilk text token (noktalı kısa isim: R.KETME, O.YILDIZ, C.PASO)
    jockey = ''
    trainer = ''
    if text_tokens:
        jockey = text_tokens[0]
        # Kalan text = trainer/sahip (ÖME. ALTIN, C. ERD. KOPAL)
        if len(text_tokens) > 1:
            trainer = " ".join(text_tokens[1:])

    # KGS = ilk sayı (gün sayısı), kalan puanlar
    kgs = 0
    handicap_vals = []
    for n in num_tokens:
        try:
            handicap_vals.append(int(n))
        except ValueError:
            pass
    if handicap_vals:
        kgs = handicap_vals[0]  # İlk sayı genelde KGS

    return {
        'horse_number': horse_no,
        'horse_name': horse_name,
        'age': age,
        'weight': weight,
        'jockey_name': jockey,
        'trainer_name': trainer,
        'owner_name': '',
        'sire_name': '',
        'dam_name': '',
        'form': form,
        'equipment': equipment,
        'kgs': kgs,
        'handicap_rating': handicap_vals[1] if len(handicap_vals) >= 2 else 0,
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
