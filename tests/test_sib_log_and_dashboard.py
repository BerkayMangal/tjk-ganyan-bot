"""Tests for SiB pick log + dashboard view-model."""
from __future__ import annotations

import json
import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


SAMPLE_PAYLOAD = {
    "date": "2026-06-24",
    "diamond": [
        {"pool": "İstanbul · 1. Altılı", "hippo_base": "İstanbul",
         "first_time": "14:30", "race_time": "14:55",
         "leg": 3, "race_no": 3, "horse_no": 4, "name": "ATIM",
         "agf": 32.0, "mp": 0.45, "mult": 1.4, "field_size": 12,
         "tier": "DIAMOND", "jockey_name": "AY"},
    ],
    "altin": [
        {"pool": "İstanbul · 1. Altılı", "hippo_base": "İstanbul",
         "first_time": "14:30", "race_time": "15:30",
         "leg": 5, "race_no": 5, "horse_no": 7, "name": "RÜZGAR",
         "agf": 22.0, "mp": 0.40, "mult": 1.8, "field_size": 11,
         "tier": "ALTIN", "jockey_name": "DG"},
    ],
    "premium": [],
    "firsat": [],
    "totals": {"altin": 1, "premium": 0, "pools_scanned": 1},
}


def _set_log_dir(tmp):
    import top4.sib_log as S
    S.LOG_DIR = tmp


class TestSibLog(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import top4.sib_log as S
        self._orig = S.LOG_DIR
        S.LOG_DIR = self.tmp
        os.environ["TJK_TOP4_FORWARD_LOG"] = "1"

    def tearDown(self):
        import top4.sib_log as S
        S.LOG_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)
        os.environ.pop("TJK_TOP4_FORWARD_LOG", None)

    def test_log_then_read(self):
        from top4.sib_log import log_sib_picks, read_picks
        p = log_sib_picks(SAMPLE_PAYLOAD, telegram_sent=True)
        self.assertIsNotNone(p)
        picks = read_picks("2026-06-24")
        self.assertEqual(len(picks), 2)
        keys = {x["tier"] for x in picks}
        self.assertEqual(keys, {"DIAMOND", "ALTIN"})

    def test_idempotent_log(self):
        from top4.sib_log import log_sib_picks, read_picks
        log_sib_picks(SAMPLE_PAYLOAD, telegram_sent=True)
        log_sib_picks(SAMPLE_PAYLOAD, telegram_sent=True)
        picks = read_picks("2026-06-24")
        self.assertEqual(len(picks), 2)  # not 4 — dedupe

    def test_disabled_when_flag_off(self):
        from top4.sib_log import log_sib_picks
        os.environ.pop("TJK_TOP4_FORWARD_LOG", None)
        self.assertIsNone(log_sib_picks(SAMPLE_PAYLOAD))

    def test_attach_results_winner_match(self):
        from top4.sib_log import (
            log_sib_picks, attach_sib_results, read_results,
        )
        log_sib_picks(SAMPLE_PAYLOAD)
        raw = [{
            "hippodrome": "İstanbul",
            "winners": [
                {"race_number": 3, "horse_number": 4},   # DIAMOND won
                {"race_number": 5, "horse_number": 9},   # ALTIN lost
            ],
        }]
        status = attach_sib_results("2026-06-24", raw)
        self.assertEqual(status["attached"], 2)
        results = read_results("2026-06-24")
        self.assertEqual(len(results), 2)
        diamond = next(r for r in results if r["tier"] == "DIAMOND")
        altin = next(r for r in results if r["tier"] == "ALTIN")
        self.assertTrue(diamond["won"])
        self.assertFalse(altin["won"])
        self.assertEqual(diamond["winner_horse_no"], 4)

    def test_attach_idempotent(self):
        from top4.sib_log import (
            log_sib_picks, attach_sib_results, read_results,
        )
        log_sib_picks(SAMPLE_PAYLOAD)
        raw = [{"hippodrome": "İstanbul",
                "winners": [{"race_number": 3, "horse_number": 4}]}]
        attach_sib_results("2026-06-24", raw)
        attach_sib_results("2026-06-24", raw)
        results = read_results("2026-06-24")
        self.assertEqual(len(results), 1)

    def test_summary_aggregates(self):
        from top4.sib_log import (
            log_sib_picks, attach_sib_results, load_summary,
        )
        log_sib_picks(SAMPLE_PAYLOAD)
        raw = [{
            "hippodrome": "İstanbul",
            "winners": [
                {"race_number": 3, "horse_number": 4},   # DIAMOND won
                {"race_number": 5, "horse_number": 9},   # ALTIN lost
            ],
        }]
        attach_sib_results("2026-06-24", raw)
        s = load_summary("2026-06-24")
        self.assertEqual(s["picks_total"], 2)
        self.assertEqual(s["results_total"], 2)
        self.assertEqual(s["by_tier_total"]["DIAMOND"], 1)
        self.assertEqual(s["by_tier_won"]["DIAMOND"], 1)
        self.assertEqual(s["win_rate_by_tier"]["DIAMOND"], 1.0)
        self.assertEqual(s["win_rate_by_tier"]["ALTIN"], 0.0)

    def test_fuzzy_hippo_match(self):
        """`İstanbul` vs `İstanbul Hipodromu` should match."""
        from top4.sib_log import attach_sib_results, log_sib_picks
        # Payload uses 'İstanbul'; results use 'İstanbul Hipodromu'.
        log_sib_picks(SAMPLE_PAYLOAD)
        raw = [{"hippodrome": "İstanbul Hipodromu",
                "winners": [{"race_number": 3, "horse_number": 4}]}]
        status = attach_sib_results("2026-06-24", raw)
        self.assertEqual(status["attached"], 1)


