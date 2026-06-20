"""Core safety tests for the scientific Top-4 engine.

Run with: python3 -m unittest tests.test_top4_engine
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from top4 import scientific_layer_active, FLAG_ENV
from top4.calibration import calibrate_race, CalibratedRow
from top4.candidate_sets import (
    build_set_by_mp, build_set_by_p_top4, coverage_required_for_target,
    coverage_from_observed,
)
from top4.roles import (
    assign_roles, ROLE_BANKER, ROLE_CORE, ROLE_SPREAD, ROLE_AVOID,
)
from top4.uncertainty import evaluate, LEVEL_NO_BET, LEVEL_HIGH, LEVEL_CHAOS
from top4.no_bet_gate import decide
from top4.ticket_builder import build as build_ticket
from top4.pipeline import forecast_race
from top4.report import has_forbidden_language
from top4.agf_benchmark import safe_label, benchmark
from top4 import simulation, ev


def _mock_race(n: int = 10):
    return [
        {"horse_no": i, "mp": 0.5 - i * 0.04, "agf": max(2.0, 40.0 - i * 4.0),
         "breed": "EN" if i % 2 == 0 else "AR"}
        for i in range(1, n + 1)
    ]


class TestFeatureFlag(unittest.TestCase):
    def test_default_off(self):
        os.environ.pop(FLAG_ENV, None)
        self.assertFalse(scientific_layer_active())

    def test_on_when_set(self):
        os.environ[FLAG_ENV] = "1"
        try:
            self.assertTrue(scientific_layer_active())
        finally:
            os.environ.pop(FLAG_ENV, None)


class TestCalibration(unittest.TestCase):
    def test_probabilities_in_range(self):
        rows = _mock_race(10)
        cal = calibrate_race(rows)
        for r in cal:
            for p in (r.p_win_cal, r.p_top2_cal, r.p_top3_cal, r.p_top4_cal):
                if p is not None:
                    self.assertGreaterEqual(p, 0.0)
                    self.assertLessEqual(p, 1.0)

    def test_monotonic(self):
        cal = calibrate_race(_mock_race(10))
        for r in cal:
            if r.p_top4_cal is None:
                continue
            self.assertLessEqual(r.p_win_cal, r.p_top2_cal + 1e-9)
            self.assertLessEqual(r.p_top2_cal, r.p_top3_cal + 1e-9)
            self.assertLessEqual(r.p_top3_cal, r.p_top4_cal + 1e-9)

    def test_calibrated_not_equal_raw_mp_by_default(self):
        rows = _mock_race(10)
        cal = calibrate_race(rows)
        diffs = []
        for raw, c in zip(rows, cal):
            if c.p_top4_cal is not None:
                diffs.append(abs(c.p_top4_cal - raw["mp"]))
        self.assertGreater(max(diffs), 0.01)

    def test_empty_input(self):
        self.assertEqual(calibrate_race([]), [])


class TestCandidateSets(unittest.TestCase):
    def test_set_sizes(self):
        rows = _mock_race(10)
        for size in (4, 5, 6, 7, 8, 9, 10):
            cs = build_set_by_mp(rows, size)
            self.assertEqual(cs.size, size)
            self.assertEqual(len(cs.horse_nos), size)
            self.assertEqual(len(set(cs.horse_nos)), size)

    def test_set_by_p_top4_falls_back(self):
        rows = _mock_race(8)
        cs = build_set_by_p_top4(rows, 4)
        self.assertIn("rank", cs.method)

    def test_coverage_required(self):
        rows = _mock_race(10)
        # enrich with calibrated probs
        cal = calibrate_race(rows)
        for r, c in zip(rows, cal):
            r["p_top4_cal"] = c.p_top4_cal
        req = coverage_required_for_target(rows, target=0.8)
        self.assertGreaterEqual(req, 4)
        self.assertLessEqual(req, 12)

    def test_coverage_from_observed(self):
        d = coverage_from_observed({1, 2, 3, 4}, {1, 3, 5, 7})
        self.assertEqual(d["hit"], 2)
        self.assertTrue(d["captured_at_least_2"])
        self.assertFalse(d["captured_full"])


class TestRoles(unittest.TestCase):
    def test_favorite_low_model_signal_not_banker(self):
        # Horse 1: high AGF (favorite) but model rates it 6th → AVOID
        rows = [
            {"horse_no": 1, "mp": 0.05, "agf": 45.0, "p_top4_cal": 0.20},
            {"horse_no": 2, "mp": 0.50, "agf": 30.0, "p_top4_cal": 0.65},
            {"horse_no": 3, "mp": 0.40, "agf": 15.0, "p_top4_cal": 0.50},
            {"horse_no": 4, "mp": 0.35, "agf": 10.0, "p_top4_cal": 0.45},
            {"horse_no": 5, "mp": 0.30, "agf": 8.0, "p_top4_cal": 0.40},
            {"horse_no": 6, "mp": 0.25, "agf": 5.0, "p_top4_cal": 0.35},
        ]
        roles = assign_roles(rows, field_size=6)
        rmap = {r.horse_no: r.role for r in roles}
        self.assertNotEqual(rmap[1], ROLE_BANKER)
        self.assertEqual(rmap[1], ROLE_AVOID)

    def test_high_model_low_agf_becomes_spread_or_chaos(self):
        # Horse 9 has positive model-vs-AGF gap but low rank in field of 8
        rows = [
            {"horse_no": 1, "mp": 0.60, "agf": 50.0, "p_top4_cal": 0.70},
            {"horse_no": 2, "mp": 0.50, "agf": 35.0, "p_top4_cal": 0.55},
            {"horse_no": 3, "mp": 0.45, "agf": 25.0, "p_top4_cal": 0.45},
            {"horse_no": 4, "mp": 0.35, "agf": 15.0, "p_top4_cal": 0.35},
            {"horse_no": 5, "mp": 0.30, "agf": 10.0, "p_top4_cal": 0.30},
            {"horse_no": 9, "mp": 0.25, "agf": 4.0, "p_top4_cal": 0.20},
        ]
        roles = assign_roles(rows, field_size=6)
        rmap = {r.horse_no: r.role for r in roles}
        self.assertIn(rmap[9], {ROLE_SPREAD, "CHAOS", "NO_SIGNAL"})

    def test_at_most_two_bankers(self):
        rows = [
            {"horse_no": i, "mp": 0.55 - i * 0.001, "agf": 35.0,
             "p_top4_cal": 0.70}
            for i in range(1, 6)
        ]
        roles = assign_roles(rows, field_size=5)
        bankers = [r for r in roles if r.role == ROLE_BANKER]
        self.assertLessEqual(len(bankers), 2)

    def test_chaos_uncertainty_blocks_banker(self):
        rows = [{"horse_no": 1, "mp": 0.60, "agf": 40.0, "p_top4_cal": 0.70}]
        roles = assign_roles(rows, field_size=1, uncertainty=LEVEL_CHAOS)
        self.assertNotEqual(roles[0].role, ROLE_BANKER)


class TestUncertainty(unittest.TestCase):
    def test_large_field_required_set_triggers_no_bet(self):
        rows = [{"horse_no": i, "mp": 0.1, "agf": 6.0} for i in range(1, 18)]
        rep = evaluate(rows, required_set_size=12)
        self.assertEqual(rep.level, LEVEL_NO_BET)

    def test_small_strong_gap_is_high(self):
        rows = [
            {"horse_no": 1, "mp": 0.7, "agf": 50.0},
            {"horse_no": 2, "mp": 0.5, "agf": 25.0},
            {"horse_no": 3, "mp": 0.4, "agf": 15.0},
            {"horse_no": 4, "mp": 0.3, "agf": 10.0},
        ]
        rep = evaluate(rows, required_set_size=4)
        self.assertEqual(rep.level, LEVEL_HIGH)


class TestNoBetGate(unittest.TestCase):
    def test_no_bet_when_uncertainty_no_bet(self):
        from top4.uncertainty import UncertaintyReport
        unc = UncertaintyReport(LEVEL_NO_BET, ["test"], 12, 17, None, None)
        d = decide(unc, [])
        self.assertTrue(d.skip)
        self.assertEqual(d.mode, "no_bet")

    def test_ticket_skipped_propagates(self):
        from top4.no_bet_gate import NoBetDecision
        ticket = build_ticket(NoBetDecision(True, "no_bet", ["test"]), [])
        self.assertTrue(ticket.skip)
        self.assertEqual(ticket.horse_total, 0)


class TestPipelineSmoke(unittest.TestCase):
    def test_forecast_returns_struct(self):
        fc = forecast_race("SMOKE", _mock_race(10))
        self.assertEqual(fc.field_size, 10)
        self.assertIn("level", fc.uncertainty)
        self.assertIn("mode", fc.decision)
        self.assertIsInstance(fc.rendered, str)
        self.assertNotIn("guaranteed", fc.rendered.lower())

    def test_no_crash_on_missing_agf(self):
        rows = [{"horse_no": i, "mp": 0.3 - 0.02 * i} for i in range(1, 9)]
        fc = forecast_race("noagf", rows)
        self.assertIsNotNone(fc.rendered)


class TestForbiddenLanguage(unittest.TestCase):
    def test_detects_banned_terms(self):
        bad = "This is guaranteed insider info, free money safe profit"
        found = has_forbidden_language(bad)
        self.assertTrue(any("insider" in f for f in found))
        self.assertTrue(any("guaranteed" in f for f in found))

    def test_clean_passes(self):
        clean = "Kalibre edilmiş p_top4 tahmini, varyans yüksek olabilir."
        self.assertEqual(has_forbidden_language(clean), [])

    def test_renderer_clean(self):
        fc = forecast_race("RC", _mock_race(10))
        self.assertEqual(has_forbidden_language(fc.rendered), [])

    def test_safe_label_remap(self):
        self.assertEqual(safe_label("insider"), "sharp_money_candidate")
        self.assertEqual(safe_label("normal_field"), "normal_field")


class TestSimulation(unittest.TestCase):
    def test_simulate_race_returns_probs(self):
        sim = simulation.simulate_race(_mock_race(8), n_iter=200, seed=7)
        total = sum(sim.p_win.values())
        self.assertAlmostEqual(total, 1.0, places=5)
        for h, p in sim.p_top4.items():
            self.assertGreaterEqual(p, sim.p_top3.get(h, 0))


class TestEV(unittest.TestCase):
    def test_skew_warning_triggers(self):
        # Heavy tail: most payouts small, one extreme
        payouts = [50.0, 60.0, 55.0, 70.0, 10000.0]
        r = ev.compute(payouts=payouts, ticket_cost=10.0, hits=5, total_tickets=50)
        self.assertEqual(r.n, 50)
        self.assertTrue(r.skew_warning)
        self.assertGreater(r.mean_payout, r.median_payout)

    def test_empty_payouts(self):
        r = ev.compute(payouts=[], ticket_cost=10.0, hits=0, total_tickets=5)
        self.assertEqual(r.hit_rate, 0.0)


class TestAGFBenchmark(unittest.TestCase):
    def test_offline_benchmark(self):
        races = [
            {
                "rows": _mock_race(8),
                "observed_top4": [1, 2, 3, 4],
                "segment": {"breed": "EN"},
            }
        ]
        b = benchmark(races)
        self.assertIn("overall", b)
        self.assertEqual(b["overall"].n_races, 1)


class TestForwardLogger(unittest.TestCase):
    def test_logger_no_op_when_flag_off(self):
        os.environ.pop(FLAG_ENV, None)
        from dashboard.top4_forward_logger import log_forecast
        self.assertIsNone(log_forecast(race_label="x", forecast={"a": 1}))


if __name__ == "__main__":
    unittest.main()
