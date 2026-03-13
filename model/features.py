"""
Feature Builder V5 — 96 Feature, Taydex/Colab Pipeline Uyumlu
================================================================
Colab'daki breed-split model (v5_leakage_free) ile birebir ayni
96 feature'i uretir. rstats_v2.json kullanir.
"""
import numpy as np
import json
import os
import re
import logging
from datetime import datetime

logger = logging.getLogger(__name__)

STATS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'trained', 'rstats_v2.json'
)
FEATURE_COLS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'trained', 'feature_columns.json'
)

HIPPO_INDEX = {
    'adana': 0.1, 'ankara': 0.2, 'antalya': 0.3, 'bursa': 0.4,
    'diyarbakir': 0.5, 'diyarbak': 0.5, 'elazig': 0.6, 'elazig': 0.6,
    'istanbul': 0.7, 'izmir': 0.8, 'kocaeli': 0.9, 'sanliurfa': 1.0,
}


def _normalize_name(name):
    n = str(name).strip().upper()
    for old, new in [('İ','I'),('Ş','S'),('Ğ','G'),('Ü','U'),('Ö','O'),('Ç','C'),
                     ('ı','I'),('ş','S'),('ğ','G'),('ü','U'),('ö','O'),('ç','C')]:
        n = n.replace(old, new)
    return n


