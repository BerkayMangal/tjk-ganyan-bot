"""Feature Engineering Pipeline — V4
Converts raw race data into ML features.
Same pipeline used in training and live prediction.

V4 additions:
- AGF/Market (7 features): odds-based signals
- Pedigree Family (5): dam produce, granddam, offspring count
- Surprise (3): rolling race profile surprise metrics
- Pace (3): best_time proxy
- Value (1): model vs market placeholder
- New interactions (8): agf×form, surprise×agf, etc.
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
    """SQLite-backed rolling statistics for jockeys, trainers, sires, dams, race profiles"""

    def __init__(self, db_path=ROLLING_DB):
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self.conn = sqlite3.connect(db_path)
        self._init_tables()

    def _init_tables(self):
        c = self.conn.cursor()
        # Original tables
        for entity in ['jockey', 'trainer', 'sire', 'dam_sire', 'sire_sire', 'jt_combo']:
            c.execute(f'''CREATE TABLE IF NOT EXISTS {entity}_stats (
                name TEXT PRIMARY KEY, wins INTEGER DEFAULT 0,
                rides INTEGER DEFAULT 0, top3 INTEGER DEFAULT 0
            )''')
        # V4: Dam produce stats
        c.execute('''CREATE TABLE IF NOT EXISTS dam_stats (
            name TEXT PRIMARY KEY, wins INTEGER DEFAULT 0,
            rides INTEGER DEFAULT 0, top3 INTEGER DEFAULT 0,
            best_earnings REAL DEFAULT 0
        )''')
        # V4: Granddam (dam_dam) stats
        c.execute('''CREATE TABLE IF NOT EXISTS damdam_stats (
            name TEXT PRIMARY KEY, wins INTEGER DEFAULT 0,
            rides INTEGER DEFAULT 0
        )''')
        # V4: Race profile surprise stats
        c.execute('''CREATE TABLE IF NOT EXISTS race_profile_stats (
            profile TEXT PRIMARY KEY, total INTEGER DEFAULT 0,
            fav_wins INTEGER DEFAULT 0, upsets INTEGER DEFAULT 0,
            winner_odds_sum REAL DEFAULT 0
        )''')
        self.conn.commit()

    def get_stats(self, table, name):
        c = self.conn.cursor()
        c.execute(f'SELECT wins, rides, top3 FROM {table}_stats WHERE name=?', (name,))
        row = c.fetchone()
        return {'wins': row[0], 'rides': row[1], 'top3': row[2]} if row else {'wins': 0, 'rides': 0, 'top3': 0}

    def get_dam_stats(self, dam_name):
        c = self.conn.cursor()
        c.execute('SELECT wins, rides, top3, best_earnings FROM dam_stats WHERE name=?', (dam_name,))
        row = c.fetchone()
        return {'wins': row[0], 'rides': row[1], 'top3': row[2], 'best_earnings': row[3]} if row else {'wins': 0, 'rides': 0, 'top3': 0, 'best_earnings': 0}

    def get_damdam_stats(self, dd_name):
        c = self.conn.cursor()
        c.execute('SELECT wins, rides FROM damdam_stats WHERE name=?', (dd_name,))
        row = c.fetchone()
        return {'wins': row[0], 'rides': row[1]} if row else {'wins': 0, 'rides': 0}

    def get_surprise_stats(self, profile_key):
        c = self.conn.cursor()
        c.execute('SELECT total, fav_wins, upsets, winner_odds_sum FROM race_profile_stats WHERE profile=?', (profile_key,))
        row = c.fetchone()
        return {'total': row[0], 'fav_wins': row[1], 'upsets': row[2], 'winner_odds_sum': row[3]} if row else {'total': 0, 'fav_wins': 0, 'upsets': 0, 'winner_odds_sum': 0}

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
    Build feature vector for each horse in a race — V4.
    horses: list of horse dicts (from scraper)
    race_info: dict with distance, track_type, group_name, first_prize, etc.
    rolling_stats: RollingStats instance

    Returns: pd.DataFrame with one row per horse
    """
    rows = []
    n_runners = len(horses)

    # Pre-compute race-level AGF stats (if odds available)
    all_odds = [h.get('final_odds', 0) for h in horses]
    valid_odds = [o for o in all_odds if o > 0]
    fav_odds = min(valid_odds) if valid_odds else 0
    fav2_odds = sorted(valid_odds)[:2][-1] if len(valid_odds) >= 2 else fav_odds
    odds_mean = np.mean(valid_odds) if valid_odds else 0
    odds_std = np.std(valid_odds) if valid_odds else 0
    has_odds = len(valid_odds) >= 2

    # Odds entropy
    if valid_odds:
        probs = np.array([1.0 / o for o in valid_odds])
        probs = probs / probs.sum()
        entropy = -(probs * np.log(probs + 1e-10)).sum() / np.log(max(len(probs), 2))
    else:
        entropy = 0.5

    # Race surprise profile key
    dist = race_info.get('distance', 1400)
    is_dirt = race_info.get('track_type', 'dirt') == 'dirt'
    group = race_info.get('group_name', '')
    fsb = 's' if n_runners <= 7 else ('m' if n_runners <= 11 else 'l')
    arab = 1 if 'Arap' in group else 0
    trk = 'dirt' if is_dirt else 'grass'
    surprise_key = f"{fsb}|{arab}|{trk}"

    # Get surprise stats
    surp_stats = rolling_stats.get_surprise_stats(surprise_key) if rolling_stats else {'total': 0, 'fav_wins': 0, 'upsets': 0, 'winner_odds_sum': 0}
    if surp_stats['total'] >= 10:
        surprise_score = 1.0 - surp_stats['fav_wins'] / surp_stats['total']
        upset_rate = surp_stats['upsets'] / surp_stats['total']
        avg_winner_odds = min(surp_stats['winner_odds_sum'] / surp_stats['total'] / 20.0, 1.0)
    else:
        surprise_score = 0.5
        upset_rate = 0.3
        avg_winner_odds = 0.25

    # Pace: race average best_time
    best_times = []
    for h in horses:
        bt = _parse_best_time(h.get('best_time', ''))
        if bt is not None:
            best_times.append(bt)
    race_avg_bt = np.mean(best_times) if best_times else 90.0

    for h in horses:
        f = {}
        parsed = parse_last_6(h.get('last_6_races', h.get('form', '')))

        # ═══════════ FORM (13) ═══════════
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

        if parsed:
            f['f_surface_match'] = (dirt_count if is_dirt else grass_count) / len(parsed)
        else:
            f['f_surface_match'] = 0.5

        f['f_last20_score'] = h.get('last_20_score', 0) / 20.0

        # ═══════════ AGF / MARKET (7) ═══════════
        h_odds = h.get('final_odds', 0)
        if h_odds > 0 and has_odds:
            f['f_agf_implied_prob'] = min(1.0 / h_odds, 1.0)
            f['f_agf_log'] = np.log1p(min(h_odds, 200)) / np.log1p(200)
            f['f_agf_rank'] = sum(1 for o in valid_odds if o <= h_odds) / max(len(valid_odds), 1)
            f['f_agf_fav_margin'] = min(h_odds / (fav_odds + 0.01), 50) / 50.0
            f['f_race_odds_cv'] = (odds_std / odds_mean) if odds_mean > 0 else 0.5
            f['f_fav1v2_gap'] = min((fav2_odds - fav_odds) / (fav_odds + 0.01), 20) / 20.0
            f['f_odds_entropy'] = entropy
        else:
            # AGF yok — default (PDF'den odds gelmezse)
            f['f_agf_implied_prob'] = 1.0 / max(n_runners, 2)
            f['f_agf_log'] = 0.5
            f['f_agf_rank'] = 0.5
            f['f_agf_fav_margin'] = 0.5
            f['f_race_odds_cv'] = 0.5
            f['f_fav1v2_gap'] = 0.5
            f['f_odds_entropy'] = 0.5

        # ═══════════ PHYSICAL (9) ═══════════
        f['f_weight'] = h.get('weight', 56) / 62.0
        f['f_distance'] = dist / 2400.0
        f['f_dist_short'] = 1.0 if dist <= 1200 else 0.0
        f['f_dist_mid'] = 1.0 if 1200 < dist <= 1600 else 0.0
        f['f_dist_mile'] = 1.0 if 1600 < dist <= 2000 else 0.0
        f['f_dist_long'] = 1.0 if dist > 2000 else 0.0
        f['f_gate'] = h.get('gate_number', 5) / 14.0
        f['f_handicap'] = h.get('handicap', 60) / 75.0
        f['f_extra_weight'] = h.get('extra_weight', 0) / 5.0

        # ═══════════ HORSE PROFILE (14) ═══════════
        age_match = re.search(r'(\d+)y', h.get('age_text', '4y'))
        age = int(age_match.group(1)) if age_match else 4
        f['f_age'] = age / 11.0
        f['f_age_young'] = 1.0 if age <= 3 else 0.0
        f['f_age_prime'] = 1.0 if 4 <= age <= 6 else 0.0
        f['f_age_veteran'] = 1.0 if age >= 7 else 0.0
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
        f['f_earnings_log'] = np.log1p(earnings) / 16.0

        # ═══════════ PACE PROXY (3) ═══════════
        bt = _parse_best_time(h.get('best_time', ''))
        if bt is not None:
            f['f_pace_best_time'] = min(bt / 180.0, 1.0)
            f['f_pace_race_avg'] = min(race_avg_bt / 180.0, 1.0)
            f['f_pace_relative'] = (f['f_pace_best_time'] - f['f_pace_race_avg']) + 0.5
        else:
            f['f_pace_best_time'] = 0.5
            f['f_pace_race_avg'] = 0.5
            f['f_pace_relative'] = 0.5

        # ═══════════ JOCKEY / TRAINER / PEDIGREE ═══════════
        if rolling_stats:
            js = rolling_stats.get_stats('jockey', h.get('jockey_name', ''))
            f['f_jockey_win_rate'] = js['wins'] / js['rides'] if js['rides'] >= MIN_JOCKEY_RIDES else 0.0
            f['f_jockey_top3_rate'] = js['top3'] / js['rides'] if js['rides'] >= MIN_JOCKEY_RIDES else 0.0
            f['f_jockey_experience'] = min(js['rides'] / 200.0, 1.0)

            ts = rolling_stats.get_stats('trainer', h.get('trainer_name', ''))
            f['f_trainer_win_rate'] = ts['wins'] / ts['rides'] if ts['rides'] >= MIN_TRAINER_RIDES else 0.0
            f['f_trainer_experience'] = min(ts['rides'] / 100.0, 1.0)

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

            # ═══════════ PEDIGREE FAMILY (5) ═══════════
            dam_name = h.get('dam_name', h.get('dam', ''))
            if dam_name:
                ds = rolling_stats.get_dam_stats(dam_name)
                f['f_dam_produce_wr'] = ds['wins'] / ds['rides'] if ds['rides'] >= 5 else 0.0
                f['f_dam_produce_top3'] = ds['top3'] / ds['rides'] if ds['rides'] >= 5 else 0.0
                f['f_dam_n_offspring'] = min(ds['rides'] / 30.0, 1.0)
                f['f_dam_best_earner'] = min(ds['best_earnings'] / 500000.0, 1.0)
            else:
                f['f_dam_produce_wr'] = 0.0
                f['f_dam_produce_top3'] = 0.0
                f['f_dam_n_offspring'] = 0.0
                f['f_dam_best_earner'] = 0.0

            dam_dam = h.get('dam_dam', '')
            if dam_dam:
                dds = rolling_stats.get_damdam_stats(dam_dam)
                f['f_damdam_family_wr'] = dds['wins'] / dds['rides'] if dds['rides'] >= 10 else 0.0
            else:
                f['f_damdam_family_wr'] = 0.0
        else:
            for feat in ['f_jockey_win_rate', 'f_jockey_top3_rate', 'f_jockey_experience',
                         'f_trainer_win_rate', 'f_trainer_experience', 'f_jt_combo_wr',
                         'f_sire_win_rate', 'f_dam_sire_win_rate', 'f_sire_sire_win_rate',
                         'f_dam_produce_wr', 'f_dam_produce_top3', 'f_dam_n_offspring',
                         'f_dam_best_earner', 'f_damdam_family_wr']:
                f[feat] = 0.0

        # ═══════════ SURPRISE (3) ═══════════
        f['f_surprise_v2'] = surprise_score
        f['f_upset_rate'] = upset_rate
        f['f_avg_winner_odds'] = avg_winner_odds

        # ═══════════ CONDITIONS (9) ═══════════
        f['f_is_dirt'] = 1.0 if is_dirt else 0.0
        f['f_is_synthetic'] = 0.0 if is_dirt else 1.0
        f['f_hippodrome'] = 0.5
        f['f_temperature'] = 0.5
        f['f_humidity'] = 0.5
        f['f_race_class'] = np.log1p(race_info.get('first_prize', 400000)) / 16.5
        f['f_field_size'] = n_runners / 16.0
        f['f_is_weekend'] = 0.0  # Set by caller
        f['f_day_of_week'] = 0.0  # Set by caller

        # ═══════════ EQUIPMENT (5) ═══════════
        equip = h.get('equipment', '')
        f['f_equip_kg'] = 1.0 if 'KG' in equip else 0.0
        f['f_equip_db'] = 1.0 if 'DB' in equip else 0.0
        f['f_equip_sk'] = 1.0 if re.search(r'\bSK\b', equip) else 0.0
        f['f_equip_skg'] = 1.0 if 'SKG' in equip else 0.0
        f['f_equip_count'] = len(equip.split()) / 4.0 if equip else 0.0

        # ═══════════ INTERACTIONS (20) ═══════════
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
        f['f_X_dam_class'] = f['f_dam_produce_wr'] * f['f_race_class']
        f['f_X_sibling_form'] = 0.0  # sibling_top3 not tracked live yet
        f['f_X_dam_jockey'] = f['f_dam_produce_wr'] * f['f_jockey_win_rate']
        f['f_X_agf_form'] = f['f_agf_implied_prob'] * f['f_form_top3']
        f['f_X_agf_jockey'] = f['f_agf_implied_prob'] * f['f_jockey_win_rate']
        f['f_X_surprise_agf'] = f['f_surprise_v2'] * f['f_agf_implied_prob']
        f['f_X_surprise_field'] = f['f_surprise_v2'] * f['f_field_size']
        f['f_X_pace_form'] = f['f_pace_relative'] * f['f_form_last1']

        # ═══════════ VALUE (1) ═══════════
        f['f_model_vs_market'] = 0.0  # Updated after model prediction

        # ═══════════ META (not features) ═══════════
        f['_horse_name'] = h.get('horse_name', '')
        f['_horse_number'] = h.get('horse_number', 0)
        f['_jockey_name'] = h.get('jockey_name', '')
        f['_trainer_name'] = h.get('trainer_name', '')
        f['_sire'] = h.get('sire', '')
        f['_odds'] = h.get('final_odds', 0)

        rows.append(f)

    return pd.DataFrame(rows)


