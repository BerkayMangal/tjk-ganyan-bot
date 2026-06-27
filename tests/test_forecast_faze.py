"""FAZ E — Data Expansion testleri.

RacingAPI, Betfair adapters + cross-source validation.
Credential olmadan graceful no-op davranışlarını doğrular.
"""
from __future__ import annotations

import os
import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.sources.theracingapi import (
    RacingAPIClient, RacingAPIConfig, normalize_racecard, parse_form_string,
)
from forecast.sources.betfair import (
    BetfairClient, BetfairConfig, implied_probability, normalized_book,
    overround, value_edge,
)
from forecast.sources.cross_validate import (
    ConsistencyMetric, MatchResult, compare_predictions_across_sources,
    match_horse_across_sources, normalize_name,
)


# ----- RACING API ----------------------------------------------------------
class TestRacingAPIConfig(unittest.TestCase):
    def test_no_creds_not_enabled(self):
        cfg = RacingAPIConfig(username=None, password=None)
        self.assertFalse(cfg.enabled)

    def test_with_creds_enabled(self):
        cfg = RacingAPIConfig(username="u", password="p")
        self.assertTrue(cfg.enabled)

    def test_from_env(self):
        env = {"TJK_RACING_API_USER": "test",
               "TJK_RACING_API_PASS": "pw"}
        with patch.dict(os.environ, env):
            cfg = RacingAPIConfig.from_env()
            self.assertEqual(cfg.username, "test")
            self.assertTrue(cfg.enabled)


class TestRacingAPIClient(unittest.TestCase):
    def test_disabled_returns_empty(self):
        client = RacingAPIClient(
            RacingAPIConfig(username=None, password=None))
        self.assertFalse(client.enabled)
        self.assertEqual(client.racecards_today(), [])
        self.assertEqual(client.horse_results("X"), [])
        self.assertIsNone(client.horse_pro("X"))


class TestNormalizeRacecard(unittest.TestCase):
    def test_basic(self):
        card = {
            "race_id": "R1",
            "off": "15:30",
            "course": "Ascot",
            "distance": "1m",
            "going": "Good",
            "runners": [
                {"number": 1, "horse": "Frankel", "jockey": "Tom Queally"},
            ],
        }
        out = normalize_racecard(card)
        self.assertEqual(out["race_id"], "R1")
        self.assertEqual(out["hippodrome"], "Ascot")
        self.assertEqual(out["n_runners"], 1)
        self.assertEqual(out["runners"][0]["horse_name"], "Frankel")


class TestParseForm(unittest.TestCase):
    def test_dash_separated(self):
        self.assertEqual(parse_form_string("1-3-2-4-1"), [1, 3, 2, 4, 1])

    def test_concatenated(self):
        self.assertEqual(parse_form_string("13241"), [1, 3, 2, 4, 1])

    def test_empty(self):
        self.assertEqual(parse_form_string(""), [])
        self.assertEqual(parse_form_string(None), [])

    def test_ignores_zeros(self):
        # '0' means unplaced — we drop it
        self.assertEqual(parse_form_string("103"), [1, 3])


# ----- BETFAIR -------------------------------------------------------------
class TestBetfairConfig(unittest.TestCase):
    def test_no_creds_not_enabled(self):
        cfg = BetfairConfig(app_key=None, session_token=None)
        self.assertFalse(cfg.enabled)

    def test_app_key_only_not_enabled(self):
        # Requires session by default
        cfg = BetfairConfig(app_key="abc", session_token=None)
        self.assertFalse(cfg.enabled)

    def test_full_creds_enabled(self):
        cfg = BetfairConfig(app_key="abc", session_token="tok")
        self.assertTrue(cfg.enabled)


class TestBetfairClient(unittest.TestCase):
    def test_disabled_returns_empty(self):
        client = BetfairClient(
            BetfairConfig(app_key=None, session_token=None))
        self.assertFalse(client.enabled)
        self.assertEqual(client.list_event_types(), [])
        self.assertEqual(client.list_market_book([]), [])


