"""Altılı Ganyan Dizi Tespiti
Bir hipodromdaki koşulardan altılı dizileri otomatik tespit eder.
TJK'da altılı her zaman 1-6 değil — 3-8, 2-7 gibi de olabiliyor.
"""
import logging
from config import ALTILI_LEG_COUNT, MIN_RACES_FOR_ALTILI

logger = logging.getLogger(__name__)


def detect_altili_sequences(races, tjk_announced=None):
    """
    Hipodromdaki koşu listesinden altılı dizilerini tespit et.

    Args:
        races: list of dict — her biri en az {'race_number': int, ...} içermeli
        tjk_announced: list of dict veya None — TJK'nın ilan ettiği altılı bilgisi
            Örn: [{'altili_no': 1, 'start_race': 1, 'end_race': 6},
                  {'altili_no': 2, 'start_race': 3, 'end_race': 8}]

    Returns:
        list of dict:
            [{'altili_no': 1, 'start_race': 1, 'end_race': 6,
              'race_numbers': [1,2,3,4,5,6], 'source': 'tjk'}, ...]
    """
    if not races:
        return []

    race_numbers = sorted(set(r['race_number'] for r in races))
    total_races = len(race_numbers)

    # ── 1. TJK'nın ilan ettiği altılılar varsa direkt kullan ──
    if tjk_announced:
        sequences = []
        for ann in tjk_announced:
            start = ann['start_race']
            end = ann['end_race']
            nums = [n for n in race_numbers if start <= n <= end]
            if len(nums) == ALTILI_LEG_COUNT:
                sequences.append({
                    'altili_no': ann.get('altili_no', len(sequences) + 1),
                    'start_race': start,
                    'end_race': end,
                    'race_numbers': nums,
                    'source': 'tjk',
                })
                logger.info(f"TJK altılı #{ann.get('altili_no')}: K{start}-K{end}")
        if sequences:
            return sequences

    # ── 2. Otomatik tespit — ardışık 6'lı bloklar bul ──
    if total_races < MIN_RACES_FOR_ALTILI:
        logger.warning(f"Sadece {total_races} koşu var, altılı için en az {MIN_RACES_FOR_ALTILI} lazım")
        return []

    sequences = []

    if total_races == 6:
        # Tam 6 koşu → tek altılı
        sequences.append({
            'altili_no': 1,
            'start_race': race_numbers[0],
            'end_race': race_numbers[-1],
            'race_numbers': race_numbers,
            'source': 'auto',
        })

    elif total_races == 7:
        # 7 koşu → genelde 1-6 veya 2-7
        # TJK convention: genelde ilk 6
        sequences.append({
            'altili_no': 1,
            'start_race': race_numbers[0],
            'end_race': race_numbers[5],
            'race_numbers': race_numbers[:6],
            'source': 'auto_7race',
        })

    elif total_races >= 8:
        # 8+ koşu → muhtemelen 2 altılı var
        # Convention: 1-6 + son 6 (veya 3-8)
        # İlk altılı
        seq1 = race_numbers[:6]
        sequences.append({
            'altili_no': 1,
            'start_race': seq1[0],
            'end_race': seq1[-1],
            'race_numbers': seq1,
            'source': 'auto_multi',
        })

        # İkinci altılı — son 6 koşu (overlap olabilir, sorun yok)
        seq2 = race_numbers[-6:]
        if seq2 != seq1:  # farklıysa ekle
            sequences.append({
                'altili_no': 2,
                'start_race': seq2[0],
                'end_race': seq2[-1],
                'race_numbers': seq2,
                'source': 'auto_multi',
            })

    for seq in sequences:
        logger.info(
            f"Altılı #{seq['altili_no']}: K{seq['start_race']}-K{seq['end_race']} "
            f"({seq['source']})"
        )

    return sequences


def filter_races_for_altili(races, sequence):
    """
    Verilen altılı dizisine ait koşuları filtrele ve sırala.

    Args:
        races: tüm koşu listesi
        sequence: detect_altili_sequences çıktısından tek bir dict

    Returns:
        list of race dicts, altılı sırasına göre (6 adet)
    """
    target_numbers = set(sequence['race_numbers'])
    filtered = [r for r in races if r['race_number'] in target_numbers]
    filtered.sort(key=lambda r: r['race_number'])

    if len(filtered) != ALTILI_LEG_COUNT:
        logger.error(
            f"Altılı #{sequence['altili_no']}: {len(filtered)} koşu bulundu, "
            f"{ALTILI_LEG_COUNT} olmalıydı!"
        )

    return filtered
