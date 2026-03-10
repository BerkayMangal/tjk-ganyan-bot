"""
AGF Scraper — agftablosu.com'dan Altılı Ganyan Favori yüzdelerini çeker
==========================================================================
Primary data source for TJK Bot V5.

agftablosu.com yapısı:
  - /agf-tablosu sayfasında günün TÜM altılıları var
  - Başlık: "9 Mart 2026 Pazartesi 14:00 Bursa AGF Tablosu 1. Altılı"
  - Her ayakta: "3 (%42.50)" veya "6 (%6.70) *E*" formatında at listesi
  - *E* = eküri

Returns: list of altili dicts, her biri 6 ayak, her ayakta at listesi + AGF %
"""
import requests
import re
import logging
from datetime import date
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

AGF_URL = "https://www.agftablosu.com/agf-tablosu"

# Sadece Türkiye hipodromları — yabancı yarışları filtrele
TURKIYE_HIPODROMLARI = {
    'bursa', 'istanbul', 'ankara', 'izmir', 'adana',
    'elazig', 'elazığ', 'diyarbakir', 'diyarbakır',
    'sanliurfa', 'şanlıurfa', 'antalya', 'kocaeli',
}

# Yabancı ülke etiketleri — bunları filtrele
YABANCI_ETIKETLER = [
    'fransa', 'abd', 'ingiltere', 'güney afrika', 'malezya',
    'hong kong', 'avustralya', 'birleşik arap', 'suudi',
    'singapur', 'japonya', 'irlanda',
]

SESSION = requests.Session()
SESSION.headers.update({
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 '
                  '(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    'Accept': 'text/html,application/xhtml+xml',
    'Accept-Language': 'tr-TR,tr;q=0.9',
})


def fetch_agf_page() -> Optional[str]:
    """AGF tablosu sayfasını çek."""
    try:
        resp = SESSION.get(AGF_URL, timeout=30)
        if resp.status_code == 200:
            logger.info(f"AGF page fetched: {len(resp.text)} chars")
            return resp.text
        logger.warning(f"AGF page HTTP {resp.status_code}")
        return None
    except Exception as e:
        logger.error(f"AGF fetch error: {e}")
        return None


def _tr_lower(s: str) -> str:
    """Turkish-safe lowercase: İ→i, Ş→ş, etc."""
    import unicodedata
    # Python's İ.lower() = i̇ (i + combining dot above U+0307)
    # Strip that combining mark for clean comparison
    result = s.lower()
    result = unicodedata.normalize('NFC', result)
    result = result.replace('\u0307', '')  # remove combining dot above
    return result


def _is_turkiye_hipodromu(hipodrom_name: str) -> bool:
    """Hipodromun Türkiye'de olup olmadığını kontrol et."""
    lower = _tr_lower(hipodrom_name)

    # Yabancı etiket varsa reddet
    for tag in YABANCI_ETIKETLER:
        if tag in lower:
            return False

    # Türkiye hipodromu mu?
    for hip in TURKIYE_HIPODROMLARI:
        if _tr_lower(hip) in lower:
            return True

    return False


def _parse_header(header_text: str) -> Optional[Dict]:
    """
    Başlık parse et.
    Örn: "9 Mart 2026 Pazartesi 14:00 Bursa AGF Tablosu 1. Altılı"

    Returns: {hippodrome, altili_no, time, date_str} or None
    """
    # Pattern: tarih saat ŞEHİR AGF Tablosu N. Altılı
    m = re.search(
        r'(\d{1,2}\s+\w+\s+\d{4}\s+\w+)\s+'  # tarih + gün
        r'(\d{2}:\d{2})\s+'                     # saat
        r'(.+?)\s+AGF\s+Tablosu\s+'             # hipodrom adı
        r'(\d+)\.\s*Alt[ıi]l[ıi]',              # altılı no
        header_text, re.IGNORECASE
    )
    if not m:
        return None

    return {
        'date_str': m.group(1).strip(),
        'time': m.group(2).strip(),
        'hippodrome_raw': m.group(3).strip(),
        'altili_no': int(m.group(4)),
    }