class FeatureBuilder:
    """Builds 96 features matching V5 Colab pipeline exactly."""

    def __init__(self, stats_path=None):
        self.stats_path = stats_path or STATS_PATH
        self.stats = None
        self.feature_cols = None

    def load(self):
        path = self.stats_path
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

        fc_path = os.path.join(os.path.dirname(path), 'feature_columns.json')
        if os.path.exists(fc_path):
            with open(fc_path) as f:
                self.feature_cols = json.load(f)
            logger.info(f"Feature columns: {len(self.feature_cols)}")
        else:
            logger.warning("feature_columns.json not found!")
            return False
        # Pedigree lookup (sire_sire, dam_dam, earnings)
        lookup_path = os.path.join(os.path.dirname(path), 'pedigree_lookup.json')
        if os.path.exists(lookup_path):
            try:
                with open(lookup_path, 'r', encoding='utf-8') as lf:
                    self.lookup = json.load(lf)
                logger.info(f"Pedigree lookup loaded: "
                           f"sire_sire={len(self.lookup.get('sire_to_sire_sire',{}))} "
                           f"dam_dam={len(self.lookup.get('dam_to_dam_dam',{}))} "
                           f"earnings={len(self.lookup.get('horse_earnings',{}))}")
            except Exception as e:
                logger.warning(f"Pedigree lookup error: {e}")
                self.lookup = {}
        else:
            self.lookup = {}

        return True

    def build_race_features(self, horses, race_info, agf_data=None):
        if not self.feature_cols:
            raise RuntimeError("Feature columns not loaded!")

        g = self.stats.get('global', {
            'distance_min': 800, 'distance_max': 2800,
            'prize_max': 30000000, 'earnings_max': 42593220
        })
        n_horses = len(horses)

        # AGF lookup
        agf_by_num = {}
        if agf_data:
            for h in agf_data:
                agf_by_num[h['horse_number']] = h

        all_odds, agf_pcts = [], []
        for h in horses:
            num = h.get('horse_number', 0)
            pct = agf_by_num.get(num, {}).get('agf_pct', 0)
            all_odds.append(100.0 / pct if pct > 0 else 20.0)
            agf_pcts.append(pct)

        odds_arr = np.array(all_odds)
        agf_pct_arr = np.array(agf_pcts)
        sorted_agf = np.sort(agf_pct_arr)[::-1]

        # Race-level
        odds_std = np.std(odds_arr) if len(odds_arr) > 1 else 0
        odds_mean = np.mean(odds_arr) if len(odds_arr) > 0 else 10.0
        odds_cv = odds_std / (odds_mean + 0.01)
        fav1v2_gap = (sorted_agf[0] - sorted_agf[1]) / 100.0 if len(sorted_agf) >= 2 else 0

        probs = agf_pct_arr[agf_pct_arr > 0] / 100.0
        if len(probs) > 0:
            pn = probs / probs.sum()
            entropy = float(-np.sum(pn * np.log(pn + 1e-10)))
        else:
            entropy = 0.5

        hps = np.array([float(h.get('handicap', 0) or 0) for h in horses])
        hp_std = np.std(hps) if len(hps) > 1 else 0
        hp_mean = np.mean(hps) if len(hps) > 0 else 60
        field_strength = hp_std / (hp_mean + 1)
        hp_range = (hps.max() - hps.min()) / 100.0 if len(hps) > 0 else 0.5

        distance = float(race_info.get('distance', 1400) or 1400)
        track_type = str(race_info.get('track_type', 'dirt') or 'dirt').lower()
        track_map = {'kum': 'dirt', 'cim': 'turf', 'sentetik': 'synthetic',
                     'dirt': 'dirt', 'turf': 'turf', 'synthetic': 'synthetic'}
        track_type = track_map.get(track_type, 'dirt')
        first_prize = float(race_info.get('first_prize', 100000) or 100000)
        temperature = race_info.get('temperature', None)
        humidity = race_info.get('humidity', None)
        hippo = race_info.get('hippodrome_name', '')
        group_name = str(race_info.get('group_name', '') or '')
        race_date_str = str(race_info.get('race_date', ''))

        try:
            rd = datetime.strptime(race_date_str[:10], '%Y-%m-%d')
            day_of_week = rd.weekday() / 6.0
            is_weekend = 1.0 if rd.weekday() >= 5 else 0.0
        except Exception:
            day_of_week = 0.5
            is_weekend = 0.0

        gn = group_name.lower()
        is_maiden = 1.0 if ('maiden' in gn or 'bakire' in gn) else 0.0
        is_female_race = 1.0 if any(w in gn for w in ('disi', 'kiz', 'kisrak')) else 0.0
        is_arab = 'arap' in gn

        dist_mile = 1.0 if 1500 <= distance <= 1700 else 0.0
        dist_mid = 1.0 if 1800 <= distance <= 2200 else 0.0

        hippo_enc = 0.5
        hl = hippo.lower()
        for key, val in HIPPO_INDEX.items():
            if key in hl:
                hippo_enc = val
                break

        avg_winner_odds = 0.5
        if hasattr(self, 'lookup') and self.lookup.get('upset_rates_v2'):
            avg_winner_odds = self.lookup['upset_rates_v2'].get(hippo, 0.5)
        if avg_winner_odds == 0.5:
            avg_winner_odds = self.stats.get('upset_rate', {}).get(hippo, 0.5)
        f_dist = self._norm(distance, g.get('distance_min', 800), g.get('distance_max', 2800))
        f_is_dirt = 1.0 if track_type == 'dirt' else 0.0
        f_is_synthetic = 1.0 if track_type == 'synthetic' else 0.0
        f_race_class = np.log1p(first_prize) / np.log1p(g.get('prize_max', 30000000))
        f_temp = self._norm(temperature, -5, 45) if temperature else 0.5
        f_humid = self._norm(humidity, 10, 100) if humidity else 0.5
        f_field_size = min(n_horses, 18) / 18.0
        surprise_v2 = self.stats.get('upset_rate', {}).get(hippo, 0.35)

        rows = []
        horse_names = []

        for h in horses:
            f = {}
            num = h.get('horse_number', 0)
            agf_pct = agf_by_num.get(num, {}).get('agf_pct', 0)
            odds = 100.0 / agf_pct if agf_pct > 0 else 20.0

            # AGF
            f['f_agf_implied_prob'] = agf_pct / 100.0
            f['f_agf_log'] = np.log1p(odds) / np.log1p(50)
            rank_pos = np.sum(agf_pct_arr > agf_pct) + 1
            f['f_agf_rank'] = rank_pos / n_horses if agf_pct_arr.max() > 0 else 0
            f['f_agf_fav_margin'] = (agf_pct - sorted_agf[1]) / 100.0 if len(sorted_agf) >= 2 else 0
            f['f_race_odds_cv'] = odds_cv
            f['f_odds_entropy'] = entropy
            f['f_avg_winner_odds'] = avg_winner_odds
            f['f_fav1v2_gap'] = fav1v2_gap

            # Race-level
            f['f_field_size'] = f_field_size
            f['f_distance'] = f_dist
            f['f_is_dirt'] = f_is_dirt
            f['f_is_synthetic'] = f_is_synthetic
            f['f_race_class'] = f_race_class
            f['f_temperature'] = f_temp
            f['f_humidity'] = f_humid
            f['f_field_strength'] = field_strength
            f['f_hp_range'] = hp_range
            f['f_hippodrome'] = hippo_enc
            f['f_day_of_week'] = day_of_week
            f['f_is_weekend'] = is_weekend
            f['f_dist_mile'] = dist_mile
            f['f_dist_mid'] = dist_mid
            f['f_is_maiden'] = is_maiden
            f['f_is_female_race'] = is_female_race
            f['f_breed_arab'] = 1.0 if is_arab else 0.0
            f['f_surprise_v2'] = surprise_v2
            f['f_upset_rate'] = surprise_v2

            # Horse basic
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

            at_l = age_text.lower()
            gender = str(h.get('gender', '') or '').lower()
            f['f_gender_mare'] = 1.0 if ('k' in at_l or gender == 'female') else 0.0
            f['f_gender_gelding'] = 1.0 if ('i' in at_l or 'gelding' in gender) else 0.0
            f['f_gender_stallion'] = 1.0 if (f['f_gender_mare'] == 0 and f['f_gender_gelding'] == 0) else 0.0

            total_earnings = float(h.get('total_earnings', 0) or 0)
            if total_earnings == 0 and hasattr(self, 'lookup'):
                horse_name = h.get('horse_name', '')
                total_earnings = float(self.lookup.get('horse_earnings', {}).get(horse_name, 0))
                if total_earnings == 0:
                    total_earnings = float(self.lookup.get('horse_earnings_normalized', {}).get(_normalize_name(horse_name), 0))
            f['f_earnings'] = np.log1p(total_earnings) / np.log1p(g.get('earnings_max', 42593220))

            kgs = float(h.get('kgs', 0) or 0)
            f['f_days_rest'] = self._norm(kgs, 0, 200) if kgs > 0 else 0.5
            f['f_rested'] = 1.0 if kgs > 60 else 0.0
            f['f_last20_score'] = float(h.get('last_20_score', 0) or 0) / 20.0

            equip = str(h.get('equipment', '') or '').upper()
            f['f_equip_skg'] = 1.0 if 'SKG' in equip else 0.0
            f['f_equip_sk'] = 1.0 if ('SK' in equip and 'SKG' not in equip) else 0.0
            f['f_equip_db'] = 1.0 if 'DB' in equip else 0.0
            f['f_equip_kg'] = 1.0 if ('KG' in equip and 'SKG' not in equip) else 0.0
            f['f_equip_count'] = sum([f['f_equip_skg'], f['f_equip_sk'], f['f_equip_db'], f['f_equip_kg']])
            f['f_light_weight_long'] = 1.0 if (weight <= 54 and distance >= 2000) else 0.0

            # Form
            form_str = str(h.get('form', '') or '')
            ku, ci, sm, fl, fb, fc, ft, fdp = self._parse_form_full(form_str, track_type)
            f['f_kumcu'] = ku
            f['f_cimci'] = ci
            f['f_surface_match'] = sm
            f['f_form_last1'] = fl
            f['f_form_best'] = fb
            f['f_form_consistency'] = fc
            f['f_form_trend'] = ft
            f['f_form_dirt_pct'] = fdp

            # Jockey / Trainer
            jockey = h.get('jockey_name', '') or h.get('jockey', '') or ''
            trainer = h.get('trainer_name', '') or h.get('trainer', '') or ''
            j_st = self.stats.get('jockey', {}).get(jockey, {})
            f['f_jockey_win_rate'] = j_st.get('win_rate', 0)
            f['f_jockey_top3_rate'] = j_st.get('top3_rate', 0)
            f['f_jockey_experience'] = j_st.get('experience', 0)
            t_st = self.stats.get('trainer', {}).get(trainer, {})
            f['f_trainer_win_rate'] = t_st.get('win_rate', 0)
            f['f_trainer_experience'] = t_st.get('experience', 0)

            # Pedigree
            sire = h.get('sire', '') or ''
            dam = h.get('dam', '') or ''
            dam_sire = h.get('dam_sire', '') or ''
            dam_dam = h.get('dam_dam', '') or ''
            sire_sire = h.get('sire_sire', '') or ''
            if not sire_sire and sire and hasattr(self, 'lookup'):
                sire_sire = self.lookup.get('sire_to_sire_sire', {}).get(sire, '')
                if not sire_sire:
                    sire_sire = self.lookup.get('sire_to_sire_sire_normalized', {}).get(_normalize_name(sire), '')

            f['f_sire_win_rate'] = self.stats.get('sire', {}).get(sire, {}).get('win_rate', 0)
            f['f_dam_sire_win_rate'] = self.stats.get('dam_sire', {}).get(dam_sire, {}).get('win_rate', 0)
            f['f_sire_sire_win_rate'] = self.stats.get('sire_sire', {}).get(sire_sire, {}).get('win_rate', 0)
            d_st = self.stats.get('dam', {}).get(dam, {})
            f['f_dam_produce_wr'] = d_st.get('win_rate', 0)
            f['f_dam_produce_top3'] = d_st.get('top3_rate', 0)
            f['f_dam_n_offspring'] = d_st.get('n_offspring', 0) / 100.0
            f['f_dam_best_earner'] = np.log1p(d_st.get('best_earner', 0)) / np.log1p(g.get('earnings_max', 42593220))
            f['f_damdam_family_wr'] = self.stats.get('damdam', {}).get(dam_dam, {}).get('win_rate', 0)

            # Pace — lookup'tan breed x distance ortalamasi
            f['f_pace_best_time'] = 0.5
            f['f_pace_relative'] = 0.0
            f['f_pace_race_avg'] = 0.0
            if hasattr(self, 'lookup') and self.lookup.get('pace_averages'):
                _breed_key = 'arab' if is_arab else 'english'
                _dist_bucket = int((distance // 200) * 200)
                _pace_key = f"{_breed_key}_{_dist_bucket}"
                _pace = self.lookup['pace_averages'].get(_pace_key, {})
                if _pace:
                    f['f_pace_race_avg'] = self._norm(_pace.get('mean', 0), 60, 200)
                    f['f_pace_best_time'] = self._norm(_pace.get('median', 0), 60, 200)
            f['f_model_vs_market'] = 0.0

            # Interactions
            jt_key = f"{jockey}||{trainer}"
            jt_wr = self.stats.get('jockey_trainer', {}).get(jt_key, {}).get('win_rate', 0)

            f['f_X_agf_form'] = f['f_agf_implied_prob'] * f['f_form_best']
            f['f_X_agf_jockey'] = f['f_agf_implied_prob'] * f['f_jockey_win_rate']
            f['f_X_surprise_agf'] = f['f_surprise_v2'] * f['f_agf_implied_prob']
            f['f_X_jockey_form'] = f['f_jockey_win_rate'] * f['f_form_last1']
            f['f_X_jockey_trainer'] = f['f_jockey_win_rate'] * f['f_trainer_win_rate']
            f['f_X_jockey_class'] = f['f_jockey_win_rate'] * f['f_race_class']
            f['f_X_jt_combo_form'] = jt_wr * f['f_form_best']
            f['f_X_trainer_form'] = f['f_trainer_win_rate'] * f['f_form_last1']
            f['f_X_sire_dist'] = f['f_sire_win_rate'] * f['f_distance']
            f['f_X_dam_jockey'] = f['f_dam_produce_wr'] * f['f_jockey_win_rate']
            f['f_X_dam_class'] = f['f_dam_produce_wr'] * f['f_race_class']
            f['f_X_sibling_form'] = f['f_dam_produce_top3'] * f['f_form_best']
            f['f_X_earnings_class'] = f['f_earnings'] * f['f_race_class']
            f['f_X_earnings_form'] = f['f_earnings'] * f['f_form_last1']
            f['f_X_form_field'] = f['f_form_last1'] * f['f_field_size']
            f['f_X_form_class'] = f['f_form_last1'] * f['f_race_class']
            f['f_X_surface_form'] = f['f_surface_match'] * f['f_form_last1']
            f['f_X_surprise_field'] = f['f_surprise_v2'] * f['f_field_size']
            f['f_X_pace_form'] = f['f_pace_relative'] * f['f_form_last1']
            f['f_X_age_trend'] = f['f_age'] * f['f_form_trend']
            f['f_X_kumcu_dirt'] = f['f_kumcu'] * f['f_is_dirt']
            f['f_X_cimci_turf'] = f['f_cimci'] * (1.0 - f['f_is_dirt'])
            f['f_X_weight_distance'] = f['f_weight'] * f['f_distance']
            f['f_X_weight_dist'] = f['f_X_weight_distance']
            f['f_X_field_strength_agf'] = f['f_field_strength'] * f['f_agf_implied_prob']
            f['f_X_maiden_field'] = f['f_is_maiden'] * f['f_field_size']

            rows.append(f)
            horse_names.append(h.get('horse_name', f'At_{num}'))

        # Build matrix
        matrix = np.zeros((n_horses, len(self.feature_cols)))
        for i, row in enumerate(rows):
            for j, col in enumerate(self.feature_cols):
                matrix[i, j] = row.get(col, 0.0)

        matrix = np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)
        return matrix, horse_names

    def _parse_form_full(self, form_str, track_type='dirt'):
        if not form_str or not isinstance(form_str, str):
            return 0.5, 0.5, 0.5, 0, 0, 0, 0.5, 0.5
        matches = re.findall(r'([KC])(\d+)', form_str)
        if not matches:
            return 0.5, 0.5, 0.5, 0, 0, 0, 0.5, 0.5

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

        n_total = len(matches)
        fdp = len(kum_pos) / n_total if n_total > 0 else 0.5
        return kumcu, cimci, sm, fl, fb, fc, ft, fdp

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
