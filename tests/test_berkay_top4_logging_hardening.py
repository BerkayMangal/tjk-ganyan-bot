"""Tests for the hardened retro logging path."""
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
    FLAG_FORWARD_LOG, FLAG_SHADOW, FLAG_TELEGRAM,
    build_berkay_scientific_top4_coupon,
)
from top4.experimental_logger import (
    ENV_RETRO_STORE, build_prediction_row, log_prediction, log_result,
    read_predictions, read_results, rebuild_summary, retro_store_mode,
)
from top4.prediction_id import make_prediction_id, make_prediction_id_for_coupon


def _mock_race_snapshot(n: int = 10, race_label: str = "TEST-1",
                        race_id: str = "TEST-1"):
    return {
        "race_label": race_label,
        "race_id": race_id,
        "race_time": "15:30",
        "hippodrome": "İstanbul",
        "horses": [
            {
                "horse_no": i,
                "horse_name": f"H{i}",
                "mp": 0.5 - i * 0.04,
                "agf": max(2.0, 40.0 - i * 4.0),
            }
            for i in range(1, n + 1)
        ],
    }


def _set_env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


class TestPredictionId(unittest.TestCase):
    def test_id_deterministic(self):
        a = make_prediction_id(
            race_id="R1", cutoff="morning",
            generated_at="2026-06-20T09:00:00+00:00",
            model_version="v7", agf_snapshot_time=None,
        )
        b = make_prediction_id(
            race_id="R1", cutoff="morning",
            generated_at="2026-06-20T09:00:55+00:00",  # same minute
            model_version="v7", agf_snapshot_time=None,
        )
        self.assertEqual(a, b)

    def test_id_changes_with_cutoff(self):
        a = make_prediction_id(
            race_id="R1", cutoff="morning",
            generated_at="2026-06-20T09:00:00+00:00",
            model_version="v7",
        )
        b = make_prediction_id(
            race_id="R1", cutoff="T-15",
            generated_at="2026-06-20T09:00:00+00:00",
            model_version="v7",
        )
        self.assertNotEqual(a, b)

    def test_id_changes_with_race(self):
        a = make_prediction_id(race_id="R1", cutoff="morning",
                               generated_at="2026-06-20T09:00:00")
        b = make_prediction_id(race_id="R2", cutoff="morning",
                               generated_at="2026-06-20T09:00:00")
        self.assertNotEqual(a, b)

    def test_id_for_coupon(self):
        c = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        pid = make_prediction_id_for_coupon(c)
        self.assertEqual(len(pid), 16)


class TestLoggingHardened(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import top4.experimental_logger as L
        self._orig_log_dir = L.LOG_DIR
        L.LOG_DIR = self.tmp
        L._reset_seen_cache_for_test()
        _set_env(**{
            FLAG_SHADOW: "1",
            FLAG_FORWARD_LOG: "1",
            ENV_RETRO_STORE: "jsonl",
        })

    def tearDown(self):
        import top4.experimental_logger as L
        L.LOG_DIR = self._orig_log_dir
        L._reset_seen_cache_for_test()
        shutil.rmtree(self.tmp, ignore_errors=True)
        _set_env(**{
            FLAG_SHADOW: None, FLAG_TELEGRAM: None,
            FLAG_FORWARD_LOG: None, ENV_RETRO_STORE: None,
        })

    def test_default_retro_store_mode_is_jsonl(self):
        _set_env(**{ENV_RETRO_STORE: None})
        self.assertEqual(retro_store_mode(), "jsonl")

    def test_retro_store_mode_invalid_falls_back_to_jsonl(self):
        _set_env(**{ENV_RETRO_STORE: "garbage"})
        self.assertEqual(retro_store_mode(), "jsonl")

    def test_prediction_row_contains_required_keys(self):
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        row = build_prediction_row(
            coupon, telegram_sent=True,
            telegram_send_error=None,
            telegram_message_id=None,
        )
        for k in (
            "event_type", "label", "prediction_id", "generated_at",
            "race_id", "race_time", "hippodrome", "field_size",
            "prediction_cutoff", "model_version",
            "feature_snapshot_hash", "agf_snapshot_time",
            "telegram_sent", "telegram_send_error",
            "telegram_message_id", "retro_store_mode", "engine_status",
        ):
            self.assertIn(k, row, f"missing {k}")
        self.assertEqual(row["telegram_sent"], True)
        self.assertEqual(len(row["prediction_id"]), 16)

    def test_jsonl_dedupe_by_prediction_id(self):
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        log_prediction(coupon, telegram_sent=True)
        log_prediction(coupon, telegram_sent=True)
        log_prediction(coupon, telegram_sent=True)
        preds = read_predictions()
        self.assertEqual(len(preds), 1)
        self.assertEqual(preds[0]["telegram_sent"], True)

    def test_log_when_telegram_off(self):
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        log_prediction(coupon, telegram_sent=False,
                       telegram_send_error="off")
        preds = read_predictions()
        self.assertEqual(len(preds), 1)
        self.assertFalse(preds[0]["telegram_sent"])

    def test_result_idempotent(self):
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        log_prediction(coupon, telegram_sent=True)
        log_result(race_id=coupon["race_id"],
                   finish_order=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        log_result(race_id=coupon["race_id"],
                   finish_order=[1, 2, 3, 4, 5, 6, 7, 8, 9, 10])
        results = read_results()
        self.assertEqual(len(results), 1)

    def test_result_matches_by_prediction_id(self):
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        log_prediction(coupon, telegram_sent=True)
        log_result(
            race_id=coupon["race_id"], finish_order=[1, 2, 3, 4],
        )
        results = read_results()
        self.assertEqual(len(results), 1)
        self.assertEqual(
            results[0]["prediction_id"],
            make_prediction_id_for_coupon(coupon),
        )

    def test_summary_includes_telegram_counts(self):
        c1 = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(race_id="R1"),
        )
        c2 = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(race_id="R2"),
        )
        log_prediction(c1, telegram_sent=True)
        log_prediction(c2, telegram_sent=False,
                       telegram_send_error="HTTP 500")
        path = rebuild_summary()
        with open(path) as fh:
            s = json.load(fh)
        self.assertEqual(s["predictions"], 2)
        self.assertEqual(s["telegram_sent_count"], 1)
        self.assertEqual(s["telegram_failed_count"], 1)
        self.assertEqual(s["telegram_unknown_count"], 0)
        self.assertEqual(s["retro_store_mode"], "jsonl")

    def test_skip_log_when_forward_log_off(self):
        _set_env(**{FLAG_FORWARD_LOG: None})
        coupon = build_berkay_scientific_top4_coupon(_mock_race_snapshot())
        self.assertIsNone(log_prediction(coupon, telegram_sent=True))


