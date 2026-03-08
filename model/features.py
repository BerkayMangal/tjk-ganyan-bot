"""Feature Engineering Pipeline
Converts raw race data into ML features.
Same pipeline used in training and live prediction.
"""
import numpy as np
import pandas as pd
import re
import sqlite3
import os
import logging
from config import ROLLING_DB, MIN_JOCKEY_RIDES, MIN_TRAINER_RIDES, MIN_SIRE_OFFSPRING

logger = logging.getLogger(__name__)


class RollingStats:
    """SQLite-backed rolling statistics for jockeys, trainers, sires"""

    def __init__(self, db_path=ROLLING_DB):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        for entity in ['jockey', 'trainer', 'sire', 'dam_sire', 'sire_sire', 'jt_combo']:
            c.execute(f'''CREATE TABLE IF NOT EXISTS {entity}_stats (
                name TEXT PRIMARY KEY, wins INTEGER DEFAULT 0,
                rides INTEGER DEFAULT 0, top3 INTEGER DEFAULT 0
            )''')
        self.conn.commit()

    def get_stats(self, table, name):
        c = self.conn.cursor()
        c.execute(f'SELECT wins, rides, top3 FROM {table}_stats WHERE name=?', (name,))
        row = c.fetchone()
        return {'wins': row[0], 'rides': row[1], 'top3': row[2]} if row else {'wins': 0, 'rides': 0, 'top3': 0}

    def update_stats(self, table, name, won, top3):
        stats = self.get_stats(table, name)
        c = self.conn.cursor()
        if stats['rides'] == 0:
            c.execute(f'INSERT INTO {table}_stats (name, wins, rides, top3) VALUES (?, ?, 1, ?)',
                      (name, int(won), int(top3)))
        else:
            c.execute(f'UPDATE {table}_stats SET wins=wins+?, rides=rides+1, top3=top3+? WHERE name=?',
                      (int(won), int(top3), name))
        self.conn.commit()

    def close(self):
        self.conn.close()


def parse_last_6(val):
    """Parse 'K4K1K1K7K3K1' -> list of (track_type, position)"""
    if not val or pd.isna(val):
        return []
    return [(t, int(p)) for t, p in re.findall(r'([KC])(\d+)', str(val))]


