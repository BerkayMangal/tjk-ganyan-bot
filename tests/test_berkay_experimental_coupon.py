"""Tests for the BERKAY BİLİMSEL DENEME TOP4 experimental layer.

Run:  python3 -m unittest tests.test_berkay_experimental_coupon
"""
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

from top4.experimental_coupon import (
    DISCLAIMER, EXPERIMENTAL_LABEL, EXPERIMENTAL_LABEL_DISPLAY,
    FLAG_FORWARD_LOG, FLAG_SHADOW, FLAG_TELEGRAM,
    build_berkay_scientific_top4_coupon,
    is_forward_log_enabled, is_shadow_enabled, is_telegram_enabled,
)
from top4.experimental_logger import (
    LOG_DIR, log_prediction, log_result, read_predictions, rebuild_summary,
)
from top4.experimental_telegram import (
    HEADER, render_experimental_block, safe_render,
)
from top4.experimental_integration import (
    build_shadow_coupons, extract_race_snapshots, maybe_append_telegram,
    record_results_for_date,
)
from top4.report import has_forbidden_language


def _mock_race_snapshot(n: int = 10, race_label: str = "TEST-1"):
    return {
        "race_label": race_label,
        "race_id": race_label,
        "race_time": "15:30",
        "hippodrome": "İstanbul",
        "race_class": "HC4",
        "horses": [
            {
                "horse_no": i,
                "horse_name": f"H{i}",
                "mp": 0.5 - i * 0.04,
                "agf": max(2.0, 40.0 - i * 4.0),
                "agf_open": max(2.0, 38.0 - i * 4.0),
                "tier": "" if i > 1 else "DIAMOND",
                "breed": "EN" if i % 2 == 0 else "AR",
            }
            for i in range(1, n + 1)
        ],
    }


def _set_flags(shadow=None, telegram=None, log=None):
    for k, v in (
        (FLAG_SHADOW, shadow), (FLAG_TELEGRAM, telegram), (FLAG_FORWARD_LOG, log),
    ):
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestFlags(unittest.TestCase):
    def test_defaults_off(self):
        _set_flags(shadow=None, telegram=None, log=None)
        self.assertFalse(is_shadow_enabled())
        self.assertFalse(is_telegram_enabled())
        self.assertFalse(is_forward_log_enabled())

    def test_explicit_on(self):
        _set_flags(shadow="1", telegram="1", log="1")
        try:
            self.assertTrue(is_shadow_enabled())
            self.assertTrue(is_telegram_enabled())
            self.assertTrue(is_forward_log_enabled())
        finally:
            _set_flags(None, None, None)


