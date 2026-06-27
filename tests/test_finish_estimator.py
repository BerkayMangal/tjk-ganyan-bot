"""Finish estimator tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.finish_estimator import (
    class_baseline_time, enrich_history, enrich_record_with_finish,
    estimate_finish_rank, time_to_seconds,
)


class TestTimeToSeconds(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(time_to_seconds("1.55.30"), 115.30)
        self.assertAlmostEqual(time_to_seconds("2.16.71"), 136.71)

    def test_colon(self):
        self.assertAlmostEqual(time_to_seconds("1:33.05"), 93.05)

    def test_invalid(self):
        self.assertIsNone(time_to_seconds(""))
        self.assertIsNone(time_to_seconds(None))
        self.assertIsNone(time_to_seconds("garbage"))


class TestBaselineTime(unittest.TestCase):
    def test_g1_1600(self):
        # ~93 sec for G1 1600m
        t = class_baseline_time(100.0, 1600)
        self.assertAlmostEqual(t, 93.0, places=1)

    def test_maiden_1600(self):
        # ~105 sec
        t = class_baseline_time(20.0, 1600)
        self.assertAlmostEqual(t, 105.0, places=1)

    def test_scale_distance(self):
        # 2400m should be ~1.5x 1600m
        t_1600 = class_baseline_time(80.0, 1600)
        t_2400 = class_baseline_time(80.0, 2400)
        self.assertAlmostEqual(t_2400 / t_1600, 1.5, places=2)


class TestEstimateRank(unittest.TestCase):
    def test_fast_time_top1(self):
        # 90 sec vs G1 baseline ~93 → 3 sec faster → rank 1
        rank = estimate_finish_rank(90.0, 100.0, 1600)
        self.assertEqual(rank, 1)

    def test_slow_time_back(self):
        # 99 sec vs ~93 → 6 sec slower → back
        rank = estimate_finish_rank(99.0, 100.0, 1600)
        self.assertGreaterEqual(rank, 5)

    def test_no_class_fallback(self):
        rank = estimate_finish_rank(90.0, None, 1600)
        self.assertEqual(rank, 5)  # field_size 10 / 2

    def test_none_time(self):
        self.assertIsNone(estimate_finish_rank(None, 80.0, 1600))


class TestEnrich(unittest.TestCase):
    def test_record_with_kosu_cinsi(self):
        rec = {
            "kosu_cinsi": "G 1",
            "mesafe": 1600,
            "derece": "1.30.50",  # 90.5 sec (fast for G1)
        }
        enriched = enrich_record_with_finish(rec)
        self.assertEqual(enriched["finish"], 1)
        self.assertTrue(enriched.get("finish_estimated"))

    def test_already_has_finish_skipped(self):
        rec = {"finish": 3, "kosu_cinsi": "G 1", "mesafe": 1600, "derece": "1.30.00"}
        enriched = enrich_record_with_finish(rec)
        self.assertEqual(enriched["finish"], 3)  # not overwritten
        self.assertNotIn("finish_estimated", enriched)

    def test_enrich_history(self):
        history = [
            {"kosu_cinsi": "G 2", "mesafe": 2000, "derece": "2.05.00"},
            {"kosu_cinsi": "Maiden", "mesafe": 1600, "derece": "1.45.00"},
        ]
        out = enrich_history(history)
        self.assertEqual(len(out), 2)
        self.assertIsNotNone(out[0].get("finish"))
        self.assertIsNotNone(out[1].get("finish"))


if __name__ == "__main__":
    unittest.main()