def build_features_for_race(horses, race_info, rolling_stats=None):
    """
    Build feature vector for each horse in a race.
    horses: list of horse dicts (from scraper)
    race_info: dict with distance, track_type, group_name, first_prize, etc.
    rolling_stats: RollingStats instance (for jockey/trainer/sire stats)

    Returns: pd.DataFrame with one row per horse, columns = feature names
    """
    rows = []

    for h in horses:
        f = {}
        parsed = parse_last_6(h.get('last_6_races', ''))

        # FORM
        positions = [p for _, p in parsed if p > 0]
        f['f_form_avg_pos'] = 1.0 / (np.mean(positions) + 1) if positions else 0.125
        f['f_form_wins'] = sum(1 for p in positions if p == 1) / max(len(positions), 1)
        f['f_form_top3'] = sum(1 for p in positions if 1 <= p <= 3) / max(len(positions), 1)
        f['f_form_last1'] = 1.0 / (positions[-1] + 1) if positions else 0.0

        if len(positions) >= 4:
            mid = len(positions) // 2
            old = np.mean(positions[:mid])
            new = np.mean(positions[mid:])
            f['f_form_trend'] = (old - new) / (old + 1)
        else:
            f['f_form_trend'] = 0.0

        f['f_form_race_count'] = len(parsed) / 6.0
        f['f_form_best'] = 1.0 / (min(positions, default=10) + 1)
        f['f_form_worst'] = 1.0 / (max(positions, default=10) + 1) if positions else 0.0
        f['f_form_consistency'] = 1.0 / (np.std(positions) + 1) if len(positions) >= 2 else 0.0

        dirt_count = sum(1 for t, _ in parsed if t == 'K')
        grass_count = sum(1 for t, _ in parsed if t == 'C')
        total = max(len(parsed), 1)
        f['f_form_dirt_pct'] = dirt_count / total if parsed else 0.5
        f['f_form_grass_pct'] = grass_count / total if parsed else 0.5

        is_dirt = race_info.get('track_type', 'dirt') == 'dirt'
        if parsed:
            if is_dirt:
                f['f_surface_match'] = dirt_count / len(parsed)
            else:
                f['f_surface_match'] = grass_count / len(parsed)
        else:
            f['f_surface_match'] = 0.5

        f['f_last20_score'] = h.get('last_20_score', 0) / 20.0

        # PHYSICAL
        f['f_weight'] = h.get('weight', 56) / 62.0  # rough normalization
        dist = race_info.get('distance', 1400)
        f['f_distance'] = dist / 2400.0
        f['f_dist_short'] = 1.0 if dist <= 1200 else 0.0
        f['f_dist_mid'] = 1.0 if 1200 < dist <= 1600 else 0.0
        f['f_dist_mile'] = 1.0 if 1600 < dist <= 2000 else 0.0
        f['f_dist_long'] = 1.0 if dist > 2000 else 0.0
        f['f_gate'] = h.get('gate_number', 5) / 14.0
        f['f_handicap'] = h.get('handicap', 60) / 75.0
        f['f_extra_weight'] = h.get('extra_weight', 0) / 5.0

        # HORSE PROFILE
        age_match = re.search(r'(\d+)y', h.get('age_text', '4y'))
        age = int(age_match.group(1)) if age_match else 4
        f['f_age'] = age / 11.0
        f['f_age_young'] = 1.0 if age <= 3 else 0.0
        f['f_age_prime'] = 1.0 if 4 <= age <= 6 else 0.0
        f['f_age_veteran'] = 1.0 if age >= 7 else 0.0

        group = race_info.get('group_name', '')
        f['f_is_arab'] = 1.0 if 'Arap' in group else 0.0
        f['f_is_english'] = 1.0 if 'İngiliz' in group or 'Ingiliz' in group else 0.0

        age_parts = h.get('age_text', '').split()
        gender = age_parts[2] if len(age_parts) >= 3 else ''
        f['f_gender_stallion'] = 1.0 if gender == 'a' else 0.0
        f['f_gender_mare'] = 1.0 if gender == 'k' else 0.0
        f['f_gender_gelding'] = 1.0 if gender == 'e' else 0.0

        kgs = h.get('kgs', 30)
        f['f_days_rest'] = min(kgs, 200) / 200.0
        f['f_fresh'] = 1.0 if kgs <= 14 else 0.0
        f['f_rested'] = 1.0 if kgs >= 30 else 0.0

        earnings = h.get('total_earnings', 0)
        f['f_earnings'] = min(earnings / 5000000.0, 1.0)
        f['f_earnings_log'] = np.log1p(earnings) / 16.0  # log(5M) ≈ 15.4

        # JOCKEY / TRAINER / PEDIGREE (from rolling stats)
        if rolling_stats:
            js = rolling_stats.get_stats('jockey', h.get('jockey_name', ''))
            f['f_jockey_win_rate'] = js['wins'] / js['rides'] if js['rides'] >= MIN_JOCKEY_RIDES else 0.0
            f['f_jockey_top3_rate'] = js['top3'] / js['rides'] if js['rides'] >= MIN_JOCKEY_RIDES else 0.0
            f['f_jockey_experience'] = min(js['rides'] / 200.0, 1.0)

            ts = rolling_stats.get_stats('trainer', h.get('trainer_name', ''))
            f['f_trainer_win_rate'] = ts['wins'] / ts['rides'] if ts['rides'] >= MIN_TRAINER_RIDES else 0.0
            f['f_trainer_experience'] = min(ts['rides'] / 100.0, 1.0)

            # Jockey-trainer combo
            combo_key = f"{h.get('jockey_name', '')}||{h.get('trainer_name', '')}"
            cs = rolling_stats.get_stats('jt_combo', combo_key)
            f['f_jt_combo_wr'] = cs['wins'] / cs['rides'] if cs['rides'] >= 5 else 0.0

            for col, table in [('sire', 'sire'), ('dam_sire', 'dam_sire'), ('sire_sire', 'sire_sire')]:
                val = h.get(col, '')
                if val:
                    ss = rolling_stats.get_stats(table, val)
                    f[f'f_{table}_win_rate'] = ss['wins'] / ss['rides'] if ss['rides'] >= MIN_SIRE_OFFSPRING else 0.0
                else:
                    f[f'f_{table}_win_rate'] = 0.0
        else:
            for feat in ['f_jockey_win_rate', 'f_jockey_top3_rate', 'f_jockey_experience',
                         'f_trainer_win_rate', 'f_trainer_experience', 'f_jt_combo_wr',
                         'f_sire_win_rate', 'f_dam_sire_win_rate', 'f_sire_sire_win_rate']:
                f[feat] = 0.0

        # CONDITIONS
        f['f_is_dirt'] = 1.0 if is_dirt else 0.0
        f['f_is_synthetic'] = 0.0 if is_dirt else 1.0
        f['f_hippodrome'] = 0.5  # Will be set per hippodrome
        f['f_temperature'] = 0.5  # From weather if available
        f['f_humidity'] = 0.5
        f['f_race_class'] = np.log1p(race_info.get('first_prize', 400000)) / 16.5
        n_runners = len(horses)
        f['f_field_size'] = n_runners / 16.0
        f['f_is_weekend'] = 0.0  # Set by caller
        f['f_day_of_week'] = 0.0  # Set by caller

        # EQUIPMENT
        equip = h.get('equipment', '')
        f['f_equip_kg'] = 1.0 if 'KG' in equip else 0.0
        f['f_equip_db'] = 1.0 if 'DB' in equip else 0.0
        f['f_equip_sk'] = 1.0 if re.search(r'\bSK\b', equip) else 0.0
        f['f_equip_skg'] = 1.0 if 'SKG' in equip else 0.0
        f['f_equip_count'] = len(equip.split()) / 4.0 if equip else 0.0

        # INTERACTIONS
        f['f_X_jockey_form'] = f['f_jockey_win_rate'] * f['f_form_wins']
        f['f_X_jockey_trainer'] = f['f_jockey_win_rate'] * f['f_trainer_win_rate']
        f['f_X_sire_dist'] = f['f_sire_win_rate'] * f['f_distance']
        f['f_X_age_trend'] = f['f_age'] * f['f_form_trend']
        f['f_X_surface_form'] = f['f_surface_match'] * f['f_form_avg_pos']
        f['f_X_form_class'] = f['f_form_avg_pos'] * f['f_race_class']
        f['f_X_jockey_class'] = f['f_jockey_win_rate'] * f['f_race_class']
        f['f_X_earnings_form'] = f['f_earnings_log'] * f['f_form_avg_pos']
        f['f_X_trainer_form'] = f['f_trainer_win_rate'] * f['f_form_avg_pos']
        f['f_X_jt_combo_form'] = f['f_jt_combo_wr'] * f['f_form_top3']
        f['f_X_form_field'] = f['f_form_avg_pos'] * f['f_field_size']
        f['f_X_earnings_class'] = f['f_earnings_log'] * f['f_race_class']

        f['_horse_name'] = h.get('horse_name', '')
        f['_horse_number'] = h.get('horse_number', 0)
        f['_jockey_name'] = h.get('jockey_name', '')
        f['_trainer_name'] = h.get('trainer_name', '')
        f['_sire'] = h.get('sire', '')
        f['_odds'] = h.get('final_odds', 0)

        rows.append(f)

    return pd.DataFrame(rows)