def _parse_leg_table(table_element) -> List[Dict]:
    """
    Tek bir ayak tablosunu parse et.

    Her satır: "3 (%42.50)" veya "6 (%6.70) *E*"

    Returns: list of {horse_number, agf_pct, is_ekuri} sorted by agf_pct desc
    """
    horses = []

    rows = table_element.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        for cell in cells:
            text = cell.get_text(strip=True)

            # "1. AYAK" başlık satırını atla
            if 'AYAK' in text:
                continue

            # Pattern: "3 (%42.50)" veya "3 (%42.50) *E*" veya "3 (%42.50) E"
            m = re.match(r'(\d{1,2})\s*\(%?([\d.]+)%?\)', text)
            if m:
                horse_no = int(m.group(1))
                agf_pct = float(m.group(2))
                is_ekuri = '*E*' in text or text.strip().endswith('E')

                horses.append({
                    'horse_number': horse_no,
                    'agf_pct': agf_pct,
                    'is_ekuri': is_ekuri,
                })

    # AGF'ye göre sıralı (büyükten küçüğe) — zaten öyle gelmeli ama garanti
    horses.sort(key=lambda h: h['agf_pct'], reverse=True)

    return horses


def parse_agf_page(html: str) -> List[Dict]:
    """
    AGF sayfasını parse et, sadece Türkiye hipodromlarını döndür.

    Returns: list of altili dicts:
    [
        {
            'hippodrome': 'Bursa',
            'altili_no': 1,
            'time': '14:00',
            'date_str': '9 Mart 2026 Pazartesi',
            'legs': [
                [  # 1. ayak
                    {'horse_number': 3, 'agf_pct': 42.50, 'is_ekuri': False},
                    {'horse_number': 1, 'agf_pct': 22.44, 'is_ekuri': False},
                    ...
                ],
                ...  # 6 ayak toplam
            ]
        },
        ...
    ]
    """
    soup = BeautifulSoup(html, 'html.parser')
    altilis = []

    # H3 başlıkları altılıları tanımlar
    headers = soup.find_all('h3')

    for header in headers:
        header_text = header.get_text(strip=True)

        # "AGF Tablosu" + "Altılı" içermeyen başlıkları atla
        if 'AGF' not in header_text or 'lt' not in header_text.lower():
            continue

        parsed = _parse_header(header_text)
        if not parsed:
            continue

        hippo = parsed['hippodrome_raw']

        # Türkiye filtresi
        if not _is_turkiye_hipodromu(hippo):
            logger.debug(f"Skipping foreign: {hippo}")
            continue

        # Bu başlıktan sonraki tabloları topla (sonraki h3'e kadar)
        tables = []
        sibling = header.find_next_sibling()
        while sibling:
            if sibling.name == 'h3':
                break
            if sibling.name == 'table':
                tables.append(sibling)
            elif hasattr(sibling, 'find_all'):
                # Bazen tablolar div içinde olabiliyor
                inner_tables = sibling.find_all('table')
                tables.extend(inner_tables)
            sibling = sibling.find_next_sibling()

        if len(tables) < 6:
            logger.warning(
                f"{hippo} {parsed['altili_no']}. altılı: "
                f"expected 6 tables, found {len(tables)}"
            )
            # Yine de devam et, ne kadar varsa alalım
            if not tables:
                continue

        # Her tablo = 1 ayak
        legs = []
        for tbl in tables[:6]:
            horses = _parse_leg_table(tbl)
            if horses:
                legs.append(horses)

        if len(legs) < 6:
            logger.warning(
                f"{hippo} {parsed['altili_no']}. altılı: "
                f"only {len(legs)} valid legs (need 6)"
            )
            if len(legs) < 4:  # 4'ten azsa boşver
                continue

        # Hipodrom adını normalize et
        hippo_clean = _normalize_hippodrome(hippo)

        altili = {
            'hippodrome': hippo_clean,
            'altili_no': parsed['altili_no'],
            'time': parsed['time'],
            'date_str': parsed['date_str'],
            'legs': legs,
            'source': 'agftablosu',
        }

        # Özet log
        fav_pcts = [leg[0]['agf_pct'] if leg else 0 for leg in legs]
        logger.info(
            f"AGF: {hippo_clean} {parsed['altili_no']}. altılı — "
            f"{len(legs)} ayak, favoriler: {fav_pcts}"
        )

        altilis.append(altili)

    logger.info(f"AGF parse complete: {len(altilis)} Türkiye altılısı bulundu")
    return altilis


