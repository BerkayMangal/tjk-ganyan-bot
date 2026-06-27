"""FAZ A — Forward-Looking Foundation testleri.

Recency + Trajectory + Recovery + Glicko-2 + Integration.
Bilimsel doğruluk + edge case + graceful failure.
"""
from __future__ import annotations

import math
import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.recency import (
    compute_recency_features, empirical_bayes_shrinkage,
    recent_vs_career_gap, weighted_rate, window_rate,
)
from forecast.trajectory import (
    bounce_risk, class_movement_score, compute_trajectory_features,
    default_class_score, distance_progression, finish_trend_signal,
    linear_slope, trend_direction,
)
from forecast.recovery import (
    comeback_score, compute_recovery_features, days_since, parse_date,
    recovery_bucket,
)
from forecast.glicko import (
    DEFAULT_RATING_HORSE, GlickoLedger, GlickoRating, expected_score,
    predict_top_n_probability, race_results_to_pairwise, update_rating,
)
from forecast.integration import (
    compute_horse_forward_features, forward_signal_summary,
)


# ----- RECENCY -------------------------------------------------------------
class TestWeightedRate(unittest.TestCase):
    def test_all_top4_returns_1(self):
        # Tüm koşular ilk 4'te
        self.assertAlmostEqual(weighted_rate([1, 2, 3, 4], target=4), 1.0)

    def test_none_top4_returns_0(self):
        self.assertAlmostEqual(weighted_rate([5, 6, 7, 8], target=4), 0.0)

    def test_recency_weighting(self):
        # Son koşu top4 (1), önceki üç dışında (5, 5, 5)
        # Decay 0.85: w = [1, 0.85, 0.7225, 0.6141]
        # rate = 1 * 1 / (1+0.85+0.7225+0.6141) = 1/3.187 ≈ 0.314
        r = weighted_rate([1, 5, 5, 5], target=4, decay=0.85)
        self.assertGreater(r, 0.30)
        self.assertLess(r, 0.40)

    def test_decay_1_equals_unweighted(self):
        positions = [1, 5, 1, 5, 1]
        unweighted = sum(1 for p in positions if p <= 4) / len(positions)
        weighted = weighted_rate(positions, target=4, decay=1.0)
        self.assertAlmostEqual(weighted, unweighted)

    def test_empty_returns_none(self):
        self.assertIsNone(weighted_rate([], target=4))

    def test_all_none_returns_none(self):
        self.assertIsNone(weighted_rate([None, None], target=4))

    def test_invalid_decay_raises(self):
        with self.assertRaises(ValueError):
            weighted_rate([1, 2], decay=-0.1)
        with self.assertRaises(ValueError):
            weighted_rate([1, 2], decay=2.0)


class TestWindowRate(unittest.TestCase):
    def test_window_smaller_than_data(self):
        # Son 3 koşu: [1, 5, 1] → 2 top4 hit / 3 = 0.667
        self.assertAlmostEqual(
            window_rate([1, 5, 1, 5, 5], window=3, target=4),
            2 / 3,
            places=3,
        )

    def test_window_larger_than_data(self):
        # 2 koşu, window=10 → kullan 2'sini
        self.assertEqual(window_rate([1, 2], window=10, target=4), 1.0)

    def test_none_window(self):
        self.assertIsNone(window_rate([None, None, None], 3, 4))


class TestGapSignal(unittest.TestCase):
    def test_improving_trend(self):
        # Kariyer %20, son 5 %80 → gap = +0.6 (TREND YUKARI)
        positions = [1, 1, 1, 1, 1, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9, 9]
        # 5 top4 + 20 dışı = career 5/25 = 0.20
        # son 5 = 5/5 = 1.0
        # gap = 1.0 - 0.20 = +0.80
        gap = recent_vs_career_gap(positions, recent_window=5, target=4)
        self.assertGreater(gap, 0.7)

    def test_declining_trend(self):
        positions = [9, 9, 9, 9, 9, 1, 1, 1, 1, 1]
        gap = recent_vs_career_gap(positions, 5, 4)
        # Son 5 = 0%, kariyer = 50%, gap = -0.50
        self.assertLess(gap, 0)