# Feature column order (must match training)
FEATURE_COLUMNS = [
    'f_form_avg_pos', 'f_form_wins', 'f_form_top3', 'f_form_trend',
    'f_form_race_count', 'f_form_best', 'f_form_worst', 'f_form_consistency',
    'f_form_dirt_pct', 'f_form_grass_pct', 'f_surface_match', 'f_last20_score',
    'f_form_last1',
    'f_weight', 'f_distance', 'f_dist_short', 'f_dist_mid', 'f_dist_mile',
    'f_dist_long', 'f_gate', 'f_handicap', 'f_extra_weight',
    'f_age', 'f_age_young', 'f_age_prime', 'f_age_veteran',
    'f_is_arab', 'f_is_english',
    'f_gender_stallion', 'f_gender_mare', 'f_gender_gelding',
    'f_days_rest', 'f_fresh', 'f_rested', 'f_earnings', 'f_earnings_log',
    'f_jockey_win_rate', 'f_jockey_top3_rate', 'f_jockey_experience',
    'f_trainer_win_rate', 'f_trainer_experience', 'f_jt_combo_wr',
    'f_sire_win_rate', 'f_dam_sire_win_rate', 'f_sire_sire_win_rate',
    'f_is_dirt', 'f_is_synthetic', 'f_hippodrome', 'f_temperature', 'f_humidity',
    'f_race_class', 'f_field_size', 'f_is_weekend', 'f_day_of_week',
    'f_equip_kg', 'f_equip_db', 'f_equip_sk', 'f_equip_skg', 'f_equip_count',
    'f_X_jockey_form', 'f_X_jockey_trainer', 'f_X_sire_dist', 'f_X_age_trend',
    'f_X_surface_form', 'f_X_form_class', 'f_X_jockey_class',
    'f_X_earnings_form', 'f_X_trainer_form', 'f_X_jt_combo_form',
    'f_X_form_field', 'f_X_earnings_class',
]
