"""Tests for the BERKAY DENEME RETRO digest message."""
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

from top4.digest_retro import (
    ENV_RETRO_TELEGRAM, build_retro_message, is_retro_telegram_enabled,
    safe_build_retro_message,
)
from top4.report import has_forbidden_language


SAMPLE_SUMMARY = {
    "date": "2026-06-21",
    "label": "BERKAY_BILIMSEL_DENEME_TOP4",
    "predictions": 60,
    "results": 58,
    "telegram_sent_count": 60,
    "telegram_failed_count": 0,
    "telegram_unknown_count": 0,
    "no_bet_count": 12,
    "engine_fallback_count": 60,
    "engine_error_count": 0,
    "banker_survived_count": 14,
    "candidate_set_full_top4_capture": 22,
    "small_ticket_hit_count": 5,
    "balanced_ticket_hit_count": 9,
    "wide_ticket_hit_count": 14,
    "agf_drift_signal_total": 12,
    "agf_drift_signal_correct": 7,
}


class TestRetroBuilder(unittest.TestCase):
    def test_basic_message_shape(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        self.assertIn("BERKAY DENEME RETRO", msg)
        self.assertIn("21 Haz", msg)
        self.assertIn("60 tahmin", msg)
        self.assertIn("58 sonuç", msg)
        self.assertIn("eksik 2", msg)
        self.assertIn("Ana at", msg)
        self.assertIn("14/58", msg)
        self.assertIn("Aday kümesi", msg)
        self.assertIn("22/58", msg)
        self.assertIn("Small", msg)
        self.assertIn("Balanced", msg)
        self.assertIn("Wide", msg)
        self.assertIn("PAS", msg)
        self.assertIn("12 koşu", msg)
        self.assertIn("AGF drift", msg)
        self.assertIn("7/12", msg)
        self.assertLess(len(msg), 4096)

    def test_disclaimer_present(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        self.assertIn("Deneme", msg)
        self.assertIn("Otomatik bahis", msg)

    def test_no_forbidden_language(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        self.assertEqual(has_forbidden_language(msg), [])

    def test_empty_summary_returns_empty(self):
        self.assertEqual(build_retro_message("2026-06-21", {}), "")

    def test_no_predictions_returns_empty(self):
        zero = dict(SAMPLE_SUMMARY)
        zero["predictions"] = 0
        self.assertEqual(build_retro_message("2026-06-21", zero), "")

    def test_no_results_skips_metric_lines(self):
        only_pred = {"predictions": 60, "results": 0}
        msg = build_retro_message("2026-06-21", only_pred)
        # Should still produce a message with general line, no hit metrics
        self.assertIn("60 tahmin", msg)
        self.assertNotIn("Ana at hayatta kalma", msg)

    def test_engine_fallback_note_visible(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        # Berkay'a "fitted değil, prior" notu
        self.assertIn("prior", msg.lower())

    def test_engine_error_note_visible(self):
        broken = dict(SAMPLE_SUMMARY)
        broken["engine_error_count"] = 3
        msg = build_retro_message("2026-06-21", broken)
        self.assertIn("motor hatası", msg)

    def test_telegram_partial_send_note(self):
        partial = dict(SAMPLE_SUMMARY)
        partial["telegram_sent_count"] = 50  # less than 60 predictions
        msg = build_retro_message("2026-06-21", partial)
        self.assertIn("Telegram gönderim", msg)

    def test_zero_drift_signals_omits_line(self):
        no_drift = dict(SAMPLE_SUMMARY)
        no_drift["agf_drift_signal_total"] = 0
        no_drift["agf_drift_signal_correct"] = 0
        msg = build_retro_message("2026-06-21", no_drift)
        self.assertNotIn("AGF drift sinyali", msg)

    def test_zero_no_bet_omits_line(self):
        no_pas = dict(SAMPLE_SUMMARY)
        no_pas["no_bet_count"] = 0
        msg = build_retro_message("2026-06-21", no_pas)
        self.assertNotIn("PAS verdik", msg)


class TestRetroFlag(unittest.TestCase):
    def test_default_off(self):
        os.environ.pop(ENV_RETRO_TELEGRAM, None)
        self.assertFalse(is_retro_telegram_enabled())

    def test_explicit_on(self):
        os.environ[ENV_RETRO_TELEGRAM] = "1"
        try:
            self.assertTrue(is_retro_telegram_enabled())
        finally:
            os.environ.pop(ENV_RETRO_TELEGRAM, None)


class TestRetroLoadsFromDisk(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import top4.experimental_logger as L
        self._orig = L.LOG_DIR
        L.LOG_DIR = self.tmp

    def tearDown(self):
        import top4.experimental_logger as L
        L.LOG_DIR = self._orig
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_reads_summary_from_disk(self):
        import top4.experimental_logger as L
        sp = os.path.join(L.LOG_DIR, "2026-06-21.summary.json")
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(SAMPLE_SUMMARY, fh)
        msg = build_retro_message("2026-06-21")
        self.assertIn("60 tahmin", msg)

    def test_safe_build_never_raises(self):
        # bad date string
        self.assertEqual(safe_build_retro_message("bogus-date"), "")


class TestRetroFormatting(unittest.TestCase):
    def test_pct_calculation(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        # 14/58 ≈ 24% → check %24 appears
        self.assertIn("%24", msg)
        # 22/58 ≈ 38%
        self.assertIn("%38", msg)
        # 5/58 ≈ 9%
        self.assertIn("%9", msg)
        # 9/58 ≈ 16%
        self.assertIn("%16", msg)
        # 14/58 ≈ 24% (wide)
        # already covered above

    def test_message_is_compact(self):
        msg = build_retro_message("2026-06-21", SAMPLE_SUMMARY)
        # Should be readable in a glance — under 1500 chars typical
        self.assertLess(len(msg), 1500,
                        f"retro message too long: {len(msg)} chars")


if __name__ == "__main__":
    unittest.main()