class TestDBStorageMock(unittest.TestCase):
    """Verify DB path falls back to no-op when event_store unavailable
    and never crashes."""

    def test_db_disabled_no_url(self):
        from top4.db_store import is_db_enabled
        # No TJK_MEASURE_DB_URL set
        os.environ.pop("TJK_MEASURE_DB_URL", None)
        self.assertFalse(is_db_enabled())

    def test_db_write_no_op_without_url(self):
        from top4.db_store import write_prediction, write_result
        os.environ.pop("TJK_MEASURE_DB_URL", None)
        self.assertFalse(write_prediction({"prediction_id": "abc"}))
        self.assertFalse(write_result({"prediction_id": "abc"}))


class TestChunkLoggerThreading(unittest.TestCase):
    """The scheduler path uses log_predictions_for_chunk; verify it
    threads telegram_sent correctly per coupon."""

    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import top4.experimental_logger as L
        self._orig = L.LOG_DIR
        L.LOG_DIR = self.tmp
        L._reset_seen_cache_for_test()
        _set_env(**{
            FLAG_SHADOW: "1",
            FLAG_FORWARD_LOG: "1",
            ENV_RETRO_STORE: "jsonl",
        })

    def tearDown(self):
        import top4.experimental_logger as L
        L.LOG_DIR = self._orig
        L._reset_seen_cache_for_test()
        shutil.rmtree(self.tmp, ignore_errors=True)
        _set_env(**{
            FLAG_SHADOW: None, FLAG_FORWARD_LOG: None,
            ENV_RETRO_STORE: None,
        })

    def test_chunk_logger_marks_sent(self):
        from top4.experimental_integration import log_predictions_for_chunk
        c1 = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(race_id="A"),
        )
        c2 = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(race_id="B"),
        )
        n = log_predictions_for_chunk([c1, c2], telegram_sent=True)
        self.assertEqual(n, 2)
        preds = read_predictions()
        self.assertEqual(len(preds), 2)
        self.assertTrue(all(p["telegram_sent"] for p in preds))

    def test_chunk_logger_marks_failed(self):
        from top4.experimental_integration import log_predictions_for_chunk
        c = build_berkay_scientific_top4_coupon(
            _mock_race_snapshot(race_id="X"),
        )
        log_predictions_for_chunk([c], telegram_sent=False,
                                  telegram_send_error="HTTP 502")
        preds = read_predictions()
        self.assertEqual(len(preds), 1)
        self.assertFalse(preds[0]["telegram_sent"])
        self.assertEqual(preds[0]["telegram_send_error"], "HTTP 502")


class TestIntegrityAudit(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        import top4.experimental_logger as L
        self._orig = L.LOG_DIR
        L.LOG_DIR = self.tmp
        L._reset_seen_cache_for_test()
        _set_env(**{
            FLAG_SHADOW: "1", FLAG_FORWARD_LOG: "1",
            ENV_RETRO_STORE: "jsonl",
        })
        # generate a few predictions
        for r in range(1, 4):
            c = build_berkay_scientific_top4_coupon(
                _mock_race_snapshot(race_id=f"R{r}"),
            )
            log_prediction(c, telegram_sent=True)

    def tearDown(self):
        import top4.experimental_logger as L
        L.LOG_DIR = self._orig
        L._reset_seen_cache_for_test()
        shutil.rmtree(self.tmp, ignore_errors=True)
        _set_env(**{
            FLAG_SHADOW: None, FLAG_FORWARD_LOG: None,
            ENV_RETRO_STORE: None,
        })

    def test_run_audit(self):
        from audit.check_berkay_top4_logging_integrity import run_audit
        from datetime import datetime, timezone
        a = run_audit(datetime.now(timezone.utc).strftime("%Y-%m-%d"))
        self.assertEqual(a["merged"]["predictions"], 3)
        self.assertEqual(a["merged"]["duplicate_count"], 0)
        self.assertEqual(a["merged"]["missing_result_count"], 3)
        self.assertEqual(a["jsonl"]["telegram_sent_counts"].get("true"), 3)


if __name__ == "__main__":
    unittest.main()
