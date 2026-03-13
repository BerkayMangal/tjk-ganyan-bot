"""
Feature Builder V5 — Taydex verisiyle uyumlu
===============================================
Colab pipeline ile birebir ayni feature'lari uretir.
rstats_v2.json kullanir.
"""
import numpy as np
import json
import os
import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STATS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'trained', 'rstats_v2.json'
)
FEATURE_COLS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'trained', 'feature_columns.json'
)


class FeatureBuilder:
    """Builds features matching V5 Colab pipeline exactly."""

    def __init__(self, stats_path=None):
        self.stats_path = stats_path or STATS_PATH
        self.stats = None
        self.feature_cols = None

    def load(self):
        # Rolling stats
        path = self.stats_path
        # Fallback: eski isim
        if not os.path.exists(path):
            old_path = path.replace('rstats_v2.json', 'rstats.json')
            if os.path.exists(old_path):
                path = old_path
        if os.path.exists(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
                logger.info(f"Rolling stats loaded: {list(self.stats.keys())}")
            except Exception as e:
                logger.warning(f"Rolling stats error: {e}")
                self.stats = {}
        else:
            logger.warning(f"Rolling stats not found: {path}")
            self.stats = {}

        # Feature columns
        fc_path = os.path.join(os.path.dirname(path), 'feature_columns.json')
        if os.path.exists(fc_path):
            with open(fc_path) as f:
                self.feature_cols = json.load(f)
            logger.info(f"Feature columns: {len(self.feature_cols)}")
        else:
            logger.warning("feature_columns.json not found!")
            return False

        return True

    def build_race_features(self, horses, race_info, agf_data=None):
        """Build feature matrix for one race.
        
        Args:
            horses: list of horse dicts from scraper
            race_info: dict with distance, track_type, group_name, etc.
            agf_data: list of AGF dicts [{horse_number, agf_pct}, ...]
        
        Returns:
            (numpy matrix, list of horse names)
        """
        if not self.feature_cols:
            raise RuntimeError("Feature columns not loaded!")

        g = self.stats.get('global', {
            'distance_min': 800, 'distance_max': 2400,
            'prize_max': 1000000, 'earnings_max': 5000000
        })
        n_horses = len(horses)

        # AGF lookup
        agf_by_num = {}
        if agf_data:
            for h in agf_data:
                agf_by_num[h['horse_number']] = h

        # All odds
        all_odds = []
        for h in horses:
            num = h.get('horse_number', 0)
            agf = agf_by_num.get(num, {})
            pct = agf.get('agf_pct', 0)
            odds = 100.0 / pct if pct > 0 else 20.0
            all_odds.append(odds)

        # Race-level
        odds_arr = np.array(all_odds)
        odds_std = np.std(odds_arr) if len(odds_arr) > 1 else 0
        odds_mean = np.mean(odds_arr) if len(odds_arr) > 0 else 10.0
        odds_cv = odds_std / (odds_mean + 0.01)

        agf_pcts = np.array([agf_by_num.get(h.get('horse_number',0), {}).get('agf_pct', 0) for h in horses])
        sorted_agf = np.sort(agf_pcts)[::-1]
        fav_gap = (sorted_agf[0] - sorted_agf[1]) / 100.0 if len(sorted_agf) >= 2 else 0

        # Entropy
        probs = agf_pcts[agf_pcts > 0] / 100.0
        if len(probs) > 0:
            probs_n = probs / probs.sum()
            entropy = float(-np.sum(probs_n * np.log(probs_n + 1e-10)))
        else:
            entropy = 0.5

        # HP stats
        hps = np.array([float(h.get('handicap', 0) or 0) for h in horses])
        hp_std = np.std(hps) if len(hps) > 1 else 0
        hp_mean = np.mean(hps) if len(hps) > 0 else 60
        field_strength = hp_std / (hp_mean + 1)
        hp_range = (hps.max() - hps.min()) / 100.0 if len(hps) > 0 else 0.5

        # Race info
        distance = float(race_info.get('distance', 1400) or 1400)
        track_type = str(race_info.get('track_type', 'dirt') or 'dirt').lower()
        track_map = {'kum': 'dirt', 'cim': 'turf', 'sentetik': 'synthetic',
                     'dirt': 'dirt', 'turf': 'turf', 'synthetic': 'synthetic'}
        track_type = track_map.get(track_type, 'dirt')
        first_prize = float(race_info.get('first_prize', 100000) or 100000)
        temperature = race_info.get('temperature', None)
        humidity = race_info.get('humidity', None)
        hippo = race_info.get('hippodrome_name', '')
        group_name = race_info.get('group_name', '')

        # Build per-horse features
        rows = []
        horse_names = []

        for h in horses:
            f = {}
            num = h.get('horse_number', 0)
            agf = agf_by_num.get(num, {})
            agf_pct = agf.get('agf_pct', 0)
            odds = 100.0 / agf_pct if agf_pct > 0 else 20.0

            # AGF
            f['f_agf_prob'] = agf_pct / 100.0
            f['f_agf_log'] = np.log1p(odds) / np.log1p(50)  # normalize
            agf_rank = 0
            if agf_pcts.max() > 0:
                rank_pos = np.sum(agf_pcts > agf_pct) + 1
                agf_rank = rank_pos / n_horses
            f['f_agf_rank'] = agf_rank

            # Race level
            f['f_fav_gap'] = fav_gap
            f['f_field_size'] = min(n_horses, 18) / 18.0
            f['f_distance'] = self._norm(distance, g.get('distance_min', 800), g.get('distance_max', 2400))
            f['f_is_dirt'] = 1.0 if track_type == 'dirt' else 0.0
            f['f_is_synthetic'] = 1.0 if track_type == 'synthetic' else 0.0
            f['f_race_class'] = np.log1p(first_prize) / np.log1p(g.get('prize_max', 1000000))
            f['f_temperature'] = self._norm(temperature, -5, 45) if temperature else 0.5
            f['f_humidity'] = self._norm(humidity, 10, 100) if humidity else 0.5
            f['f_field_strength'] = field_strength
            f['f_hp_range'] = hp_range
            f['f_upset_rate'] = self.stats.get('upset_rate', {}).get(hippo, 0.35)

            # Horse
            weight = float(h.get('weight', 57) or 57)
            f['f_weight'] = self._norm(weight, 50, 62)
            f['f_extra_weight'] = float(h.get('extra_weight', 0) or 0) / 5.0
            f['f_gate'] = float(h.get('gate_number', num) or num) / 18.0
            hp = float(h.get('handicap', 0) or 0)
            f['f_handicap'] = self._norm(hp, 40, 100) if hp > 0 else 0.5
            age_text = str(h.get('age_text', '4') or '4')
            am = re.search(r'(\d)', age_text)
            age = int(am.group(1)) if am else 4
            f['f_age'] = age / 10.0
            f['f_gender_mare'] = 1.0 if 'k' in age_text.lower() else 0.0
            f['f_breed_arab'] = 1.0 if 'arap' in str(group_name).lower() else 0.0
            f['f_earnings'] = np.log1p(float(h.get('total_earnings', 0) or 0)) / np.log1p(g.get('earnings_max', 5000000))
            kgs = float(h.get('kgs', 0) or 0)
            f['f_days_rest'] = self._norm(kgs, 0, 200) if kgs > 0 else 0.5
            f['f_last20_score'] = float(h.get('last_20_score', 0) or 0) / 20.0

            # Form — K/C parse
            form_str = str(h.get('form', '') or '')
            ku, ci, sm, fl, fb, fc, ft = self._parse_form(form_str, track_type)
            f['f_kumcu'] = ku
            f['f_cimci'] = ci
            f['f_surface_match'] = sm
            f['f_form_last1'] = fl
            f['f_form_best'] = fb
            f['f_form_consistency'] = fc
            f['f_form_trend'] = ft

            # Jokey/Trainer from stats
            jockey = h.get('jockey_name', '') or h.get('jockey', '') or ''
            trainer = h.get('trainer_name', '') or h.get('trainer', '') or ''
            sire = h.get('sire', '') or h.get('sire_name', '') or ''
            dam = h.get('dam', '') or h.get('dam_name', '') or ''
            dam_sire = h.get('dam_sire', '') or h.get('dam_sire_name', '') or ''
            dam_dam = h.get('dam_dam', '') or ''
            sire_sire = h.get('sire_sire', '') or ''

            j_stats = self.stats.get('jockey', {}).get(jockey, {})
            f['f_jockey_wr'] = j_stats.get('win_rate', 0)
            f['f_jockey_t3r'] = j_stats.get('top3_rate', 0)
            f['f_jockey_exp'] = j_stats.get('experience', 0)
            f['f_trainer_wr'] = self.stats.get('trainer', {}).get(trainer, {}).get('win_rate', 0)
            f['f_sire_wr'] = self.stats.get('sire', {}).get(sire, {}).get('win_rate', 0)
            f['f_dam_sire_wr'] = self.stats.get('dam_sire', {}).get(dam_sire, {}).get('win_rate', 0)
            f['f_dam_wr'] = self.stats.get('dam', {}).get(dam, {}).get('win_rate', 0)
            f['f_dam_t3r'] = self.stats.get('dam', {}).get(dam, {}).get('top3_rate', 0)
            f['f_damdam_wr'] = self.stats.get('damdam', {}).get(dam_dam, {}).get('win_rate', 0)

            jt_key = f"{jockey}||{trainer}"
            f['f_jt_wr'] = self.stats.get('jockey_trainer', {}).get(jt_key, {}).get('win_rate', 0)

            # Interactions
            f['f_X_jockey_agf'] = f['f_jockey_wr'] * f['f_agf_prob']
            f['f_X_sire_dist'] = f['f_sire_wr'] * f['f_distance']
            f['f_X_form_agf'] = f['f_form_best'] * f['f_agf_prob']
            f['f_X_weight_dist'] = f['f_weight'] * f['f_distance']
            f['f_X_kumcu_dirt'] = f['f_kumcu'] * f['f_is_dirt']
            f['f_X_jt_form'] = f['f_jt_wr'] * f['f_form_best']
            f['f_X_dam_form'] = f['f_dam_wr'] * f['f_form_best']
            f['f_X_earnings_class'] = f['f_earnings'] * f['f_race_class']
            f['f_X_upset_field'] = f['f_upset_rate'] * f['f_field_size']

            rows.append(f)
            name = h.get('horse_name', f'At_{num}')
            horse_names.append(name)

        # Build matrix in correct column order
        matrix = np.zeros((n_horses, len(self.feature_cols)))
        for i, row in enumerate(rows):
            for j, col in enumerate(self.feature_cols):
                matrix[i, j] = row.get(col, 0.0)

        matrix = np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)
        return matrix, horse_names

    def _parse_form(self, form_str, track_type='dirt'):
        """Parse form string — K/C harflerini koru!"""
        if not form_str or not isinstance(form_str, str):
            return 0.5, 0.5, 0.5, 0, 0, 0, 0.5
        matches = re.findall(r'([KC])(\d+)', form_str)
        if not matches:
            return 0.5, 0.5, 0.5, 0, 0, 0, 0.5
        kum_pos = [int(p) for s, p in matches if s == 'K']
        cim_pos = [int(p) for s, p in matches if s == 'C']
        all_pos = [int(p) for _, p in matches]
        kumcu = sum(1 for p in kum_pos if p <= 3) / max(len(kum_pos), 1) if kum_pos else 0.5
        cimci = sum(1 for p in cim_pos if p <= 3) / max(len(cim_pos), 1) if cim_pos else 0.5
        if track_type in ('dirt', 'kum'):
            sm = kumcu
        elif track_type in ('turf', 'cim', 'grass'):
            sm = cimci
        else:
            sm = 0.5
        fl = 1.0 / (all_pos[-1] + 1) if all_pos else 0
        fb = 1.0 / (min(all_pos) + 1) if all_pos else 0
        fc = 1.0 / (np.std(all_pos) + 1) if len(all_pos) >= 2 else 0
        ft = 0.5
        if len(all_pos) >= 4:
            half = len(all_pos) // 2
            ft = (np.mean(all_pos[:half]) - np.mean(all_pos[half:])) / (np.mean(all_pos[:half]) + 1)
        return kumcu, cimci, sm, fl, fb, fc, ft

    @staticmethod
    def _norm(val, mn, mx):
        if val is None:
            return 0.5
        try:
            val = float(val)
        except (ValueError, TypeError):
            return 0.5
        if mx == mn:
            return 0.5
        return max(0.0, min(1.0, (val - mn) / (mx - mn)))
