"""TJK Daily Program Scraper
Fetches today's race card from tjk.org
Returns structured data for each race: horses, jockeys, trainers, weights, etc.
"""
import requests
from bs4 import BeautifulSoup
from datetime import datetime, date
import json
import re
import logging

logger = logging.getLogger(__name__)

TJK_PROGRAM_URL = "https://www.tjk.org/TR/YarisSever/Info/GunlukYarisProgrami"
TJK_BULTEN_URL = "https://www.tjk.org/TR/YarisSever/Info/Bulten"


def get_todays_races(target_date=None):
    """
    Fetch today's race program from TJK.
    Returns list of dicts, one per hippodrome:
    [
        {
            'hippodrome': 'İstanbul Veliefendi Hipodromu',
            'date': '2026-03-08',
            'races': [
                {
                    'race_number': 1,
                    'race_id': 78200,
                    'distance': 1200,
                    'track_type': 'dirt',
                    'group_name': '3 Yaşlı İngilizler',
                    'first_prize': 490000,
                    'horses': [
                        {
                            'horse_number': 1,
                            'horse_name': 'SHARP STORM',
                            'jockey_name': 'KADİR TOKAÇOĞLU',
                            'trainer_name': 'HÜSEYİN KARABULUT',
                            'weight': 56.0,
                            'handicap': 61,
                            'gate_number': 2,
                            'extra_weight': 0.0,
                            'last_6_races': 'K4K1K1K7K3K1',
                            'last_20_score': 20,
                            'equipment': 'KG DB SK',
                            'age_text': '3y d e',
                            'sire': 'SHARP KNIFE (USA)',
                            'dam': 'CHARMING PRINCESS',
                            'dam_sire': 'LION HEART (USA)',
                            'kgs': 14,
                        },
                        ...
                    ]
                },
                ...
            ]
        },
        ...
    ]
    """
    if target_date is None:
        target_date = date.today()

    date_str = target_date.strftime('%d/%m/%Y')
    logger.info(f"Fetching TJK program for {date_str}")

    try:
        # Try API endpoint first
        program = _fetch_from_api(target_date)
        if program:
            return program
    except Exception as e:
        logger.warning(f"API fetch failed: {e}, trying HTML scrape")

    try:
        # Fallback: HTML scrape
        program = _fetch_from_html(target_date)
        if program:
            return program
    except Exception as e:
        logger.error(f"HTML scrape failed: {e}")

    return []


def _fetch_from_api(target_date):
    """Try TJK's JSON API"""
    date_str = target_date.strftime('%Y-%m-%d')

    # TJK sometimes has an undocumented JSON endpoint
    url = f"https://www.tjk.org/TR/YarisSever/Query/ConnectedRaceCards/GunlukYarisProgrami?QueryParameter_Tarih={date_str}"

    headers = {
        'User-Agent': 'Mozilla/5.0',
        'Accept': 'application/json',
        'X-Requested-With': 'XMLHttpRequest',
    }

    resp = requests.get(url, headers=headers, timeout=30)
    if resp.status_code == 200 and resp.text.strip().startswith('{'):
        data = resp.json()
        return _parse_api_response(data, target_date)

    return None


def _fetch_from_html(target_date):
    """Scrape TJK HTML program page"""
    date_str = target_date.strftime('%d/%m/%Y')

    headers = {'User-Agent': 'Mozilla/5.0'}
    resp = requests.get(
        f"{TJK_BULTEN_URL}?QueryParameter_Tarih={date_str}",
        headers=headers, timeout=30
    )
    resp.raise_for_status()

    soup = BeautifulSoup(resp.text, 'lxml')
    # Parse structure depends on TJK's current HTML layout
    # This is a template — actual parsing needs to match TJK's DOM

    hippodromes = []
    # Find hippodrome sections
    for section in soup.select('.race-card, .program-section, [data-hippodrome]'):
        hippo_name = section.get('data-hippodrome', '')
        if not hippo_name:
            header = section.select_one('h2, h3, .hippodrome-name')
            if header:
                hippo_name = header.get_text(strip=True)

        races = []
        for race_elem in section.select('.race, .kosu, [data-race-number]'):
            race = _parse_race_html(race_elem)
            if race:
                races.append(race)

        if races:
            hippodromes.append({
                'hippodrome': hippo_name,
                'date': target_date.isoformat(),
                'races': races,
            })

    return hippodromes