def _parse_best_time(val):
    """Parse best_time string to seconds. e.g. '1.41.79' -> 101.79"""
    try:
        if not val or pd.isna(val):
            return None
        val = str(val).strip()
        parts = val.split('.')
        if len(parts) == 2:
            return float(parts[0]) * 60 + float(parts[1])
        elif len(parts) == 3:
            return float(parts[0]) * 60 + float(parts[1]) + float(parts[2]) / 100
        return None
    except:
        return None


# Feature column order (must match V4 training)
FEATURE_COLUMNS = [
    # Form (13)
    'f_form_avg_pos', 'f_form_wins', 'f_form_top3', 'f_form_trend',
    'f_form_race_count', 'f_form_best', 'f_form_worst', 'f_form_consistency',
    'f_form_dirt_pct', 'f_form_grass_pct', 'f_surface_match', 'f_last20_score',
    'f_form_last1',
    # Market (7)
    'f_agf_implied_prob', 'f_agf_rank', 'f_agf_log', 'f_agf_fav_margin',
    'f_race_odds_cv', 'f_fav1v2_gap', 'f_odds_entropy',
    # Physical (9)
    'f_weight', 'f_distance', 'f_dist_short', 'f_dist_mid', 'f_dist_mile',
    'f_dist_long', 'f_gate', 'f_handicap', 'f_extra_weight',
    # Horse Profile (14)
    'f_age', 'f_age_young', 'f_age_prime', 'f_age_veteran',
    'f_is_arab', 'f_is_english',
    'f_gender_stallion', 'f_gender_mare', 'f_gender_gelding',
    'f_days_rest', 'f_fresh', 'f_rested', 'f_earnings', 'f_earnings_log',
    # Pace (3)
    'f_pace_best_time', 'f_pace_race_avg', 'f_pace_relative',
    # Jockey/Trainer/Pedigree (9)
    'f_jockey_win_rate', 'f_jockey_top3_rate', 'f_jockey_experience',
    'f_trainer_win_rate', 'f_trainer_experience', 'f_jt_combo_wr',
    'f_sire_win_rate', 'f_dam_sire_win_rate', 'f_sire_sire_win_rate',
    # Pedigree Family (5)
    'f_dam_produce_wr', 'f_dam_produce_top3', 'f_dam_n_offspring',
    'f_dam_best_earner', 'f_damdam_family_wr',
    # Surprise (3)
    'f_surprise_v2', 'f_upset_rate', 'f_avg_winner_odds',
    # Conditions (9)
    'f_is_dirt', 'f_is_synthetic', 'f_hippodrome', 'f_temperature', 'f_humidity',
    'f_race_class', 'f_field_size', 'f_is_weekend', 'f_day_of_week',
    # Equipment (5)
    'f_equip_kg', 'f_equip_db', 'f_equip_sk', 'f_equip_skg', 'f_equip_count',
    # Interactions (20)
    'f_X_jockey_form', 'f_X_jockey_trainer', 'f_X_sire_dist', 'f_X_age_trend',
    'f_X_surface_form', 'f_X_form_class', 'f_X_jockey_class',
    'f_X_earnings_form', 'f_X_trainer_form', 'f_X_jt_combo_form',
    'f_X_form_field', 'f_X_earnings_class',
    'f_X_dam_class', 'f_X_sibling_form', 'f_X_dam_jockey',
    'f_X_agf_form', 'f_X_agf_jockey', 'f_X_surprise_agf',
    'f_X_surprise_field', 'f_X_pace_form',
    # Value (1)
    'f_model_vs_market',
]
