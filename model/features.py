"""
Feature Builder — Canlı yarış verisi → 82 feature
====================================================
AGF scraper + PDF parser + rolling_stats.json → model input

Her at için V3 backtest'teki aynı 82 feature'ı üretir.
Kaynak eşleştirmesi:
  - Market (8): AGF scraper'dan (odds, implied prob, rank vs.)
  - Form (7): PDF'ten (last_6_races, last_20_score)
  - Physical (7): PDF + AGF'den (weight, distance, gate, handicap)
  - HorseProfile (7): PDF'ten (age, gender, earnings, rest days)
  - Jockey/Trainer (6): rolling_stats.json
  - Pedigree + Family (9): rolling_stats.json
  - Conditions (9): PDF + rolling_stats
  - Equipment (5): PDF'ten
  - Pace (3): tarihsel ortalama (rolling_stats), canlıda yaklaşık
  - Surprise (2): rolling_stats race profiles
  - Interactions (18): yukarıdakilerin çarpımları
  - model_vs_market (1): 2. pass'ta hesaplanır
"""
import numpy as np
import json
import os
import re
import logging
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

STATS_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)), 'trained', 'rstats.json'
)


class FeatureBuilder:
    """Builds 82 features for each horse in a race."""

    def __init__(self, stats_path=None):
        self.stats_path = stats_path or STATS_PATH
        self.stats = None
        self.feature_cols = None

    def load(self):
        """Load rolling stats and feature column order."""
        # Rolling stats — optional, model works without it (just fewer features filled)
        if os.path.exists(self.stats_path):
            try:
                with open(self.stats_path, 'r', encoding='utf-8') as f:
                    self.stats = json.load(f)
                logger.info(f"Rolling stats loaded: {list(self.stats.keys())}")
            except Exception as e:
                logger.warning(f"Rolling stats parse error: {e}")
                self.stats = {}
        else:
            logger.warning(f"Rolling stats not found: {self.stats_path} — using defaults")
            self.stats = {}

        # Feature column order — required
        json_path = os.path.join(
            os.path.dirname(self.stats_path), 'feature_columns.json'
        )
        if os.path.exists(json_path):
            with open(json_path) as f:
                self.feature_cols = json.load(f)
            logger.info(f"Feature columns: {len(self.feature_cols)}")
        else:
            logger.error("feature_columns.json not found!")
            self.feature_cols = []

        # Feature cols yeterliyse True dön — stats olmasa da çalışabiliriz
        return bool(self.feature_cols)

    def build_race_features(self, horses, race_info, agf_data=None):
        """
        Tek bir koşu için tüm atların feature matrix'ini üret.

        Args:
            horses: list of dicts from PDF parser, each with:
                horse_name, horse_number, jockey_name, trainer_name,
                weight, age, form (last_6_races string), equipment, etc.
            race_info: dict with:
                distance, track_type, group_name, hippodrome_name,
                first_prize, temperature, humidity, race_date
            agf_data: list of dicts from AGF scraper:
                [{horse_number, agf_pct, is_ekuri}, ...]

        Returns:
            numpy array (n_horses, 82) in correct column order
            list of horse names in same order
        """
        if not self.feature_cols:
            raise RuntimeError("Feature columns not loaded! Call load() first.")

        g = self.stats.get('global', {})
        n_horses = len(horses)
        field_size = n_horses

        # AGF lookup by horse number
        agf_by_num = {}
        if agf_data:
            for h in agf_data:
                agf_by_num[h['horse_number']] = h

        # All odds for race-level features
        all_odds = []
        for h in horses:
            num = h.get('horse_number', 0)
            agf = agf_by_num.get(num, {})
            pct = agf.get('agf_pct', 0)
            if pct > 0:
                odds = 100.0 / pct
            else:
                odds = 20.0  # default high odds
            all_odds.append(odds)

        # Race-level features
        min_odds = min(all_odds) if all_odds else 1.0
        odds_std = np.std(all_odds) if len(all_odds) > 1 else 0
        odds_mean = np.mean(all_odds) if all_odds else 10.0
        race_odds_cv = odds_std / (odds_mean + 0.01)

        # Odds entropy
        if all_odds and sum(all_odds) > 0:
            probs = np.array([1.0/o if o > 0 else 0.01 for o in all_odds])
            probs = probs / probs.sum()
            odds_entropy = -np.sum(probs * np.log(probs + 1e-10))
        else:
            odds_entropy = 0.5

        # Avg winner odds (from upset_rate profile)
        avg_winner_odds = 5.0  # default

        # Race surprise score
        surprise_key = self._build_surprise_key(field_size, race_info)
        surprise_data = self.stats.get('race_surprise', {}).get(surprise_key, {})
        surprise_score = surprise_data.get('surprise_rate', 0.5)

        # Upset rate for hippodrome
        hippo_name = race_info.get('hippodrome_name', '')
        upset_rate = self.stats.get('upset_rate', {}).get(hippo_name, 0.3)

        # Race conditions
        distance = race_info.get('distance', 1400)
        track_type = race_info.get('track_type', 'dirt')
        first_prize = race_info.get('first_prize', 100000)
        temperature = race_info.get('temperature', 15)
        humidity = race_info.get('humidity', 60)
        race_date = race_info.get('race_date', None)

        is_dirt = 1.0 if track_type == 'dirt' else 0.0
        is_synthetic = 1.0 if track_type == 'synthetic' else 0.0
        hippo_enc = self.stats.get('hippodrome_encoding', {}).get(hippo_name, 0.5)
        race_class = self._safe_norm_val(np.log1p(first_prize), 0, np.log1p(g.get('prize_max', 1000000)))
        f_field_size = self._safe_norm_val(field_size, 2, 18)
        is_weekend = 0.0
        day_of_week = 0.0
        if race_date:
            import datetime
            if isinstance(race_date, str):
                race_date = datetime.datetime.strptime(race_date[:10], '%Y-%m-%d')
            is_weekend = 1.0 if race_date.weekday() >= 5 else 0.0
            day_of_week = race_date.weekday() / 6.0

        f_temperature = self._safe_norm_val(temperature, -5, 45)
        f_humidity = self._safe_norm_val(humidity, 10, 100)
        f_distance = self._safe_norm_val(distance, g.get('distance_min', 800), g.get('distance_max', 2400))
        f_dist_mid = 1.0 if 1200 < distance <= 1600 else 0.0
        f_dist_mile = 1.0 if 1600 < distance <= 2000 else 0.0

        # Fav1 vs fav2 gap
        sorted_odds = sorted(all_odds)
        if len(sorted_odds) >= 2 and sorted_odds[0] > 0:
            fav1v2_gap = sorted_odds[1] / sorted_odds[0]
        else:
            fav1v2_gap = 1.0
        fav1v2_gap = self._safe_norm_val(fav1v2_gap, 1.0, 10.0)

        # ── Build per-horse features ──
        rows = []
        horse_names = []

        for h in horses:
            f = {}
            num = h.get('horse_number', 0)
            name = h.get('horse_name', f'#{num}')
            horse_names.append(name)

            # ── MARKET (from AGF) ──
            agf = agf_by_num.get(num, {})
            agf_pct = agf.get('agf_pct', 5.0)
            odds = 100.0 / agf_pct if agf_pct > 0 else 20.0

            f['f_agf_log'] = self._safe_norm_val(np.log1p(min(odds, 200)), 0, np.log1p(200))
            f['f_agf_implied_prob'] = min(1.0 / (odds + 0.01), 1.0) if odds > 0 else 0.0
            f['f_agf_rank'] = self._safe_norm_val(
                agf.get('agf_rank', len(horses)),
                1, len(horses)
            ) if 'agf_rank' not in agf else self._safe_norm_val(
                sorted([a['agf_pct'] for a in agf_data], reverse=True).index(agf_pct) + 1
                if agf_data and agf_pct in [a['agf_pct'] for a in agf_data] else len(horses),
                1, len(horses)
            )
            f['f_agf_fav_margin'] = self._safe_norm_val(
                odds / (min_odds + 0.01), 1.0, 50.0
            )
            f['f_race_odds_cv'] = self._safe_norm_val(race_odds_cv, 0, 3)
            f['f_odds_entropy'] = self._safe_norm_val(odds_entropy, 0, 3)
            f['f_avg_winner_odds'] = self._safe_norm_val(avg_winner_odds, 1, 50)
            f['f_fav1v2_gap'] = fav1v2_gap
            f['f_is_favorite'] = 1.0 if abs(odds - min_odds) < 0.01 else 0.0  # extra, not in 82

            # ── FORM (from PDF or default) ──
            form_str = h.get('form', h.get('last_6_races', ''))
            parsed = self._parse_form(form_str)
            positions = [p for _, p in parsed if p > 0]

            f['f_form_last1'] = 1.0 / (parsed[-1][1] + 1) if parsed and parsed[-1][1] > 0 else 0.0
            f['f_form_best'] = 1.0 / (min(positions, default=10) + 1)
            f['f_form_consistency'] = 1.0 / (np.std(positions) + 1) if len(positions) >= 2 else 0.0
            f['f_form_trend'] = self._calc_form_trend(parsed)
            f['f_form_dirt_pct'] = sum(1 for t, _ in parsed if t == 'K') / max(len(parsed), 1) if parsed else 0.5
            f['f_surface_match'] = self._calc_surface_match(parsed, track_type)
            f['f_last20_score'] = h.get('last_20_score', 10) / 20.0

            # ── PHYSICAL ──
            weight = h.get('weight', 57)
            f['f_weight'] = self._safe_norm_val(weight, g.get('weight_min', 50), g.get('weight_max', 62))
            f['f_distance'] = f_distance
            f['f_dist_mid'] = f_dist_mid
            f['f_dist_mile'] = f_dist_mile
            f['f_gate'] = self._safe_norm_val(h.get('gate_number', h.get('start_position', 5)),
                                               g.get('gate_min', 1), g.get('gate_max', 18))
            f['f_handicap'] = self._safe_norm_val(h.get('handicap', 60),
                                                   g.get('handicap_min', 0), g.get('handicap_max', 100))
            f['f_extra_weight'] = self._safe_norm_val(h.get('extra_weight', 0),
                                                       g.get('extra_weight_min', 0), g.get('extra_weight_max', 5))

            # ── HORSE PROFILE ──
            age = h.get('age', 4)
            f['f_age'] = self._safe_norm_val(age, 2, 10)
            f['f_gender_mare'] = 1.0 if h.get('gender') == 'female' or 'k' in str(h.get('age_text', '')) else 0.0
            f['f_gender_stallion'] = 1.0 if 'a' in str(h.get('age_text', '')) else 0.0
            f['f_gender_gelding'] = 1.0 if 'e' in str(h.get('age_text', '')) else 0.0
            earnings = h.get('total_earnings', 0) or 0
            f['f_earnings'] = self._safe_norm_val(earnings, 0, g.get('earnings_max', 5000000))
            kgs = h.get('kgs', 30) or 30
            f['f_days_rest'] = self._safe_norm_val(min(kgs, 200), 0, 200)
            f['f_rested'] = 1.0 if kgs >= 30 else 0.0

            # ── JOCKEY ──
            jockey = h.get('jockey_name', '')
            j_stats = self.stats.get('jockey', {}).get(jockey, {})
            f['f_jockey_win_rate'] = j_stats.get('win_rate', 0)
            f['f_jockey_top3_rate'] = j_stats.get('top3_rate', 0)
            f['f_jockey_experience'] = min(j_stats.get('experience', 0) / 200.0, 1.0)

            # ── TRAINER ──
            trainer = h.get('trainer_name', '')
            t_stats = self.stats.get('trainer', {}).get(trainer, {})
            f['f_trainer_win_rate'] = t_stats.get('win_rate', 0)
            f['f_trainer_experience'] = min(t_stats.get('experience', 0) / 100.0, 1.0)

            # ── PEDIGREE ──
            sire = h.get('sire', '')
            dam_sire = h.get('dam_sire', '')
            sire_sire = h.get('sire_sire', '')
            f['f_sire_win_rate'] = self.stats.get('sire', {}).get(sire, {}).get('win_rate', 0)
            f['f_dam_sire_win_rate'] = self.stats.get('dam_sire', {}).get(dam_sire, {}).get('win_rate', 0)
            f['f_sire_sire_win_rate'] = self.stats.get('sire_sire', {}).get(sire_sire, {}).get('win_rate', 0)

            # ── PEDIGREE FAMILY ──
            dam = h.get('dam', '')
            # Try rolling stats first, then horse_dam mapping
            if not dam:
                dam = self.stats.get('horse_dam', {}).get(name, '')
            dp = self.stats.get('dam_produce', {}).get(dam, {})
            f['f_dam_produce_wr'] = dp.get('win_rate', 0)
            f['f_dam_produce_top3'] = dp.get('top3_rate', 0)
            f['f_dam_n_offspring'] = min(dp.get('n_offspring', 0) / 5.0, 1.0)
            f['f_dam_best_earner'] = min(dp.get('best_earner', 0) / 500000.0, 1.0)

            damdam = h.get('dam_dam', '')
            if not damdam:
                damdam = self.stats.get('horse_damdam', {}).get(name, '')
            f['f_damdam_family_wr'] = self.stats.get('damdam', {}).get(damdam, {}).get('win_rate', 0)

            # Sibling
            sib = self.stats.get('sibling', {}).get(dam, {})
            sibling_top3 = sib.get('top3_rate', 0)

            # ── CONDITIONS ──
            f['f_is_dirt'] = is_dirt
            f['f_is_synthetic'] = is_synthetic
            f['f_hippodrome'] = hippo_enc
            f['f_temperature'] = f_temperature
            f['f_humidity'] = f_humidity
            f['f_race_class'] = race_class
            f['f_field_size'] = f_field_size
            f['f_is_weekend'] = is_weekend
            f['f_day_of_week'] = day_of_week

            # ── EQUIPMENT ──
            eq = h.get('equipment', '')
            f['f_equip_kg'] = 1.0 if 'KG' in eq else 0.0
            f['f_equip_db'] = 1.0 if 'DB' in eq else 0.0
            f['f_equip_skg'] = 1.0 if 'SKG' in eq else 0.0
            f['f_equip_sk'] = 1.0 if re.search(r'\bSK\b', eq) else 0.0
            f['f_equip_count'] = len(eq.split()) / 4.0 if eq else 0.0

            # ── PACE (approximate from historical) ──
            f['f_pace_relative'] = 0.5  # neutral — no live pace data
            f['f_pace_best_time'] = 0.5
            f['f_pace_race_avg'] = 0.5
            # If best_time available from taydex
            best_time = h.get('best_time', None)
            if best_time and isinstance(best_time, (int, float)) and best_time > 0:
                f['f_pace_best_time'] = self._safe_norm_val(best_time, 60, 160)

            # ── SURPRISE ──
            f['f_surprise_v2'] = surprise_score
            f['f_upset_rate'] = upset_rate

            # ── INTERACTIONS ──
            form_avg_pos = 1.0 / (np.mean(positions) + 1) if positions else 0.125
            form_top3 = sum(1 for p in positions if 1 <= p <= 3) / max(len(positions), 1) if positions else 0
            form_wins = sum(1 for p in positions if p == 1) / max(len(positions), 1) if positions else 0
            earnings_log = self._safe_norm_val(np.log1p(earnings), 0, np.log1p(g.get('earnings_max', 5000000)))

            jt_key = f"{jockey}||{trainer}"
            jt_wr = self.stats.get('jockey_trainer', {}).get(jt_key, {}).get('win_rate', 0)

            f['f_X_surprise_agf'] = surprise_score * f['f_agf_implied_prob']
            f['f_X_jockey_form'] = f['f_jockey_win_rate'] * form_wins
            f['f_X_dam_jockey'] = f['f_dam_produce_wr'] * f['f_jockey_win_rate']
            f['f_X_earnings_class'] = earnings_log * race_class
            f['f_X_earnings_form'] = earnings_log * form_avg_pos
            f['f_X_form_field'] = form_avg_pos * f_field_size
            f['f_X_surface_form'] = f['f_surface_match'] * form_avg_pos
            f['f_X_agf_form'] = f['f_agf_implied_prob'] * form_top3
            f['f_X_form_class'] = form_avg_pos * race_class
            f['f_X_sibling_form'] = sibling_top3 * form_top3
            f['f_X_surprise_field'] = surprise_score * f_field_size
            f['f_X_pace_form'] = f['f_pace_relative'] * form_avg_pos
            f['f_X_trainer_form'] = f['f_trainer_win_rate'] * form_avg_pos
            f['f_X_jockey_trainer'] = f['f_jockey_win_rate'] * f['f_trainer_win_rate']
            f['f_X_agf_jockey'] = f['f_agf_implied_prob'] * f['f_jockey_win_rate']
            f['f_X_jockey_class'] = f['f_jockey_win_rate'] * race_class
            f['f_X_jt_combo_form'] = jt_wr * form_top3
            f['f_X_age_trend'] = f['f_age'] * f['f_form_trend']
            f['f_X_sire_dist'] = f['f_sire_win_rate'] * f_distance
            f['f_X_dam_class'] = f['f_dam_produce_wr'] * race_class

            # model_vs_market: placeholder, computed after first predict pass
            f['f_model_vs_market'] = 0.0

            rows.append(f)

        # Build matrix in correct column order
        matrix = np.zeros((n_horses, len(self.feature_cols)))
        for i, row in enumerate(rows):
            for j, col in enumerate(self.feature_cols):
                matrix[i, j] = row.get(col, 0.0)

        # Replace NaN/inf
        matrix = np.nan_to_num(matrix, nan=0.0, posinf=1.0, neginf=0.0)

        return matrix, horse_names

    def update_model_vs_market(self, matrix, model_scores):
        """
        2nd pass: f_model_vs_market = model rank - AGF rank difference.
        Call after first predict, then predict again.
        """
        if 'f_model_vs_market' not in self.feature_cols:
            return matrix

        col_idx = self.feature_cols.index('f_model_vs_market')
        agf_rank_idx = self.feature_cols.index('f_agf_rank') if 'f_agf_rank' in self.feature_cols else None

        if agf_rank_idx is None:
            return matrix

        # Model rank (1 = best)
        model_ranks = np.argsort(np.argsort(-model_scores)) + 1
        agf_ranks = matrix[:, agf_rank_idx] * len(model_scores)  # denormalize

        # Positive = model thinks horse is better than market
        diff = agf_ranks - model_ranks
        matrix[:, col_idx] = self._safe_norm_val(diff.mean(), -10, 10)  # simplified

        return matrix

    # ── Helper methods ──

    def _parse_form(self, form_str):
        """Parse 'K4K1K1K7K3K1' → [('K',4), ('K',1), ...]"""
        if not form_str or not isinstance(form_str, str):
            return []
        return [(t, int(p)) for t, p in re.findall(r'([KC])(\d+)', form_str)]

    def _calc_form_trend(self, parsed):
        if len(parsed) < 4:
            return 0.0
        half = len(parsed) // 2
        first = [p for _, p in parsed[:half] if p > 0]
        second = [p for _, p in parsed[half:] if p > 0]
        if not first or not second:
            return 0.0
        avg_first = np.mean(first)
        avg_second = np.mean(second)
        return (avg_first - avg_second) / (avg_first + 1)

    def _calc_surface_match(self, parsed, track_type):
        if not parsed:
            return 0.5
        if track_type == 'dirt':
            return sum(1 for t, _ in parsed if t == 'K') / len(parsed)
        else:
            return sum(1 for t, _ in parsed if t == 'C') / len(parsed)

    def _build_surprise_key(self, field_size, race_info):
        fs_bucket = 'small' if field_size <= 7 else ('medium' if field_size <= 11 else 'large')
        group = race_info.get('group_name', '')
        is_arab = 1 if 'arap' in group.lower() else 0
        track = race_info.get('track_type', 'dirt')
        hippo = race_info.get('hippodrome_name', 'UNK')
        return f"{fs_bucket}|{is_arab}|{track}|{hippo}"

    @staticmethod
    def _safe_norm_val(val, mn, mx):
        if mx == mn:
            return 0.5
        return max(0.0, min(1.0, (val - mn) / (mx - mn)))
