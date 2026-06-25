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


class TestUnifiedPicksBuilder(unittest.TestCase):
    """Verify the new unified picks list combines shadow + SiB correctly."""

    def test_picks_combine_kinds(self):
        from top4.dashboard_api import _extract_unified_picks
        shadow_rows = [{
            "hippodrome": "İstanbul", "race_id": "İstanbul_3",
            "race_label": "İstanbul 3. koşu", "race_time": "15:30",
            "recommended_mode": "BALANCED", "confidence": "MEDIUM",
            "outcome": {"status": "pending"},
            "bankers": [4], "candidate_set": [4, 2, 7, 9, 1],
            "horses": [
                {"horse_no": 4, "horse_name": "ATIM", "role": "BANKER",
                 "p_top4_cal": 0.78, "agf_now": 32.0, "mp": 0.45},
                {"horse_no": 7, "horse_name": "RUZGAR", "role": "SPREAD",
                 "value_tag": "DEĞER", "value_gap_pct": 22,
                 "agf_now": 5.0, "mp": 0.27},
                {"horse_no": 1, "horse_name": "SEFA", "role": "AVOID",
                 "agf_now": 35.0, "mp": 0.05},
            ],
        }]
        sib_rows = [{
            "tier": "DIAMOND", "hippo": "İstanbul", "race_no": 5,
            "race_time": "16:30", "horse_no": 1, "horse_name": "KOŞAR",
            "agf": 35.0, "mp": 0.42,
            "outcome": {"status": "graded", "won": True},
        }]
        picks = _extract_unified_picks(shadow_rows, sib_rows)
        kinds = [p["kind"] for p in picks]
        # Order: banker, value, avoid (banker comes first; SiB DIAMOND = banker)
        self.assertIn("banker", kinds)
        self.assertIn("value", kinds)
        self.assertIn("avoid", kinds)
        # Banker count: 1 shadow + 1 SiB DIAMOND = 2
        self.assertEqual(kinds.count("banker"), 2)

    def test_no_bet_collapses_to_single_row(self):
        from top4.dashboard_api import _extract_unified_picks
        shadow_rows = [{
            "hippodrome": "X", "race_label": "X 1. koşu",
            "race_id": "X_1", "recommended_mode": "NO_BET",
            "horses": [],
        }]
        picks = _extract_unified_picks(shadow_rows, [])
        self.assertEqual(len(picks), 1)
        self.assertEqual(picks[0]["kind"], "no_bet")
        self.assertIsNone(picks[0]["horse_no"])

    def test_outcome_won_marked(self):
        from top4.dashboard_api import _extract_unified_picks
        shadow_rows = [{
            "hippodrome": "X", "race_label": "X 1. koşu",
            "race_id": "X_1", "recommended_mode": "BALANCED",
            "outcome": {"status": "graded", "winner": 4, "top4_actual": [4, 7, 1, 2]},
            "horses": [
                {"horse_no": 4, "horse_name": "ATIM", "role": "BANKER",
                 "p_top4_cal": 0.7, "agf_now": 30.0, "mp": 0.4},
            ],
        }]
        picks = _extract_unified_picks(shadow_rows, [])
        self.assertEqual(len(picks), 1)
        self.assertTrue(picks[0]["outcome"]["won"])

    def test_daily_stats_shape(self):
        from top4.dashboard_api import (
            _build_daily_stats, _extract_unified_picks,
        )
        shadow = [{
            "hippodrome": "X", "race_label": "X 1. koşu",
            "race_id": "X_1", "recommended_mode": "NO_BET",
            "horses": [],
        }]
        picks = _extract_unified_picks(shadow, [])
        s = _build_daily_stats(shadow, [], picks)
        for k in ("races", "picks", "results_graded", "no_bet",
                  "banker_count", "value_count", "avoid_count",
                  "won", "lost", "pending"):
            self.assertIn(k, s)