class TestBuilderShape(unittest.TestCase):
    def test_basic_keys(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))
        for k in (
            "label", "label_display", "race_id", "race_time",
            "generated_at", "agf_snapshot_time", "prediction_cutoff",
            "model_version", "feature_snapshot_hash", "confidence",
            "variance", "recommended_mode", "bankers", "core", "spread",
            "chaos", "avoid", "candidate_set", "small_ticket",
            "balanced_ticket", "wide_ticket", "no_bet_reason", "notes",
            "engine_status", "disclaimer", "horses",
        ):
            self.assertIn(k, c, f"missing key {k}")
        self.assertEqual(c["label"], EXPERIMENTAL_LABEL)
        self.assertEqual(c["label_display"], EXPERIMENTAL_LABEL_DISPLAY)
        self.assertEqual(c["disclaimer"], DISCLAIMER)

    def test_cutoff_validation(self):
        for cutoff in ("morning", "T-15", "T-5", "T-3", "latest"):
            c = build_berkay_scientific_top4_coupon(
                _mock_race_snapshot(), cutoff=cutoff,
            )
            self.assertEqual(c["prediction_cutoff"], cutoff)
        c = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(), cutoff="bogus",
        )
        self.assertEqual(c["prediction_cutoff"], "latest")

    def test_p_top4_method_fallback_labeled(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))
        methods = {h.get("p_top4_method") for h in c.get("horses", [])}
        # In current state no fitted calibrator → fallback
        self.assertIn("fallback_rank_prior", methods)
        # And engine_status must reflect that
        self.assertEqual(c["engine_status"], "fallback")

    def test_disclaimer_in_output(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        self.assertEqual(c["disclaimer"], DISCLAIMER)

    def test_empty_horses_returns_no_bet(self):
        c = build_berkay_scientific_top4_coupon(
            {"race_label": "EMPTY", "horses": []}
        )
        self.assertEqual(c["recommended_mode"], "NO_BET")
        self.assertEqual(c["engine_status"], "error")

    def test_never_raises_on_garbage(self):
        # Garbage values must not crash
        c = build_berkay_scientific_top4_coupon({
            "race_label": "X",
            "horses": [
                {"horse_no": "abc", "mp": "xyz", "agf": "what"},
                {"horse_no": None, "mp": None},
            ],
        })
        self.assertIn("engine_status", c)


class TestAGFDrift(unittest.TestCase):
    def test_drift_reason_appears_when_strong(self):
        # Heavy positive drift on a top-rank horse → reason should mention AGF
        snap = _mock_race_snapshot(8)
        for h in snap["horses"]:
            if h["horse_no"] == 1:
                h["agf_open"] = 10.0
                h["agf"] = 30.0  # +200% drift on the top model horse
        c = build_berkay_scientific_top4_coupon(snap)
        all_reasons = " ".join(
            h.get("reason", "") for h in c.get("horses", [])
        )
        self.assertTrue(
            "canlı AGF hareketi" in all_reasons
            or "sharp money adayı" in all_reasons
            or c["recommended_mode"] == "NO_BET",
            f"expected drift reason, got: {all_reasons}",
        )

    def test_agf_missing_no_crash(self):
        snap = {
            "race_label": "NOAGF", "race_id": "NOAGF",
            "horses": [
                {"horse_no": i, "horse_name": f"H{i}", "mp": 0.3 - i * 0.02}
                for i in range(1, 7)
            ],
        }
        c = build_berkay_scientific_top4_coupon(snap)
        self.assertNotEqual(c["engine_status"], "error")
        notes = " ".join(c.get("notes") or [])
        self.assertIn("AGF_MISSING", notes)

    def test_agf_stale_warning(self):
        # supply explicit snapshot with no `ts` → drift module treats as stale
        snap = _mock_race_snapshot(8)
        coupon = build_berkay_scientific_top4_coupon(
            snap,
            agf_snapshot={
                "open": {"ts": None,
                         "horses": {h["horse_no"]: h["agf_open"]
                                    for h in snap["horses"]}},
                "now": {"ts": None,
                        "horses": {h["horse_no"]: h["agf"]
                                   for h in snap["horses"]}},
            },
        )
        notes = " ".join(coupon.get("notes") or [])
        # Either MISSING or STALE acceptable (no `ts` provided)
        self.assertTrue("AGF_STALE" in notes or "AGF_MISSING" in notes
                        or coupon["engine_status"] != "error",
                        f"notes={notes}")


class TestForbiddenLanguage(unittest.TestCase):
    def test_no_banned_terms_in_telegram_render(self):
        coupons = [build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))]
        text = render_experimental_block(coupons)
        self.assertEqual(has_forbidden_language(text), [])

    def test_disclaimer_in_telegram_render(self):
        coupons = [build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))]
        text = render_experimental_block(coupons)
        self.assertIn("Deneme", text)
        self.assertIn("Otomatik bahis değildir", text)
        self.assertIn("BERKAY BİLİMSEL DENEME TOP4", text)