class TestShrinkage(unittest.TestCase):
    def test_high_n_close_to_observed(self):
        # n=100, observed=0.80, prior=0.40 → ≈0.77
        s = empirical_bayes_shrinkage(0.80, n=100, prior_rate=0.40, prior_n=8)
        self.assertGreater(s, 0.75)

    def test_low_n_close_to_prior(self):
        # n=2, observed=1.0, prior=0.40 → strong pull
        s = empirical_bayes_shrinkage(1.0, n=2, prior_rate=0.40, prior_n=8)
        # (2*1 + 8*0.4) / 10 = 5.2/10 = 0.52
        self.assertAlmostEqual(s, 0.52, places=2)


class TestRecencyComposite(unittest.TestCase):
    def test_all_features_present(self):
        rf = compute_recency_features([1, 2, 3, 4, 5, 6, 7, 8, 9, 10], 4)
        self.assertEqual(rf.n_races, 10)
        self.assertIsNotNone(rf.weighted_top4_85)
        self.assertIsNotNone(rf.last5_top4)
        self.assertIsNotNone(rf.gap_recent5_career_top4)

    def test_empty_input(self):
        rf = compute_recency_features([], 4)
        self.assertEqual(rf.n_races, 0)
        self.assertIsNone(rf.weighted_top4_85)


# ----- TRAJECTORY ----------------------------------------------------------
class TestLinearSlope(unittest.TestCase):
    def test_increasing_sequence(self):
        # y = x (slope 1)
        self.assertAlmostEqual(linear_slope([0, 1, 2, 3, 4]), 1.0)

    def test_constant(self):
        self.assertAlmostEqual(linear_slope([5, 5, 5, 5]), 0.0)

    def test_decreasing(self):
        self.assertAlmostEqual(linear_slope([4, 3, 2, 1, 0]), -1.0)

    def test_single_point(self):
        self.assertIsNone(linear_slope([5]))

    def test_all_none(self):
        self.assertIsNone(linear_slope([None, None]))


class TestFinishTrend(unittest.TestCase):
    def test_improving_at(self):
        # Index 0 = newest. Positions [1, 3, 5, 7] = newest is 1st, oldest 7th
        # ⇒ improving (positions decreasing toward newest)
        sig = finish_trend_signal([1, 3, 5, 7])
        self.assertIsNotNone(sig)
        self.assertGreater(sig, 0.3)

    def test_declining_at(self):
        # newest 7th, oldest 1st = at kötüleşiyor
        sig = finish_trend_signal([7, 5, 3, 1])
        self.assertLess(sig, -0.3)

    def test_stable(self):
        sig = finish_trend_signal([3, 3, 3, 3])
        self.assertAlmostEqual(sig, 0.0, places=2)


class TestClassMovement(unittest.TestCase):
    def test_class_score_g1(self):
        self.assertEqual(default_class_score("G 1"), 100.0)
        self.assertEqual(default_class_score("G 2"), 90.0)
        self.assertEqual(default_class_score("G 3"), 80.0)

    def test_class_score_maiden(self):
        self.assertEqual(default_class_score("Maiden"), 20.0)

    def test_class_score_kv(self):
        # KV-7 → 75 - 7 = 68
        self.assertEqual(default_class_score("KV-7"), 68.0)

    def test_movement_rising(self):
        # En taze G2, sonra G3, sonra KV-7 → at yükseliyor → slope NEGATIF
        records = [
            {"kosu_cinsi": "G 2"},
            {"kosu_cinsi": "G 3"},
            {"kosu_cinsi": "KV-7"},
        ]
        slope = class_movement_score(records)
        self.assertLess(slope, 0)


class TestBounceRisk(unittest.TestCase):
    def test_high_after_win(self):
        # Latest position = 1 → bounce risk yüksek
        self.assertEqual(bounce_risk([1, 5, 5]), 0.7)

    def test_low_for_mid_finishes(self):
        self.assertLessEqual(bounce_risk([7, 5, 5]), 0.2)


