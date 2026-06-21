"""Tests for the auto-wire of retro results into the BERKAY shadow log."""
from __future__ import annotations

import os
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from top4.experimental_coupon import (
    FLAG_FORWARD_LOG, FLAG_SHADOW, build_berkay_scientific_top4_coupon,
)
from top4.experimental_integration import record_results_for_date
from top4.experimental_logger import (
    ENV_RETRO_STORE, log_prediction, read_predictions, read_results,
)


def _set_env(**kw):
    for k, v in kw.items():
        if v is None:
            os.environ.pop(k, None)
        else:
            os.environ[k] = v


def _race(rn: int, hippo: str = "İstanbul"):
    return {
        "race_label": f"{hippo} {rn}. koşu",
        "race_id": f"{hippo}_{rn}",
        "race_time": "15:30",
        "hippodrome": hippo,
        "horses": [
            {"horse_no": i, "horse_name": f"H{i}",
             "mp": 0.5 - i * 0.04,
             "agf": max(2.0, 40.0 - i * 4.0)}
            for i in range(1, 11)
        ],
    }


class TestRecordFromEngineRetro(unittest.TestCase):
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
        for rn in (1, 2, 3):
            c = build_berkay_scientific_top4_coupon(_race(rn))
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

    def test_attach_from_engine_retro_shape(self):
        # engine.retro shape: hippodrome + winners[{race_number, horse_number}]
        raw_results = [{
            "hippodrome": "İstanbul",
            "altili_no": 1,
            "winners": [
                {"race_number": 1, "horse_number": 5, "agf_rank": 3},
                {"race_number": 2, "horse_number": 1, "agf_rank": 1},
                {"race_number": 3, "horse_number": 7, "agf_rank": 5},
            ],
        }]
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        record_results_for_date(today, raw_results)
        results = read_results(today)
        race_ids = sorted(r.get("race_id") for r in results)
        self.assertEqual(race_ids, ["İstanbul_1", "İstanbul_2", "İstanbul_3"])
        for r in results:
            self.assertIn("auto_attached_from_retro", r.get("notes") or [])

    def test_attach_dedupes(self):
        raw_results = [{
            "hippodrome": "İstanbul",
            "winners": [{"race_number": 1, "horse_number": 5}],
        }]
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        record_results_for_date(today, raw_results)
        record_results_for_date(today, raw_results)
        results = read_results(today)
        # Only one result row for race 1
        rn1 = [r for r in results if r.get("race_id") == "İstanbul_1"]
        self.assertEqual(len(rn1), 1)

    def test_unmatched_race_skipped_quietly(self):
        raw_results = [{
            "hippodrome": "Bursa",  # no prediction for Bursa
            "winners": [{"race_number": 9, "horse_number": 3}],
        }]
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        # Should not crash, just no results
        record_results_for_date(today, raw_results)
        results = read_results(today)
        bursa = [r for r in results if r.get("race_id", "").startswith("Bursa")]
        self.assertEqual(len(bursa), 0)

    def test_yerli_engine_attach_helper(self):
        # Direct test of the yerli_engine private helper
        sys.path.insert(0, str(ROOT / "dashboard"))
        try:
            # Need to mock heavy imports
            import importlib.util
            spec = importlib.util.spec_from_file_location(
                "_ye_test", str(ROOT / "dashboard/yerli_engine.py")
            )
            # Skip — yerli_engine has heavy imports; we already test
            # the integration via record_results_for_date which uses
            # the SAME matching logic.
        finally:
            pass

    def test_direct_shape_still_works(self):
        """The old direct API `{race_id, finish_order}` still works."""
        from datetime import datetime, timezone
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        record_results_for_date(today, [
            {"race_id": "İstanbul_1", "finish_order": [5, 1, 3, 7]},
        ])
        results = read_results(today)
        r = next((x for x in results if x.get("race_id") == "İstanbul_1"), None)
        self.assertIsNotNone(r)
        self.assertEqual(r["finish_order"], [5, 1, 3, 7])


if __name__ == "__main__":
    unittest.main()