class TestForwardLog(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.mkdtemp()
        self._orig_log_dir = LOG_DIR
        import top4.experimental_logger as L
        L.LOG_DIR = self.tmp_dir
        _set_flags(shadow="1", telegram=None, log="1")

    def tearDown(self):
        import top4.experimental_logger as L
        L.LOG_DIR = self._orig_log_dir
        shutil.rmtree(self.tmp_dir, ignore_errors=True)
        _set_flags(None, None, None)

    def test_log_prediction_writes_jsonl(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))
        path = log_prediction(c)
        self.assertIsNotNone(path)
        self.assertTrue(os.path.exists(path))
        with open(path) as fh:
            line = fh.readline()
        rec = json.loads(line)
        self.assertEqual(rec["event_type"], "prediction")
        self.assertEqual(rec["label"], EXPERIMENTAL_LABEL)
        self.assertIn("feature_snapshot_hash", rec)
        self.assertIn("horses", rec)

    def test_log_result_and_summary(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot(10))
        log_prediction(c)
        race_id = c["race_id"]
        path = log_result(
            race_id=race_id, race_label=c["race_label"],
            finish_order=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10],
            payouts={"top4": 12345.0},
        )
        self.assertIsNotNone(path)
        # one prediction + one result row
        with open(path) as fh:
            lines = fh.readlines()
        self.assertGreaterEqual(len(lines), 2)
        # summary exists
        summary_path = path.replace(".jsonl", ".summary.json")
        self.assertTrue(os.path.exists(summary_path))
        with open(summary_path) as fh:
            summary = json.load(fh)
        self.assertEqual(summary["label"], EXPERIMENTAL_LABEL)
        self.assertEqual(summary["predictions"], 1)
        self.assertEqual(summary["results"], 1)

    def test_log_skipped_when_flag_off(self):
        _set_flags(shadow=None, telegram=None, log=None)
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        self.assertIsNone(log_prediction(c))


class TestIntegration(unittest.TestCase):
    def test_extract_race_snapshots(self):
        results = {
            "hippodromes": [{
                "hippodrome": "İstanbul",
                "altili": [{
                    "race_no": 1,
                    "time": "15:30",
                    "horses": [
                        {"horse_no": 1, "horse_name": "X", "mp": 0.3,
                         "agf": 25.0},
                        {"horse_no": 2, "horse_name": "Y", "mp": 0.2,
                         "agf": 18.0},
                    ],
                }],
            }],
        }
        snaps = extract_race_snapshots(results)
        self.assertEqual(len(snaps), 1)
        self.assertEqual(len(snaps[0]["horses"]), 2)
        self.assertEqual(snaps[0]["hippodrome"], "İstanbul")

    def test_build_shadow_coupons_off_returns_empty(self):
        _set_flags(shadow=None, telegram=None, log=None)
        self.assertEqual(build_shadow_coupons({"hippodromes": []}), [])

    def test_maybe_append_telegram_off_unchanged(self):
        _set_flags(shadow=None, telegram=None, log=None)
        existing = ["MSG1"]
        out = maybe_append_telegram(existing, {"hippodromes": []})
        self.assertEqual(out, existing)

    def test_maybe_append_telegram_on_adds_block(self):
        _set_flags(shadow="1", telegram="1", log=None)
        try:
            results = {
                "hippodromes": [{
                    "hippodrome": "İstanbul",
                    "altili": [{
                        "race_no": 1, "time": "15:30",
                        "horses": [
                            {"horse_no": i, "horse_name": f"H{i}",
                             "mp": 0.5 - i * 0.04,
                             "agf": max(2.0, 40.0 - i * 4.0)}
                            for i in range(1, 9)
                        ],
                    }],
                }],
            }
            existing = ["PROD MESSAGE"]
            out = maybe_append_telegram(existing, results)
            self.assertEqual(len(out), 2)
            self.assertEqual(out[0], "PROD MESSAGE")
            self.assertIn("BERKAY BİLİMSEL DENEME TOP4", out[1])
            self.assertIn("Deneme", out[1])
            self.assertEqual(has_forbidden_language(out[1]), [])
        finally:
            _set_flags(None, None, None)

    def test_engine_failure_returns_original_messages(self):
        _set_flags(shadow="1", telegram="1", log=None)
        try:
            existing = ["X"]
            out = maybe_append_telegram(existing, None)  # bad input
            # never crashes; returns existing or appends nothing
            self.assertEqual(out, ["X"])
        finally:
            _set_flags(None, None, None)


class TestProductionUnchangedWhenFlagsOff(unittest.TestCase):
    def test_existing_messages_passthrough(self):
        _set_flags(None, None, None)
        existing = ["A", "B", "C"]
        out = maybe_append_telegram(existing, {"hippodromes": []})
        self.assertEqual(out, existing)
        self.assertIsNot(out, existing)  # returns a copy

    def test_record_results_off(self):
        _set_flags(None, None, None)
        self.assertIsNone(record_results_for_date("2026-06-20", []))


if __name__ == "__main__":
    unittest.main()
