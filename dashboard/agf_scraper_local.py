"""
AGF Scraper Local — agftablosu.com standalone copy for dashboard/
==================================================================
scraper/agf_scraper.py'nin dashboard/ icinde calisan kopyasi.
Cross-package import sorunu olmadan ayni logic.
"""
import requests
import re
import logging
import unicodedata
from datetime import date
from bs4 import BeautifulSoup
from typing import List, Dict, Optional

logger = logging.getLogger(__name__)

AGF_URL = "https://www.agftablosu.com/agf-tablosu"

TURKIYE_HIPODROMLARI = {
    'bursa', 'istanbul', 'ankara', 'izmir', 'adana',
    'elazig', 'elazığ', 'diyarbakir', 'diyarbakır',
    'sanliurfa', 'şanlıurfa', 'antalya', 'kocaeli',
}

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
    result = s.lower()
    result = unicodedata.normalize('NFC', result)
    result = result.replace('\u0307', '')
    return result


def _is_turkiye_hipodromu(hipodrom_name: str) -> bool:
    lower = _tr_lower(hipodrom_name)
    for tag in YABANCI_ETIKETLER:
        if tag in lower:
            return False
    for hip in TURKIYE_HIPODROMLARI:
        if _tr_lower(hip) in lower:
            return True
    return False