# ----- RECOVERY ------------------------------------------------------------
class TestParseDate(unittest.TestCase):
    def test_iso(self):
        d = parse_date("2026-06-27")
        self.assertIsNotNone(d)
        self.assertEqual(d.year, 2026)

    def test_invalid(self):
        self.assertIsNone(parse_date("bogus"))
        self.assertIsNone(parse_date(None))


class TestRecoveryBucket(unittest.TestCase):
    def test_buckets(self):
        self.assertEqual(recovery_bucket(7), "hot")
        self.assertEqual(recovery_bucket(20), "fresh")
        self.assertEqual(recovery_bucket(45), "rested")
        self.assertEqual(recovery_bucket(100), "mola")
        self.assertEqual(recovery_bucket(300), "long_mola")
        self.assertEqual(recovery_bucket(None), "unknown")


class TestComebackScore(unittest.TestCase):
    def test_score_curve(self):
        self.assertEqual(comeback_score(10), 0.0)
        self.assertEqual(comeback_score(45), 0.15)
        self.assertGreater(comeback_score(200), 0.5)
        self.assertGreater(comeback_score(400), 0.7)


class TestRecoveryComposite(unittest.TestCase):
    def test_full(self):
        records = [
            {"date": "2026-06-20"},   # 7 days  → in last 60d
            {"date": "2026-05-15"},   # 43 days → in last 60d
            {"date": "2026-04-01"},   # 87 days → NOT in last 60d
        ]
        rf = compute_recovery_features(records, ref_date="2026-06-27")
        self.assertEqual(rf.days_since_last, 7)
        self.assertEqual(rf.bucket, "hot")
        self.assertEqual(rf.n_races_in_last_60d, 2)


# ----- GLICKO --------------------------------------------------------------
class TestGlickoRating(unittest.TestCase):
    def test_default_rating(self):
        r = GlickoRating()
        self.assertEqual(r.rating, DEFAULT_RATING_HORSE)
        self.assertEqual(r.rd, 350)

    def test_to_from_g2_roundtrip(self):
        r = GlickoRating(1600, 200, 0.06)
        mu, phi = r.to_g2()
        r2 = GlickoRating.from_g2(mu, phi, 0.06)
        self.assertAlmostEqual(r.rating, r2.rating, places=3)
        self.assertAlmostEqual(r.rd, r2.rd, places=3)


class TestGlickoExpectedScore(unittest.TestCase):
    def test_equal_returns_half(self):
        a = GlickoRating(1500, 100, 0.06)
        b = GlickoRating(1500, 100, 0.06)
        e = expected_score(a, b)
        self.assertAlmostEqual(e, 0.5, places=2)

    def test_higher_rating_wins(self):
        strong = GlickoRating(1800, 100, 0.06)
        weak = GlickoRating(1200, 100, 0.06)
        self.assertGreater(expected_score(strong, weak), 0.85)
        self.assertLess(expected_score(weak, strong), 0.15)


class TestGlickoUpdate(unittest.TestCase):
    def test_win_raises_rating(self):
        player = GlickoRating(1500, 200, 0.06)
        opp = GlickoRating(1500, 200, 0.06)
        new = update_rating(player, [(opp, 1.0)])
        self.assertGreater(new.rating, player.rating)
        self.assertLess(new.rd, player.rd)

    def test_loss_lowers_rating(self):
        player = GlickoRating(1500, 200, 0.06)
        opp = GlickoRating(1500, 200, 0.06)
        new = update_rating(player, [(opp, 0.0)])
        self.assertLess(new.rating, player.rating)

    def test_no_games_increases_rd(self):
        # No games in rating period → RD grows
        player = GlickoRating(1500, 200, 0.06)
        new = update_rating(player, [])
        self.assertGreaterEqual(new.rd, player.rd)

    def test_upset_large_update(self):
        # Strong player loses to weak → big rating drop
        strong = GlickoRating(1800, 100, 0.06)
        weak = GlickoRating(1200, 100, 0.06)
        new = update_rating(strong, [(weak, 0.0)])
        self.assertLess(new.rating, 1750)


