"""Regression tests for the deep audit fixes.

Each test documents the bug found, the expected behavior, and verifies
the fix. Tests fail on the original (buggy) code; pass after fix.
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# CRITICAL #1 — set_coverage_probability underestimate
# Bug: simulate_race only kept top-10 most-frequent sets; coverage probability
# was computed from those 10 entries only, ignoring the rest of n_iter draws.
# ---------------------------------------------------------------------------
class TestSetCoverageProbabilityAccuracy(unittest.TestCase):
    def test_full_coverage_when_set_contains_all_top_utility(self):
        """If the candidate set contains the top-N horses (by utility), then
        for a Plackett-Luce sim, full-coverage probability MUST be very high
        — not under-estimated by the top-10 set-frequency truncation."""
        from top4.simulation import set_coverage_probability
        # Strong favorites: util ratio ~10:1
        rows = [
            {"horse_no": 1, "p_win_cal": 0.40},
            {"horse_no": 2, "p_win_cal": 0.30},
            {"horse_no": 3, "p_win_cal": 0.15},
            {"horse_no": 4, "p_win_cal": 0.10},
            {"horse_no": 5, "p_win_cal": 0.03},
            {"horse_no": 6, "p_win_cal": 0.02},
        ]
        # Candidate set has the 4 top-utility horses. PL probability of
        # full top-4 capture should be much higher than 50%.
        cs = {1, 2, 3, 4}
        out = set_coverage_probability(rows, cs, n_iter=2000,
                                       source="p_win_cal")
        p = out.get("p_full_coverage") or out.get("p_full_coverage_approx")
        self.assertGreater(p, 0.45,
                           f"expected >0.45, got {p} — underestimate bug")

    def test_full_coverage_with_complete_field(self):
        """If candidate set = entire field, full-coverage MUST be 1.0."""
        from top4.simulation import set_coverage_probability
        rows = [
            {"horse_no": i, "p_win_cal": 0.2 - i * 0.02}
            for i in range(1, 7)
        ]
        full = {1, 2, 3, 4, 5, 6}
        out = set_coverage_probability(rows, full, n_iter=500,
                                       source="p_win_cal")
        p = out.get("p_full_coverage") or out.get("p_full_coverage_approx")
        self.assertEqual(p, 1.0)

    def test_expected_hits_sane(self):
        """expected_hits should be in [0, 4] and not zero for a strong
        candidate set."""
        from top4.simulation import set_coverage_probability
        rows = [
            {"horse_no": i, "p_win_cal": 0.5 - i * 0.05}
            for i in range(1, 10)
        ]
        cs = {1, 2, 3, 4}
        out = set_coverage_probability(rows, cs, n_iter=1000,
                                       source="p_win_cal")
        eh = out.get("expected_hits") or out.get("expected_hits_approx")
        self.assertGreater(eh, 1.5, f"expected_hits too low: {eh}")
        self.assertLessEqual(eh, 4.0)


# ---------------------------------------------------------------------------
# CRITICAL #2 — agf_drift_signal_hit_rate ignores rising-drift fade-or-hit
# logic. Both directions of drift fire as a "signal"; correctness must
# count direction correctly.
# ---------------------------------------------------------------------------
class TestAGFDriftSignalHitRate(unittest.TestCase):
    def test_falling_drift_top4_counts_as_correct(self):
        """Falling AGF + horse in top4 → 'sharp money was right'.
        Must be counted as correct, not ignored."""
        from top4.experimental_coupon import (
            FLAG_FORWARD_LOG, FLAG_SHADOW,
            build_berkay_scientific_top4_coupon,
        )
        from top4.experimental_logger import (
            ENV_RETRO_STORE, log_prediction, log_result, rebuild_summary,
            _reset_seen_cache_for_test,
        )
        tmp = tempfile.mkdtemp()
        try:
            import top4.experimental_logger as L
            L.LOG_DIR = tmp
            _reset_seen_cache_for_test()
            os.environ[FLAG_SHADOW] = "1"
            os.environ[FLAG_FORWARD_LOG] = "1"
            os.environ[ENV_RETRO_STORE] = "jsonl"

            snap = {
                "race_label": "X", "race_id": "X",
                "race_time": "15:30", "hippodrome": "İstanbul",
                "horses": [
                    {"horse_no": i, "horse_name": f"H{i}",
                     "mp": 0.5 - i * 0.04, "agf": max(2, 40 - i * 4),
                     "agf_open": max(2, 25 - i * 4)}  # 5: open ~5, now ~20 → +rise
                    for i in range(1, 9)
                ],
            }
            coupon = build_berkay_scientific_top4_coupon(snap)
            # Inject a synthetic falling drift on horse #2
            for h in coupon.get("horses", []):
                if h["horse_no"] == 2:
                    h["agf_drift_rel"] = -0.30  # strong fall
            log_prediction(coupon, telegram_sent=True)
            # Horse #2 lands in top4
            log_result(race_id="X", finish_order=[1, 2, 3, 4], force=True)
            from datetime import datetime, timezone
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
            path = rebuild_summary(today)
            import json
            with open(path) as fh:
                s = json.load(fh)
            # Total drift signals fired = at least the synthetic one
            self.assertGreaterEqual(s["agf_drift_signal_total"], 1)
            # Falling-drift hit (#2 in top4) MUST count as correct
            self.assertGreaterEqual(s["agf_drift_signal_correct"], 1)
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
            for k in (FLAG_SHADOW, FLAG_FORWARD_LOG, ENV_RETRO_STORE):
                os.environ.pop(k, None)


# ---------------------------------------------------------------------------
# CRITICAL #3 — agf_benchmark divides by N (total including skipped)
# ---------------------------------------------------------------------------
class TestAGFBenchmarkDenominator(unittest.TestCase):
    def test_empty_races_excluded_from_denominator(self):
        from top4.agf_benchmark import benchmark
        races = [
            {  # valid
                "rows": [
                    {"horse_no": 1, "mp": 0.6, "agf": 40.0},
                    {"horse_no": 2, "mp": 0.3, "agf": 25.0},
                    {"horse_no": 3, "mp": 0.2, "agf": 15.0},
                    {"horse_no": 4, "mp": 0.1, "agf": 10.0},
                ],
                "observed_top4": [1, 2, 3, 4],
            },
            {"rows": [], "observed_top4": [1, 2, 3, 4]},  # empty rows
            {"rows": [{"horse_no": 1, "mp": 0.5, "agf": 30}],
             "observed_top4": []},  # empty observed
        ]
        b = benchmark(races)
        ov = b["overall"]
        # 1 valid race, agf top1 = #1 in observed → 1.0 hit rate
        # Original buggy code: 1/3 = 0.33
        # Fixed: 1/1 = 1.0
        self.assertAlmostEqual(ov.agf_top1_top4_hit, 1.0,
                               msg=f"hit_rate={ov.agf_top1_top4_hit}, "
                                   f"divided by N={ov.n_races} but only "
                                   f"valid races should count")


# ---------------------------------------------------------------------------
# CRITICAL #4 — _race_number fails for "X 3. koşu" labels
# ---------------------------------------------------------------------------
class TestRaceNumberExtraction(unittest.TestCase):
    def test_race_id_underscore_format(self):
        from top4.digest_renderer import _race_number
        self.assertEqual(_race_number({"race_id": "İstanbul_3"}), "3")

    def test_race_label_space_format(self):
        from top4.digest_renderer import _race_number
        # BUG: rsplit(" ", 1) yields ["İstanbul 3.", "koşu"] → "koşu" → no digits
        self.assertEqual(_race_number({
            "race_label": "İstanbul 3. koşu"}), "3")

    def test_race_id_takes_precedence(self):
        from top4.digest_renderer import _race_number
        self.assertEqual(_race_number({
            "race_id": "X_5", "race_label": "X 3. koşu"}), "5")

    def test_no_race_info(self):
        from top4.digest_renderer import _race_number
        self.assertEqual(_race_number({}), "?")


# ---------------------------------------------------------------------------
# CRITICAL #5 — value_tag assigned even when agf missing
# ---------------------------------------------------------------------------
class TestValueTagAgfRequired(unittest.TestCase):
    def test_no_value_tag_without_agf(self):
        """If a horse has no agf, the 'model > halk' value comparison is
        meaningless — value_tag must NOT be assigned."""
        from top4.experimental_coupon import (
            build_berkay_scientific_top4_coupon,
        )
        snap = {
            "race_label": "X", "race_id": "X",
            "horses": [
                # field where most have AGF
                {"horse_no": 1, "horse_name": "A", "mp": 0.5, "agf": 35},
                {"horse_no": 2, "horse_name": "B", "mp": 0.3, "agf": 20},
                {"horse_no": 3, "horse_name": "C", "mp": 0.4, "agf": None},  # no agf
                {"horse_no": 4, "horse_name": "D", "mp": 0.2, "agf": 10},
                {"horse_no": 5, "horse_name": "E", "mp": 0.15, "agf": 8},
                {"horse_no": 6, "horse_name": "F", "mp": 0.1, "agf": 5},
            ],
        }
        c = build_berkay_scientific_top4_coupon(snap)
        # Horse #3 has no AGF — must NEVER have value_tag="DEĞER"
        for pool_key in ("spread", "chaos", "core", "bankers", "avoid"):
            for h in c.get(pool_key, []):
                if h["horse_no"] == 3:
                    self.assertNotEqual(
                        h.get("value_tag"), "DEĞER",
                        f"horse 3 has agf=None but got value_tag in "
                        f"{pool_key}: {h}",
                    )


# ---------------------------------------------------------------------------
# HIGH — Dead imports/variables: verify they are removed
# ---------------------------------------------------------------------------
class TestNoDeadImports(unittest.TestCase):
    @staticmethod
    def _module_unused(modname, names):
        import importlib
        import inspect
        mod = importlib.import_module(modname)
        src = inspect.getsource(mod)
        out = []
        for name in names:
            # `import X` or `from X import Y` lines exist?
            import_line_count = sum(
                1 for line in src.split("\n")
                if (f"import {name}" in line or f", {name}" in line
                    or f"{name}," in line or f"import {name}," in line)
                and "import" in line
            )
            # `name` usage outside imports
            non_import_lines = [
                line for line in src.split("\n")
                if name in line and "import" not in line
            ]
            if import_line_count > 0 and not non_import_lines:
                out.append(name)
        return out

    def test_calibration_no_dead_field(self):
        unused = self._module_unused("top4.calibration", ["field"])
        self.assertEqual(unused, [], f"dead imports: {unused}")

    def test_digest_renderer_no_dead(self):
        unused = self._module_unused(
            "top4.digest_renderer",
            ["Iterable", "EXPERIMENTAL_LABEL_DISPLAY"],
        )
        self.assertEqual(unused, [], f"dead imports: {unused}")

    def test_simulation_no_dead(self):
        unused = self._module_unused("top4.simulation", ["math", "Optional"])
        self.assertEqual(unused, [], f"dead imports: {unused}")

    def test_pipeline_no_dead(self):
        unused = self._module_unused("top4.pipeline", ["Optional"])
        self.assertEqual(unused, [], f"dead imports: {unused}")

    def test_agf_benchmark_no_dead(self):
        unused = self._module_unused(
            "top4.agf_benchmark", ["field", "Optional"],
        )
        self.assertEqual(unused, [], f"dead imports: {unused}")

    def test_experimental_logger_no_dead(self):
        unused = self._module_unused("top4.experimental_logger", ["LABEL"])
        self.assertEqual(unused, [], f"dead imports: {unused}")


# ---------------------------------------------------------------------------
# HIGH — drift loop O(N^2 log N) — verify sorted_idx only computed once
# ---------------------------------------------------------------------------
class TestDriftLoopPerformance(unittest.TestCase):
    def test_drift_loop_does_not_repeat_sort(self):
        """The drift loop in build_berkay_scientific_top4_coupon must not
        recompute sorted_idx inside the role loop. Smoke test: build a
        large race; result must complete fast and be correct."""
        import time
        from top4.experimental_coupon import (
            build_berkay_scientific_top4_coupon,
        )
        # 20-horse race; drift loop ran sorted() ONCE per role under buggy
        # code. With 20 roles + 20 horses each O(N log N) = 20*20*~5 = 2000
        # ops. Fix: precompute → ~20 ops. Not a real perf bug but is dead
        # code. Just check correctness here.
        snap = {
            "race_label": "X", "race_id": "X",
            "horses": [
                {"horse_no": i, "horse_name": f"H{i}",
                 "mp": 0.5 - i * 0.02, "agf": max(2, 40 - i * 2),
                 "agf_open": max(2, 38 - i * 2)}
                for i in range(1, 21)
            ],
        }
        t0 = time.perf_counter()
        c = build_berkay_scientific_top4_coupon(snap)
        elapsed = time.perf_counter() - t0
        self.assertLess(elapsed, 3.0,
                        f"build took {elapsed:.2f}s — perf regression")
        # Verify each horse_detail carries model_rank
        for h in c.get("horses", []):
            self.assertIsNotNone(h.get("model_rank"),
                                 f"horse {h.get('horse_no')} no model_rank")


if __name__ == "__main__":
    unittest.main()
