"""Master orchestrator integration tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.master import forecast_horse, forecast_race, quick_summary
from forecast.glicko import GlickoLedger, GlickoRating


SAMPLE_HISTORY = [
    {"finish": 2, "date": "2026-06-20", "kosu_cinsi": "G 3", "mesafe": 2200},
    {"finish": 4, "date": "2026-05-10", "kosu_cinsi": "KV-7", "mesafe": 2000},
    {"finish": 3, "date": "2026-04-01", "kosu_cinsi": "KV-8", "mesafe": 1800},
    {"finish": 5, "date": "2026-02-15", "kosu_cinsi": "Maiden", "mesafe": 1600},
    {"finish": 8, "date": "2025-12-01", "kosu_cinsi": "Maiden", "mesafe": 1400},
]


class TestForecastHorse(unittest.TestCase):
    def test_basic_returns_all_phases(self):
        out = forecast_horse(
            "RABOVO", SAMPLE_HISTORY, ref_date="2026-06-27",
            v7_model_prob=0.07,
        )
        # All phases should produce output
        self.assertIn("faza", out)
        self.assertIn("fazb", out)
        self.assertIn("fazc_pace", out)
        self.assertIn("summary", out)
        self.assertIn("refined_probability", out)
        self.assertEqual(out["horse_name"], "RABOVO")

    def test_refined_probability_in_range(self):
        out = forecast_horse(
            "X", SAMPLE_HISTORY, v7_model_prob=0.30,
        )
        rp = out["refined_probability"]
        self.assertGreater(rp, 0.0)
        self.assertLess(rp, 1.0)

    def test_drift_data_processed(self):
        out = forecast_horse(
            "X", SAMPLE_HISTORY,
            drift_snapshots=[5.0, 7.0, 9.0, 11.0],
        )
        self.assertIn("fazc_drift", out)
        drift = out["fazc_drift"]
        self.assertEqual(drift["move_class"], "steam")
        self.assertGreater(drift["steam_advantage"], 0)

    def test_glicko_attaches(self):
        led = GlickoLedger()
        led.set("RABOVO", GlickoRating(1700, 150, 0.06))
        out = forecast_horse(
            "RABOVO", SAMPLE_HISTORY, glicko_ledger=led,
        )
        self.assertIn("glicko", out["faza"])
        self.assertAlmostEqual(out["faza"]["glicko"]["rating"], 1700)

    def test_empty_history(self):
        out = forecast_horse("UNKNOWN", [])
        self.assertEqual(out["history_n"], 0)
        # Should still produce output, not raise
        self.assertIn("refined_probability", out)


class TestForecastRace(unittest.TestCase):
    def test_race_with_multiple_horses(self):
        history_map = {
            "A": SAMPLE_HISTORY,
            "B": SAMPLE_HISTORY[:3],
        }
        horses = [
            {"horse_name": "A", "horse_no": 1, "model_prob": 0.30},
            {"horse_name": "B", "horse_no": 2, "model_prob": 0.10},
        ]
        out = forecast_race(
            horses, history_lookup=lambda n: history_map.get(n, []),
        )
        self.assertEqual(len(out), 2)
        for forecast in out:
            self.assertIn("refined_probability", forecast)

    def test_history_lookup_returns_none(self):
        horses = [{"horse_name": "X", "model_prob": 0.2}]
        out = forecast_race(
            horses, history_lookup=lambda n: None,
        )
        self.assertEqual(len(out), 1)
        # Should not crash


class TestQuickSummary(unittest.TestCase):
    def test_summary_includes_name(self):
        out = forecast_horse("RABOVO", SAMPLE_HISTORY, v7_model_prob=0.2)
        s = quick_summary(out)
        self.assertIn("RABOVO", s)
        self.assertIn("refined", s)


if __name__ == "__main__":
    unittest.main()