class TestRaceToPairwise(unittest.TestCase):
    def test_winner_pairwise(self):
        r1 = GlickoRating(1500, 100, 0.06)
        r2 = GlickoRating(1500, 100, 0.06)
        r3 = GlickoRating(1500, 100, 0.06)
        # Horse 0 finished 1st, horse 1 finished 2nd, horse 2 finished 3rd
        finishes = [(r1, 1), (r2, 2), (r3, 3)]
        pairs = race_results_to_pairwise(finishes, horse_index=0)
        self.assertEqual(len(pairs), 2)
        # Beat both: scores all 1.0
        self.assertTrue(all(s == 1.0 for _, s in pairs))


class TestPredictTopN(unittest.TestCase):
    def test_solo_runner(self):
        # 1 at → top-1 = certain
        r = GlickoRating()
        p = predict_top_n_probability(r, [], target_n=1)
        self.assertEqual(p, 1.0)

    def test_strong_target_high_topn(self):
        target = GlickoRating(2000, 80, 0.05)
        opps = [GlickoRating(1300, 200, 0.10) for _ in range(8)]
        p = predict_top_n_probability(target, opps, target_n=1, n_samples=1500)
        self.assertGreater(p, 0.7)

    def test_weak_target_low_top1(self):
        target = GlickoRating(1100, 80, 0.05)
        opps = [GlickoRating(1700, 80, 0.05) for _ in range(8)]
        p = predict_top_n_probability(target, opps, target_n=1, n_samples=1500)
        self.assertLess(p, 0.1)


class TestGlickoLedger(unittest.TestCase):
    def test_get_default(self):
        led = GlickoLedger()
        r = led.get("NEW_HORSE")
        self.assertEqual(r.rating, DEFAULT_RATING_HORSE)

    def test_update_persist(self):
        led = GlickoLedger()
        opp = GlickoRating()
        led.update("RABOVO", [(opp, 1.0)])
        self.assertGreater(led.get("RABOVO").rating, DEFAULT_RATING_HORSE)

    def test_json_roundtrip(self):
        led = GlickoLedger()
        led.set("X", GlickoRating(1700, 180, 0.07))
        data = led.to_json()
        led2 = GlickoLedger.from_json(data)
        self.assertAlmostEqual(led2.get("X").rating, 1700)
        self.assertAlmostEqual(led2.get("X").rd, 180)


# ----- INTEGRATION --------------------------------------------------------
class TestIntegration(unittest.TestCase):
    def _sample_history(self):
        return [
            {"finish": 2, "date": "2026-06-20", "kosu_cinsi": "G 3", "mesafe": 2200},
            {"finish": 4, "date": "2026-05-10", "kosu_cinsi": "KV-7", "mesafe": 2000},
            {"finish": 3, "date": "2026-04-01", "kosu_cinsi": "KV-8", "mesafe": 1800},
            {"finish": 5, "date": "2026-02-15", "kosu_cinsi": "Maiden", "mesafe": 1600},
        ]

    def test_compute_returns_dict(self):
        feat = compute_horse_forward_features(
            "RABOVO", self._sample_history(), ref_date="2026-06-27",
        )
        self.assertIn("recency", feat)
        self.assertIn("trajectory", feat)
        self.assertIn("recovery", feat)
        self.assertEqual(feat["history_n"], 4)

    def test_glicko_attaches(self):
        led = GlickoLedger()
        led.set("RABOVO", GlickoRating(1700, 150, 0.06))
        feat = compute_horse_forward_features(
            "RABOVO", self._sample_history(), glicko_ledger=led,
        )
        self.assertIn("glicko", feat)
        self.assertAlmostEqual(feat["glicko"]["rating"], 1700)

    def test_summary_shape(self):
        feat = compute_horse_forward_features(
            "RABOVO", self._sample_history(), ref_date="2026-06-27",
        )
        sum_ = forward_signal_summary(feat)
        for k in ("trend", "form_recent_top4", "recovery_status",
                  "verdict"):
            self.assertIn(k, sum_)

    def test_empty_history(self):
        feat = compute_horse_forward_features("X", [])
        self.assertEqual(feat["history_n"], 0)
        # Should still produce a valid summary
        sum_ = forward_signal_summary(feat)
        self.assertEqual(sum_["trend"], "unknown")


if __name__ == "__main__":
    unittest.main()