class TestDashboardAPI(unittest.TestCase):
    def setUp(self):
        self.tmp_shadow = tempfile.mkdtemp()
        self.tmp_sib = tempfile.mkdtemp()
        import top4.experimental_logger as L
        import top4.sib_log as S
        self._orig_shadow = L.LOG_DIR
        self._orig_sib = S.LOG_DIR
        L.LOG_DIR = self.tmp_shadow
        S.LOG_DIR = self.tmp_sib
        L._reset_seen_cache_for_test()
        os.environ["TJK_TOP4_SHADOW"] = "1"
        os.environ["TJK_TOP4_FORWARD_LOG"] = "1"
        os.environ["TJK_TOP4_BERKAY_SHADOW"] = "1"

    def tearDown(self):
        import top4.experimental_logger as L
        import top4.sib_log as S
        L.LOG_DIR = self._orig_shadow
        S.LOG_DIR = self._orig_sib
        L._reset_seen_cache_for_test()
        shutil.rmtree(self.tmp_shadow, ignore_errors=True)
        shutil.rmtree(self.tmp_sib, ignore_errors=True)
        for k in ("TJK_TOP4_SHADOW", "TJK_TOP4_FORWARD_LOG",
                  "TJK_TOP4_BERKAY_SHADOW"):
            os.environ.pop(k, None)

    def test_empty_today_view(self):
        from top4.dashboard_api import build_today_view
        v = build_today_view("2099-01-01")
        self.assertEqual(v["shadow"]["count"], 0)
        self.assertEqual(v["sib"]["count"], 0)
        self.assertIn("disclaimer", v)

    def test_today_view_includes_sib(self):
        from top4.dashboard_api import build_today_view
        from top4.sib_log import log_sib_picks
        log_sib_picks(SAMPLE_PAYLOAD, telegram_sent=True)
        v = build_today_view("2026-06-24")
        self.assertEqual(v["sib"]["count"], 2)
        tiers = {r["tier"] for r in v["sib"]["rows"]}
        self.assertEqual(tiers, {"DIAMOND", "ALTIN"})
        # All pending (no results yet)
        for r in v["sib"]["rows"]:
            self.assertEqual(r["outcome"]["status"], "pending")

    def test_today_view_after_results(self):
        from top4.dashboard_api import build_today_view
        from top4.sib_log import log_sib_picks, attach_sib_results
        log_sib_picks(SAMPLE_PAYLOAD)
        attach_sib_results("2026-06-24", [{
            "hippodrome": "İstanbul",
            "winners": [
                {"race_number": 3, "horse_number": 4},  # DIAMOND wins
                {"race_number": 5, "horse_number": 9},  # ALTIN loses
            ],
        }])
        v = build_today_view("2026-06-24")
        rows = {r["tier"]: r for r in v["sib"]["rows"]}
        self.assertEqual(rows["DIAMOND"]["outcome"]["status"], "graded")
        self.assertTrue(rows["DIAMOND"]["outcome"]["won"])
        self.assertEqual(rows["ALTIN"]["outcome"]["status"], "graded")
        self.assertFalse(rows["ALTIN"]["outcome"]["won"])

    def test_history_empty(self):
        from top4.dashboard_api import build_history_view
        v = build_history_view(days=7)
        self.assertEqual(v["days_requested"], 7)

    def test_history_sane_clamp(self):
        from top4.dashboard_api import build_history_view
        v = build_history_view(days=999)
        self.assertLessEqual(v["days_requested"], 60)


if __name__ == "__main__":
    unittest.main()
