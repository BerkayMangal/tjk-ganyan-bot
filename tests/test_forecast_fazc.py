"""FAZ C — Pace + AGF Drift Dynamics testleri."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.pace.pace import (
    PaceStyle, STYLE_CLOSER, STYLE_FRONT, STYLE_MID, STYLE_STALKER,
    STYLE_UNKNOWN, infer_pace_style, pace_adjusted_topn,
    race_tempo_simulation,
)
from forecast.pace.dynamics import (
    DriftMetrics, classify_market_move, compute_drift_metrics,
    confidence_from_volatility, crowd_convergence_score,
    steam_move_advantage,
)


# ----- PACE STYLE ----------------------------------------------------------
class TestInferStyle(unittest.TestCase):
    def test_empty(self):
        st = infer_pace_style([])
        self.assertEqual(st.primary, STYLE_UNKNOWN)

    def test_front_inference(self):
        # G1/G2 koşularda 1. ve 2. çıkmış güçlü at = FRONT
        records = [
            {"finish": 1, "kosu_cinsi": "G 2"},
            {"finish": 2, "kosu_cinsi": "G 2"},
            {"finish": 1, "kosu_cinsi": "G 3"},
            {"finish": 2, "kosu_cinsi": "G 2"},
        ]
        st = infer_pace_style(records)
        self.assertEqual(st.primary, STYLE_FRONT)
        self.assertGreater(st.confidence, 0.4)

    def test_closer_inference(self):
        # Yarış sonu top4 yapıyor (3-4) ama top2 değil → closer
        records = [
            {"finish": 3, "kosu_cinsi": "KV-7"},
            {"finish": 4, "kosu_cinsi": "KV-8"},
            {"finish": 3, "kosu_cinsi": "KV-7"},
            {"finish": 4, "kosu_cinsi": "KV-8"},
        ]
        st = infer_pace_style(records)
        self.assertEqual(st.primary, STYLE_CLOSER)

    def test_mid_inference(self):
        # Hep arka sıralarda
        records = [
            {"finish": 8, "kosu_cinsi": "ŞARTLI 4"},
            {"finish": 9, "kosu_cinsi": "Maiden"},
            {"finish": 7, "kosu_cinsi": "ŞARTLI 5"},
        ]
        st = infer_pace_style(records)
        self.assertIn(st.primary, (STYLE_MID,))


# ----- RACE TEMPO ----------------------------------------------------------
class TestRaceTempo(unittest.TestCase):
    def test_zero_front_slow(self):
        styles = [PaceStyle(primary=STYLE_CLOSER) for _ in range(8)]
        r = race_tempo_simulation(styles)
        self.assertEqual(r.tempo, "slow")
        self.assertLess(r.closer_advantage, 0)

    def test_one_front_even(self):
        styles = ([PaceStyle(primary=STYLE_FRONT)]
                  + [PaceStyle(primary=STYLE_MID) for _ in range(7)])
        r = race_tempo_simulation(styles)
        self.assertEqual(r.tempo, "even")
        self.assertEqual(r.closer_advantage, 0.0)

    def test_many_fronts_hot(self):
        styles = ([PaceStyle(primary=STYLE_FRONT) for _ in range(5)]
                  + [PaceStyle(primary=STYLE_CLOSER) for _ in range(3)])
        r = race_tempo_simulation(styles)
        self.assertEqual(r.tempo, "hot")
        self.assertGreater(r.closer_advantage, 0.15)


class TestPaceAdjusted(unittest.TestCase):
    def test_closer_boosted_by_hot(self):
        hot_tempo = race_tempo_simulation(
            [PaceStyle(primary=STYLE_FRONT) for _ in range(5)]
        )
        closer = PaceStyle(primary=STYLE_CLOSER, confidence=0.8)
        adjusted = pace_adjusted_topn(closer, hot_tempo, base_prob=0.20)
        self.assertGreater(adjusted, 0.20)

    def test_front_lowered_by_hot(self):
        hot_tempo = race_tempo_simulation(
            [PaceStyle(primary=STYLE_FRONT) for _ in range(5)]
        )
        front = PaceStyle(primary=STYLE_FRONT, confidence=0.8)
        adjusted = pace_adjusted_topn(front, hot_tempo, base_prob=0.20)
        self.assertLess(adjusted, 0.20)

    def test_unknown_returns_base(self):
        tempo = race_tempo_simulation([])
        unk = PaceStyle()
        self.assertEqual(pace_adjusted_topn(unk, tempo, 0.30), 0.30)


# ----- DRIFT METRICS -------------------------------------------------------
class TestDriftMetrics(unittest.TestCase):
    def test_too_few_snapshots(self):
        m = compute_drift_metrics([10.0])
        self.assertEqual(m.n_snapshots, 1)
        self.assertIsNone(m.abs_drift)

    def test_simple_drift(self):
        m = compute_drift_metrics([10.0, 11.0, 12.0, 13.0])
        self.assertAlmostEqual(m.abs_drift, 3.0)
        self.assertAlmostEqual(m.rel_drift, 0.30, places=2)
        self.assertEqual(m.direction_consistency, 1.0)
        self.assertTrue(m.is_steam)

    def test_volatile_pattern(self):
        m = compute_drift_metrics([10.0, 14.0, 9.0, 13.0, 10.0])
        self.assertIsNotNone(m.volatility)
        self.assertGreater(m.volatility, 3.0)

    def test_drift_down(self):
        m = compute_drift_metrics([20.0, 18.0, 15.0, 13.0, 11.0])
        self.assertLess(m.rel_drift, -0.4)
        self.assertTrue(m.is_drift_down)


class TestMarketClassification(unittest.TestCase):
    def test_steam(self):
        m = compute_drift_metrics([5.0, 7.0, 9.0, 11.0])
        self.assertEqual(classify_market_move(m), "steam")

    def test_drift_down(self):
        m = compute_drift_metrics([30.0, 25.0, 20.0, 15.0])
        self.assertEqual(classify_market_move(m), "drift_down")

    def test_stable(self):
        m = compute_drift_metrics([10.0, 10.2, 10.1, 10.0])
        self.assertEqual(classify_market_move(m), "stable")

    def test_unknown(self):
        m = compute_drift_metrics([])
        self.assertEqual(classify_market_move(m), "unknown")


class TestConfidence(unittest.TestCase):
    def test_low_vol_full_confidence(self):
        self.assertAlmostEqual(confidence_from_volatility(0.5), 1.0)

    def test_high_vol_reduced(self):
        c = confidence_from_volatility(5.0)
        self.assertLess(c, 0.7)

    def test_none(self):
        self.assertEqual(confidence_from_volatility(None, 0.8), 0.8)


class TestSteamAdvantage(unittest.TestCase):
    def test_steam_gives_boost(self):
        m = compute_drift_metrics([5.0, 7.0, 9.0, 11.0])
        adv = steam_move_advantage(m)
        self.assertGreater(adv, 0)

    def test_no_steam_no_boost(self):
        m = compute_drift_metrics([10.0, 10.1, 10.0, 9.9])
        adv = steam_move_advantage(m)
        self.assertEqual(adv, 0.0)


class TestConvergence(unittest.TestCase):
    def test_convergence(self):
        # Top atlar up, alt atlar down → convergence
        ms = [
            compute_drift_metrics([10.0, 12.0, 14.0]),  # up
            compute_drift_metrics([8.0, 10.0, 12.0]),   # up
            compute_drift_metrics([15.0, 13.0, 11.0]),  # down
            compute_drift_metrics([12.0, 10.0, 8.0]),   # down
        ]
        c = crowd_convergence_score(ms)
        self.assertGreater(c, 0.2)

    def test_empty(self):
        self.assertEqual(crowd_convergence_score([]), 0.0)


if __name__ == "__main__":
    unittest.main()