def _parse_header(header_text: str) -> Optional[Dict]:
    m = re.search(
        r'(\d{1,2}\s+\w+\s+\d{4}\s+\w+)\s+'
        r'(\d{2}:\d{2})\s+'
        r'(.+?)\s+AGF\s+Tablosu\s+'
        r'(\d+)\.\s*Alt[ıi]l[ıi]',
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
    horses = []
    rows = table_element.find_all('tr')
    for row in rows:
        cells = row.find_all('td')
        for cell in cells:
            text = cell.get_text(strip=True)
            if 'AYAK' in text:
                continue
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
    horses.sort(key=lambda h: h['agf_pct'], reverse=True)
    return horses


def _normalize_hippodrome(raw_name: str) -> str:
    name = raw_name.strip()
    mapping = {
        'Bursa': 'Bursa Hipodromu', 'İstanbul': 'İstanbul Hipodromu',
        'Ankara': 'Ankara Hipodromu', 'İzmir': 'İzmir Hipodromu',
        'Adana': 'Adana Hipodromu', 'Elazığ': 'Elazığ Hipodromu',
        'Diyarbakır': 'Diyarbakır Hipodromu', 'Şanlıurfa': 'Şanlıurfa Hipodromu',
        'Antalya': 'Antalya Hipodromu', 'Kocaeli': 'Kocaeli Hipodromu',
    }
    for key, val in mapping.items():
        if key.lower() in name.lower():
            return val
    if 'Hipodrom' not in name:
        return f"{name} Hipodromu"
    return name


def parse_agf_page(html: str) -> List[Dict]:
    soup = BeautifulSoup(html, 'html.parser')
    altilis = []

    headers = soup.find_all('h3')
    for header in headers:
        header_text = header.get_text(strip=True)
        if 'AGF' not in header_text or 'lt' not in header_text.lower():
            continue

        parsed = _parse_header(header_text)
        if not parsed:
            continue

        hippo = parsed['hippodrome_raw']
        if not _is_turkiye_hipodromu(hippo):
            logger.debug(f"Skipping foreign: {hippo}")
            continue

        # Collect ALL tables between this H3 and next H3
        tables = []
        sibling = header.find_next_sibling()
        while sibling:
            if sibling.name == 'h3':
                break
            if sibling.name == 'table':
                tables.append(sibling)
            elif hasattr(sibling, 'find_all'):
                inner_tables = sibling.find_all('table')
                tables.extend(inner_tables)
            sibling = sibling.find_next_sibling()

        if len(tables) < 6:
            logger.warning(f"{hippo} {parsed['altili_no']}. altili: expected 6 tables, found {len(tables)}")
            if not tables:
                continue

        legs = []
        for tbl in tables[:6]:
            horses = _parse_leg_table(tbl)
            if horses:
                legs.append(horses)

        if len(legs) < 4:
            logger.warning(f"{hippo}: only {len(legs)} valid legs, skipping")
            continue

        hippo_clean = _normalize_hippodrome(hippo)
        altili = {
            'hippodrome': hippo_clean,
            'altili_no': parsed['altili_no'],
            'time': parsed['time'],
            'date_str': parsed['date_str'],
            'legs': legs,
            'source': 'agftablosu_local',
        }

        fav_pcts = [leg[0]['agf_pct'] if leg else 0 for leg in legs]
        logger.info(f"AGF: {hippo_clean} {parsed['altili_no']}. altili — {len(legs)} ayak, favoriler: {fav_pcts}")
        altilis.append(altili)

    logger.info(f"AGF parse complete: {len(altilis)} Turkiye altilisi")
    return altilis


# ═══════════════════════════════════════════
# PUBLIC API
# ═══════════════════════════════════════════

def get_todays_agf(target_date: Optional[date] = None) -> List[Dict]:
    html = fetch_agf_page()
    if not html:
        return []
    return parse_agf_page(html)


def agf_to_legs(agf_altili: Dict) -> List[Dict]:
    legs = []
    for i, agf_leg in enumerate(agf_altili['legs']):
        if not agf_leg:
            legs.append(_empty_leg(i + 1))
            continue
        n_runners = len(agf_leg)
        top_agf = agf_leg[0]['agf_pct'] if agf_leg else 0
        second_agf = agf_leg[1]['agf_pct'] if len(agf_leg) > 1 else 0
        conf = (top_agf - second_agf) / 100.0

        horses = []
        for h in agf_leg:
            score = h['agf_pct'] / 100.0
            feature_dict = {
                'agf_pct': h['agf_pct'],
                'agf_rank': agf_leg.index(h) + 1,
                'is_ekuri': h['is_ekuri'],
            }
            name = f"#{h['horse_number']}"
            horses.append((name, score, h['horse_number'], feature_dict))

        legs.append({
            'horses': horses, 'n_runners': n_runners, 'confidence': conf,
            'model_agreement': 1.0, 'is_arab': False, 'is_english': False,
            'race_number': i + 1, 'distance': '', 'race_type': '', 'group_name': '',
            'top_jockey_name': '', 'top_jockey_wr': 0, 'top_form_top3': 0,
            'agf_data': agf_leg,
        })
    return legs


def _empty_leg(leg_num: int) -> Dict:
    return {
        'horses': [], 'n_runners': 0, 'confidence': 0, 'model_agreement': 0,
        'is_arab': False, 'is_english': False, 'race_number': leg_num,
        'distance': '', 'race_type': '', 'group_name': '',
        'top_jockey_name': '', 'top_jockey_wr': 0, 'top_form_top3': 0, 'agf_data': [],
    }


def enrich_legs_from_pdf(legs: List[Dict], pdf_races: List[Dict]) -> List[Dict]:
    if not pdf_races:
        return legs
    sorted_races = sorted(pdf_races, key=lambda r: r.get('race_number', 0))
    if len(sorted_races) < 6:
        logger.warning(f"  Sadece {len(sorted_races)} kosu var, 6 lazim")
        return legs

    race_counts = {}
    for r in sorted_races:
        rn = r.get('race_number', 0)
        n_horses = len([h for h in r.get('horses', []) if isinstance(h, dict) and h.get('horse_number')])
        race_counts[rn] = n_horses

    agf_counts = []
    for leg in legs:
        n = len([h for h in leg.get('agf_data', []) if h.get('horse_number')])
        agf_counts.append(n)

    best_sequence = None
    best_score = -1
    for start_idx in range(len(sorted_races) - 5):
        candidate = sorted_races[start_idx:start_idx + 6]
        score = 0
        for i, race in enumerate(candidate):
            if i < len(agf_counts):
                race_n = race_counts.get(race.get('race_number', 0), 0)
                agf_n = agf_counts[i]
                if race_n == agf_n: score += 10
                elif abs(race_n - agf_n) <= 1: score += 5
                elif abs(race_n - agf_n) <= 2: score += 2
        if score > best_score:
            best_score = score
            best_sequence = candidate

    if not best_sequence:
        logger.warning("  Ardisik dizi bulunamadi")
        return legs

    start_rn = best_sequence[0].get('race_number', 0)
    end_rn = best_sequence[-1].get('race_number', 0)
    logger.info(f"  Ardisik dizi: Kosu {start_rn}-{end_rn} (skor: {best_score})")

    for i, leg in enumerate(legs):
        if i >= len(best_sequence):
            break
        pdf_race = best_sequence[i]
        rn = pdf_race.get('race_number', 0)

        agf_nums = set()
        for h in leg.get('agf_data', []):
            if h.get('horse_number'):
                agf_nums.add(h['horse_number'])

        race_nums_set = set()
        for h in pdf_race.get('horses', []):
            if isinstance(h, dict) and h.get('horse_number'):
                race_nums_set.add(h['horse_number'])

        overlap = len(agf_nums & race_nums_set) if agf_nums else 0
        logger.info(f"  Leg {i+1} -> Kosu {rn} (overlap: {overlap}, n_horses: {len(agf_nums)})")

        leg['distance'] = pdf_race.get('distance', '') or leg.get('distance', '')
        leg['track_type'] = pdf_race.get('track_type', '') or leg.get('track_type', '')
        leg['race_type'] = pdf_race.get('race_type', '') or leg.get('race_type', '')
        leg['group_name'] = pdf_race.get('group_name', '') or leg.get('group_name', '')
        leg['first_prize'] = pdf_race.get('prize', 0) or leg.get('first_prize', 0)
        leg['race_number'] = pdf_race.get('race_number', rn)

        group = leg.get('group_name', '')
        leg['is_arab'] = 'Arap' in group
        leg['is_english'] = 'İngiliz' in group or 'Ingiliz' in group

        try:
            pdf_horses = {h.get('horse_number', 0): h for h in pdf_race.get('horses', [])
                          if isinstance(h, dict) and h.get('horse_number')}
        except Exception as e:
            logger.warning(f"  Horse dict mapping failed: {e}")
            pdf_horses = {}

        enriched_horses = []
        for name, score, number, feat_dict in leg['horses']:
            if number in pdf_horses:
                pdf_h = pdf_horses[number]
                real_name = pdf_h.get('horse_name', name)
                for k, pk in [('weight','weight'),('jockey','jockey_name'),('trainer','trainer_name'),
                    ('form','form'),('age','age'),('age_text','age_text'),('start_position','start_position'),
                    ('handicap','handicap_rating'),('equipment','equipment'),('kgs','kgs'),
                    ('last_20_score','last_20_score'),('sire','sire_name'),('dam','dam_name'),
                    ('dam_sire','dam_sire_name')]:
                    if pdf_h.get(pk): feat_dict[k] = pdf_h[pk]
                enriched_horses.append((real_name, score, number, feat_dict))
            else:
                enriched_horses.append((name, score, number, feat_dict))
        leg['horses'] = enriched_horses

        if enriched_horses:
            top_feat = enriched_horses[0][3] if len(enriched_horses[0]) > 3 else {}
            leg['top_jockey_name'] = top_feat.get('jockey', '')

    return legs