def _parse_api_response(data, target_date):
    """Parse TJK API JSON into our format"""
    # Structure varies — this is a general parser
    hippodromes = []

    race_list = data.get('races', data.get('Races', data.get('kosu_listesi', [])))
    if isinstance(data, list):
        race_list = data

    # Group by hippodrome
    hippo_map = {}
    for race in race_list:
        hippo = race.get('hippodrome', race.get('Hippodrome', race.get('sehir', 'Unknown')))
        if hippo not in hippo_map:
            hippo_map[hippo] = []

        horses = []
        for h in race.get('horses', race.get('atlar', [])):
            horses.append({
                'horse_number': int(h.get('horse_number', h.get('atNo', 0))),
                'horse_name': h.get('horse_name', h.get('atAdi', '')).strip().upper(),
                'jockey_name': h.get('jockey_name', h.get('jokeyAdi', '')).strip(),
                'trainer_name': h.get('trainer_name', h.get('antrenorAdi', '')).strip(),
                'weight': float(h.get('weight', h.get('kilo', 0))),
                'handicap': int(h.get('handicap', h.get('hp', 0))),
                'gate_number': int(h.get('gate_number', h.get('kulvar', 0))),
                'extra_weight': float(h.get('extra_weight', h.get('ekKilo', 0))),
                'last_6_races': h.get('last_6_races', h.get('son6', '')),
                'last_20_score': int(h.get('last_20_score', h.get('puan', 0))),
                'equipment': h.get('equipment', h.get('taki', '')),
                'age_text': h.get('age_text', h.get('yas', '')),
                'sire': h.get('sire', h.get('baba', '')),
                'dam': h.get('dam', h.get('anne', '')),
                'dam_sire': h.get('dam_sire', h.get('anneBaba', '')),
                'kgs': int(h.get('kgs', h.get('gunSayisi', 0))),
                'total_earnings': float(h.get('total_earnings', h.get('kazanc', 0))),
            })

        hippo_map[hippo].append({
            'race_number': int(race.get('race_number', race.get('kosuNo', 0))),
            'race_id': int(race.get('race_id', race.get('kosuId', 0))),
            'distance': int(race.get('distance', race.get('mesafe', 0))),
            'track_type': race.get('track_type', race.get('pist', 'dirt')),
            'group_name': race.get('group_name', race.get('grup', '')),
            'first_prize': float(race.get('first_prize', race.get('ikramiye', 0))),
            'horses': horses,
        })

    for hippo, races in hippo_map.items():
        hippodromes.append({
            'hippodrome': hippo,
            'date': target_date.isoformat(),
            'races': sorted(races, key=lambda r: r['race_number']),
        })

    return hippodromes


def _parse_race_html(elem):
    """Parse a single race from HTML"""
    # Template — needs customization based on actual TJK DOM
    return None


def identify_altili_sequences(hippo_data):
    """
    Given a hippodrome's races, identify 6'li ganyan sequences.
    Returns list of sequences (each = list of 6 race dicts).
    Typically: last 6 races = 1. altili
    If 9+ races: first 6 = 2. altili, last 6 = 1. altili
    """
    races = sorted(hippo_data['races'], key=lambda r: r['race_number'])
    if len(races) < 6:
        return []

    sequences = []

    # Last 6 = main altili
    sequences.append({
        'altili_no': 1,
        'races': races[-6:],
        'hippodrome': hippo_data['hippodrome'],
        'date': hippo_data['date'],
    })

    # If 9+, first 6 = second altili
    if len(races) >= 9:
        first6 = races[:6]
        last6_ids = {r['race_number'] for r in races[-6:]}
        first6_ids = {r['race_number'] for r in first6}
        if first6_ids != last6_ids:
            sequences.append({
                'altili_no': 2,
                'races': first6,
                'hippodrome': hippo_data['hippodrome'],
                'date': hippo_data['date'],
            })

    return sequences


if __name__ == '__main__':
    # Test
    logging.basicConfig(level=logging.INFO)
    program = get_todays_races()
    for h in program:
        print(f"\n{h['hippodrome']}: {len(h['races'])} races")
        for r in h['races']:
            print(f"  R{r['race_number']}: {r['distance']}m {r['group_name']} — {len(r['horses'])} horses")