def _normalize_hippodrome(raw_name: str) -> str:
    """AGF hipodrom adını standart formata çevir."""
    name = raw_name.strip()

    # Yaygın eşleştirmeler
    mapping = {
        'Bursa': 'Bursa Hipodromu',
        'İstanbul': 'İstanbul Hipodromu',
        'Ankara': 'Ankara Hipodromu',
        'İzmir': 'İzmir Hipodromu',
        'Adana': 'Adana Hipodromu',
        'Elazığ': 'Elazığ Hipodromu',
        'Diyarbakır': 'Diyarbakır Hipodromu',
        'Şanlıurfa': 'Şanlıurfa Hipodromu',
        'Antalya': 'Antalya Hipodromu',
        'Kocaeli': 'Kocaeli Hipodromu',
    }

    for key, val in mapping.items():
        if key.lower() in name.lower():
            return val

    # Fallback: Hipodromu ekle
    if 'Hipodrom' not in name:
        return f"{name} Hipodromu"
    return name


# ═══════════════════════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════════════════════

def get_todays_agf(target_date: Optional[date] = None) -> List[Dict]:
    """
    Günün AGF verilerini çek ve parse et.

    Args:
        target_date: şimdilik kullanılmıyor (agftablosu hep bugünü gösterir)

    Returns: list of altili dicts (sadece Türkiye)
    """
    html = fetch_agf_page()
    if not html:
        return []

    altilis = parse_agf_page(html)
    return altilis


def agf_to_legs(agf_altili: Dict) -> List[Dict]:
    """
    AGF altılı dict'ini main.py'nin beklediği leg formatına çevir.

    Input (agf_altili['legs'][i]):
        [{'horse_number': 3, 'agf_pct': 42.50, 'is_ekuri': False}, ...]

    Output (leg dict):
        {
            'horses': [(name, score, number, feature_dict), ...],
            'n_runners': 10,
            'confidence': 0.42,  # favori AGF - 2. at AGF
            'agf_data': [...],   # ham AGF verisi
            ...
        }
    """
    legs = []

    for i, agf_leg in enumerate(agf_altili['legs']):
        if not agf_leg:
            legs.append(_empty_leg(i + 1))
            continue

        n_runners = len(agf_leg)
        top_agf = agf_leg[0]['agf_pct'] if agf_leg else 0
        second_agf = agf_leg[1]['agf_pct'] if len(agf_leg) > 1 else 0

        # Confidence = AGF fark (favori ile 2. at arası)
        # AGF %50+ net favori → confidence yüksek
        conf = (top_agf - second_agf) / 100.0

        # Score olarak AGF yüzdesini normalize et (0-1 arası)
        horses = []
        for h in agf_leg:
            score = h['agf_pct'] / 100.0
            feature_dict = {
                'agf_pct': h['agf_pct'],
                'agf_rank': agf_leg.index(h) + 1,
                'is_ekuri': h['is_ekuri'],
            }
            # At ismi yok AGF'de — numara ile göster, PDF'ten zenginleştirilecek
            name = f"#{h['horse_number']}"
            horses.append((name, score, h['horse_number'], feature_dict))

        # AGF-bazlı ayak sınıflandırma
        is_arab = False  # AGF'den bilemiyoruz, PDF'ten gelecek
        is_english = False

        legs.append({
            'horses': horses,
            'n_runners': n_runners,
            'confidence': conf,
            'model_agreement': 1.0,  # AGF = piyasa konsensüsü
            'is_arab': is_arab,
            'is_english': is_english,
            'race_number': i + 1,  # placeholder, PDF'ten override edilecek
            'distance': '',
            'race_type': '',
            'group_name': '',
            'top_jockey_name': '',
            'top_jockey_wr': 0,
            'top_form_top3': 0,
            'agf_data': agf_leg,  # ham veri saklansın
        })

    return legs


def _empty_leg(leg_num: int) -> Dict:
    """Boş ayak (veri yoksa fallback)."""
    return {
        'horses': [],
        'n_runners': 0,
        'confidence': 0,
        'model_agreement': 0,
        'is_arab': False,
        'is_english': False,
        'race_number': leg_num,
        'distance': '',
        'race_type': '',
        'group_name': '',
        'top_jockey_name': '',
        'top_jockey_wr': 0,
        'top_form_top3': 0,
        'agf_data': [],
    }


