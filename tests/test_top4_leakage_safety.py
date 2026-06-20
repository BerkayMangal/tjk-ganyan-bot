"""Leakage safety unit tests.

These test the *invariants*, not just the scan. The scan in
audit/top4_leakage_audit.py is heuristic and complements these.
"""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from top4.calibration import calibrate_race
from top4.pipeline import forecast_race


class TestNoFutureLabels(unittest.TestCase):
    def test_calibration_does_not_require_finish_position(self):
        rows = [
            {"horse_no": i, "mp": 0.3 - 0.02 * i, "agf": 20.0}
            for i in range(1, 8)
        ]
        # No `finish_position`, no `payout` keys — should still succeed.
        cal = calibrate_race(rows)
        self.assertEqual(len(cal), 7)

    def test_pipeline_does_not_consume_payout_field(self):
        rows = [
            {"horse_no": i, "mp": 0.3 - 0.02 * i, "agf": 20.0,
             "payout_amount": 99999.0, "finish_position": 1}
            for i in range(1, 8)
        ]
        # The pipeline should ignore label-only fields and not crash.
        fc = forecast_race("LEAK_CHECK", rows)
        self.assertIsNotNone(fc.rendered)
        # Rendered output must not echo payout/finish numbers.
        self.assertNotIn("99999", fc.rendered)
        self.assertNotIn("finish_position", fc.rendered)


class TestForwardLogContract(unittest.TestCase):
    def test_logger_includes_timestamp_and_hash_keys(self):
        import os
        import json
        import tempfile

        os.environ["TJK_TOP4_SCIENTIFIC"] = "1"
        try:
            from dashboard.top4_forward_logger import log_forecast, LOG_DIR
            path = log_forecast(
                race_label="UNIT",
                forecast={"a": 1},
                feature_snapshot={"k": "v"},
                agf_snapshot_ts="2026-06-20T08:00:00Z",
            )
            self.assertIsNotNone(path)
            with open(path) as fh:
                last = fh.readlines()[-1]
            rec = json.loads(last)
            self.assertIn("ts_utc", rec)
            self.assertIn("feature_snapshot_hash", rec)
            self.assertIn("agf_snapshot_ts", rec)
        finally:
            os.environ.pop("TJK_TOP4_SCIENTIFIC", None)


if __name__ == "__main__":
    unittest.main()