class TestImpliedProbability(unittest.TestCase):
    def test_basic(self):
        self.assertAlmostEqual(implied_probability(2.0), 0.5)
        self.assertAlmostEqual(implied_probability(4.0), 0.25)

    def test_invalid(self):
        self.assertIsNone(implied_probability(None))
        self.assertIsNone(implied_probability(0.5))
        self.assertIsNone(implied_probability(1.0))


class TestOverround(unittest.TestCase):
    def test_fair_book(self):
        # Three horses, each at 3.0 odds → 0.333 each → 0.999
        ov = overround([1 / 3, 1 / 3, 1 / 3])
        self.assertAlmostEqual(ov, 0.999, places=2)

    def test_overround_book(self):
        # 5% overround
        ov = overround([0.4, 0.35, 0.30])
        self.assertAlmostEqual(ov, 1.05, places=2)


class TestNormalizedBook(unittest.TestCase):
    def test_sums_to_one(self):
        out = normalized_book([2.0, 3.0, 4.0])
        total = sum(p for p in out if p)
        self.assertAlmostEqual(total, 1.0, places=4)


class TestValueEdge(unittest.TestCase):
    def test_positive_edge(self):
        # Model: 50% but odds say 33% (3.0) → positive value
        edge = value_edge(0.50, 3.0)
        self.assertAlmostEqual(edge, 0.50 - 1/3, places=4)
        self.assertGreater(edge, 0)

    def test_negative_edge(self):
        edge = value_edge(0.20, 3.0)
        self.assertLess(edge, 0)

    def test_invalid(self):
        self.assertIsNone(value_edge(0.5, None))


# ----- CROSS VALIDATE ------------------------------------------------------
class TestNormalizeName(unittest.TestCase):
    def test_turkish_chars(self):
        self.assertEqual(normalize_name("BAY NALÇAKAN"), "BAY NALCAKAN")
        self.assertEqual(normalize_name("Şahin"), "SAHIN")

    def test_whitespace(self):
        self.assertEqual(normalize_name("  the   tide  "), "THE TIDE")

    def test_empty(self):
        self.assertEqual(normalize_name(""), "")
        self.assertEqual(normalize_name(None), "")


class TestMatchHorse(unittest.TestCase):
    def test_match_in_multiple_sources(self):
        sources = {
            "tjk": [{"horse_name": "BAY NALÇAKAN"}],
            "racingapi": [{"name": "BAY NALCAKAN"}],
            "betfair": [{"horse_name": "Bay Nalcakan"}],
        }
        result = match_horse_across_sources("BAY NALÇAKAN", sources)
        self.assertEqual(len(result.matches), 3)
        self.assertEqual(result.confidence, 1.0)

    def test_partial_match(self):
        sources = {
            "tjk": [{"horse_name": "RABOVO"}],
            "racingapi": [{"name": "OTHER HORSE"}],
        }
        result = match_horse_across_sources("RABOVO", sources)
        self.assertEqual(len(result.matches), 1)
        self.assertEqual(result.confidence, 0.5)

    def test_no_match(self):
        sources = {"tjk": [{"horse_name": "ABC"}]}
        result = match_horse_across_sources("XYZ", sources)
        self.assertEqual(len(result.matches), 0)
        self.assertEqual(result.confidence, 0)


class TestComparePredictions(unittest.TestCase):
    def test_high_agreement(self):
        preds = {"v7": 0.30, "racing_api": 0.32, "betfair": 0.29}
        m = compare_predictions_across_sources(preds)
        self.assertEqual(m.agreement, "high")
        self.assertEqual(m.n_sources, 3)

    def test_low_agreement(self):
        preds = {"v7": 0.30, "racing_api": 0.05, "betfair": 0.55}
        m = compare_predictions_across_sources(preds)
        self.assertEqual(m.agreement, "low")

    def test_empty(self):
        m = compare_predictions_across_sources({})
        self.assertEqual(m.n_sources, 0)
        self.assertEqual(m.agreement, "unknown")


if __name__ == "__main__":
    unittest.main()