class TestRacesView(unittest.TestCase):
    """Race-by-race view — 1 row per race, multi-pick combined."""

    def test_one_row_per_race(self):
        from top4.dashboard_api import _build_races_view
        shadow = [{
            "hippodrome": "Elazığ", "race_id": "Elazığ_2",
            "race_label": "Elazığ 2. koşu", "race_time": "15:30",
            "field_size": 12, "recommended_mode": "BALANCED",
            "confidence": "MEDIUM",
            "outcome": {"status": "pending"},
            "horses": [
                {"horse_no": 2, "horse_name": "KING", "role": "BANKER",
                 "p_top4_cal": 0.85, "agf_now": 45, "mp": 0.30},
                {"horse_no": 1, "horse_name": "ETIQUETTE", "role": "BANKER",
                 "p_top4_cal": 0.74, "agf_now": 39, "mp": 0.28},
                {"horse_no": 8, "horse_name": "LORD", "role": "CHAOS",
                 "agf_now": 1, "mp": 0.05},
                {"horse_no": 6, "horse_name": "INFERNO", "role": "CHAOS",
                 "agf_now": 1.4, "mp": 0.06},
            ],
        }]
        races = _build_races_view(shadow, [])
        # 4 picks → 1 race row
        self.assertEqual(len(races), 1)
        r = races[0]
        self.assertEqual(r["hippo"], "Elazığ")
        self.assertEqual(r["race_no"], 2)
        self.assertEqual(len(r["main_picks"]), 2)  # 2 BANKER
        self.assertEqual(len(r["other_picks"]), 2)  # 2 CHAOS
        self.assertIn("⭐", r["headline"])

    def test_no_bet_race_collapses(self):
        from top4.dashboard_api import _build_races_view
        shadow = [{
            "hippodrome": "X", "race_id": "X_1",
            "race_label": "X 1. koşu",
            "recommended_mode": "NO_BET", "confidence": "CHAOS",
            "horses": [],
        }]
        races = _build_races_view(shadow, [])
        self.assertEqual(len(races), 1)
        self.assertIn("PAS", races[0]["headline"])

    def test_sib_picks_attach_to_same_race(self):
        from top4.dashboard_api import _build_races_view
        shadow = [{
            "hippodrome": "İstanbul", "race_id": "İstanbul_3",
            "race_label": "İstanbul 3. koşu",
            "recommended_mode": "BALANCED",
            "outcome": {"status": "pending"},
            "horses": [
                {"horse_no": 4, "horse_name": "ATIM", "role": "BANKER",
                 "p_top4_cal": 0.7, "agf_now": 30, "mp": 0.4},
            ],
        }]
        sib = [{
            "tier": "DIAMOND", "hippo": "İstanbul", "race_no": 3,
            "horse_no": 7, "horse_name": "RUZGAR",
            "agf": 8, "mp": 0.3,
            "outcome": {"status": "pending"},
        }]
        races = _build_races_view(shadow, sib)
        self.assertEqual(len(races), 1)
        # Shadow BANKER #4 + SiB DIAMOND #7 = 2 main picks
        self.assertEqual(len(races[0]["main_picks"]), 2)


class TestTopPicks(unittest.TestCase):
    """Top K picks builder — 'BUGÜN EN GÜÇLÜ 5' view."""

    def _race(self, picks):
        return {
            "hippo": "X", "race_no": 1, "race_time": "15:00",
            "field_size": 10, "mode": "BALANCED",
            "main_picks": picks,
            "other_picks": [],
            "outcome": {"status": "pending"},
        }

    def test_banker_priority(self):
        from top4.dashboard_api import _build_top_picks
        races = [self._race([
            {"kind": "value", "horse_no": 7, "horse_name": "VAL",
             "mp": 0.3, "agf": 5, "label": "💎 Değer", "detail": "+10pp"},
            {"kind": "banker", "horse_no": 4, "horse_name": "BANK",
             "mp": 0.4, "agf": 30, "label": "⭐ Ana At", "detail": ""},
        ])]
        top = _build_top_picks(races, k=5)
        # Banker first
        self.assertEqual(top[0]["kind"], "banker")
        self.assertEqual(top[0]["rank"], 1)

    def test_k_limit(self):
        from top4.dashboard_api import _build_top_picks
        races = [self._race([
            {"kind": "banker", "horse_no": i, "horse_name": "H" + str(i),
             "mp": 0.5 - i * 0.01, "agf": 30, "label": "⭐", "detail": ""}
            for i in range(1, 12)
        ])]
        top = _build_top_picks(races, k=5)
        self.assertEqual(len(top), 5)

    def test_value_gap_in_score(self):
        from top4.dashboard_api import _build_top_picks
        races = [self._race([
            {"kind": "value", "horse_no": 1, "horse_name": "A",
             "mp": 0.2, "agf": 5, "label": "💎", "detail": "+5pp"},
            {"kind": "value", "horse_no": 2, "horse_name": "B",
             "mp": 0.2, "agf": 5, "label": "💎", "detail": "+20pp"},
        ])]
        top = _build_top_picks(races, k=5)
        # Higher gap (B) ranks above lower gap (A)
        self.assertEqual(top[0]["horse_no"], 2)


class TestTopTraps(unittest.TestCase):
    def test_avoid_ranked_by_agf(self):
        from top4.dashboard_api import _build_top_traps
        races = [
            {"hippo": "X", "race_no": 1, "race_time": "14:00",
             "field_size": 10, "mode": "BALANCED",
             "main_picks": [],
             "other_picks": [
                {"kind": "avoid", "horse_no": 1, "horse_name": "A",
                 "agf": 20, "mp": 0.05},
                {"kind": "avoid", "horse_no": 2, "horse_name": "B",
                 "agf": 35, "mp": 0.04},
                {"kind": "chaos", "horse_no": 3, "horse_name": "C",
                 "agf": 1},
             ],
             "outcome": {}},
        ]
        traps = _build_top_traps(races, k=3)
        self.assertEqual(len(traps), 2)  # 2 avoid only
        self.assertEqual(traps[0]["horse_no"], 2)  # higher AGF first