def enrich_legs_from_pdf(legs: List[Dict], pdf_races: List[Dict]) -> List[Dict]:
    """
    PDF'ten çekilen detay bilgileri ile AGF leg'lerini zenginleştir.

    Eşleştirme: at numarası üzerinden.
    PDF koşu numarasına göre eşleştirme (pozisyon değil!).
    """
    if not pdf_races:
        return legs

    # PDF koşularını numara bazlı index'le
    pdf_by_racenum = {}
    for pr in pdf_races:
        rn = pr.get('race_number', 0)
        if rn > 0:
            pdf_by_racenum[rn] = pr

    # Altılı ayak → koşu numarası eşleştirmesi
    # AGF leg sırası 1-6, ama koşu numaraları farklı olabilir (3-8, 2-7 vs.)
    # Eğer leg'te race_number varsa onu kullan, yoksa pozisyon bazlı dene
    for i, leg in enumerate(legs):
        leg_rn = leg.get('race_number', i + 1)

        # Önce race_number ile eşleştir
        pdf_race = pdf_by_racenum.get(leg_rn)

        # Bulamazsa pozisyon bazlı dene
        if not pdf_race and i < len(pdf_races):
            pdf_race = pdf_races[i]

        if not pdf_race:
            continue

        # Koşu bilgileri
        leg['distance'] = pdf_race.get('distance', '') or leg.get('distance', '')
        leg['track_type'] = pdf_race.get('track_type', '') or leg.get('track_type', '')
        leg['race_type'] = pdf_race.get('race_type', '') or leg.get('race_type', '')
        leg['group_name'] = pdf_race.get('group_name', '') or leg.get('group_name', '')
        leg['first_prize'] = pdf_race.get('prize', 0) or leg.get('first_prize', 0)
        leg['race_number'] = pdf_race.get('race_number', leg_rn)

        # Cins tespiti
        group = leg.get('group_name', '')
        leg['is_arab'] = 'Arap' in group
        leg['is_english'] = 'İngiliz' in group or 'Ingiliz' in group

        # At isimlerini eşleştir — horse_number bazlı
        pdf_horses = {h['horse_number']: h for h in pdf_race.get('horses', [])}

        enriched_horses = []
        for name, score, number, feat_dict in leg['horses']:
            if number in pdf_horses:
                pdf_h = pdf_horses[number]
                real_name = pdf_h.get('horse_name', name)
                feat_dict['weight'] = pdf_h.get('weight', 0)
                feat_dict['jockey'] = pdf_h.get('jockey_name', '')
                feat_dict['form'] = pdf_h.get('form', '')
                feat_dict['age'] = pdf_h.get('age', 0)
                feat_dict['start_position'] = pdf_h.get('start_position', 0)
                feat_dict['handicap'] = pdf_h.get('handicap_rating', 0)
                enriched_horses.append((real_name, score, number, feat_dict))
            else:
                enriched_horses.append((name, score, number, feat_dict))

        leg['horses'] = enriched_horses

        # Jokey bilgisi güncelle
        if enriched_horses:
            top_feat = enriched_horses[0][3] if len(enriched_horses[0]) > 3 else {}
            leg['top_jockey_name'] = top_feat.get('jockey', '')

    return legs


# ═══════════════════════════════════════════════════════════
# STANDALONE TEST
# ═══════════════════════════════════════════════════════════

if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)

    print("=" * 60)
    print("AGF SCRAPER TEST")
    print("=" * 60)

    altilis = get_todays_agf()

    if not altilis:
        print("Bugün AGF verisi yok veya çekilemedi!")
    else:
        print(f"\n{len(altilis)} Türkiye altılısı bulundu:\n")

        for alt in altilis:
            print(f"🏇 {alt['hippodrome']} — {alt['altili_no']}. Altılı ({alt['time']})")

            for i, leg in enumerate(alt['legs']):
                fav = leg[0] if leg else None
                n = len(leg)

                if fav:
                    fav_str = f"#{fav['horse_number']} (%{fav['agf_pct']:.1f})"
                    # İlk 3 at
                    top3 = ", ".join(
                        f"#{h['horse_number']}(%{h['agf_pct']:.1f})"
                        for h in leg[:3]
                    )
                    print(f"  {i+1}. Ayak ({n} at): {top3}")
                else:
                    print(f"  {i+1}. Ayak: VERİ YOK")

            print()
