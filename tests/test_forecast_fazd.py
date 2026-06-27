"""FAZ D — Causal modeling testleri."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.causal.propensity import (
    CausalEffect, average_treatment_effect, compute_propensity_score,
    estimate_causal_effect, nearest_neighbor_match,
)
from forecast.causal.counterfactual import (
    CounterfactualResult, counterfactual_probability,
    feature_importance_via_perturbation, whatif_distance_change,
    whatif_jockey_swap,
)


# ----- PROPENSITY ----------------------------------------------------------
class TestPropensityScore(unittest.TestCase):
    def test_empty_returns_empty(self):
        self.assertEqual(compute_propensity_score([], []), [])

    def test_simple_logistic(self):
        # Treatment 1 when covariate > 0
        treatments = [1, 1, 0, 0, 1, 0]
        covariates = [[2.0], [3.0], [-1.0], [-2.0], [1.5], [-0.5]]
        scores = compute_propensity_score(treatments, covariates, n_iter=500)
        self.assertEqual(len(scores), 6)
        # Higher covariate → higher propensity
        self.assertGreater(scores[0], scores[2])
        self.assertGreater(scores[1], scores[3])


class TestNearestMatch(unittest.TestCase):
    def test_matching(self):
        propensity = [0.7, 0.3, 0.8, 0.2]
        treatments = [1, 0, 1, 0]
        pairs = nearest_neighbor_match(propensity, treatments, caliper=None)
        # Treated [0, 2] matched with controls [1, 3]
        self.assertEqual(len(pairs), 2)

    def test_caliper_blocks(self):
        propensity = [0.9, 0.1]
        treatments = [1, 0]
        # Caliper too tight
        pairs = nearest_neighbor_match(propensity, treatments, caliper=0.05)
        self.assertEqual(pairs, [])

    def test_all_treated(self):
        propensity = [0.7, 0.5, 0.3]
        treatments = [1, 1, 1]
        # No controls
        pairs = nearest_neighbor_match(propensity, treatments)
        self.assertEqual(pairs, [])


class TestATE(unittest.TestCase):
    def test_positive_effect(self):
        # All treated win, all controls miss
        pairs = [(0, 1), (2, 3)]
        outcomes = [1.0, 0.0, 1.0, 0.0]
        ate = average_treatment_effect(pairs, outcomes)
        self.assertAlmostEqual(ate, 1.0)

    def test_null_effect(self):
        pairs = [(0, 1)]
        outcomes = [0.5, 0.5]
        ate = average_treatment_effect(pairs, outcomes)
        self.assertEqual(ate, 0)

    def test_empty_pairs(self):
        self.assertIsNone(average_treatment_effect([], []))


class TestEstimateCausalEffect(unittest.TestCase):
    def test_no_treatment(self):
        eff = estimate_causal_effect(
            treatments=[0, 0, 0],
            outcomes=[0, 0, 0],
            covariates=[[1], [2], [3]],
        )
        self.assertIsNone(eff.ate)
        self.assertEqual(eff.interpretation, "unknown")

    def test_clear_positive(self):
        # 4 treated horses all top4, 4 untreated all miss
        # Use loose caliper so that matching succeeds
        eff = estimate_causal_effect(
            treatments=[1, 1, 1, 1, 0, 0, 0, 0],
            outcomes=[1, 1, 1, 1, 0, 0, 0, 0],
            covariates=[[1], [1.1], [0.9], [1.2], [-1], [-0.9], [-1.1], [-1.2]],
            caliper=1.0,
        )
        self.assertIsNotNone(eff.ate)


# ----- COUNTERFACTUAL ------------------------------------------------------
def _toy_predictor(features):
    """Toy: prob = 0.5 + 0.3 * mp + 0.1 * jockey_overall_top4"""
    return min(0.99, max(0.01,
               0.5 + 0.3 * (features.get("mp") or 0)
               + 0.1 * (features.get("jockey_overall_top4") or 0)))


class TestCounterfactualProbability(unittest.TestCase):
    def test_positive_perturbation(self):
        base = {"mp": 0.2, "jockey_overall_top4": 0.5}
        result = counterfactual_probability(
            _toy_predictor, base, {"mp": 0.6}
        )
        self.assertGreater(result.counterfactual_prob, result.base_prob)
        self.assertGreater(result.delta, 0)

    def test_no_change(self):
        base = {"mp": 0.2, "jockey_overall_top4": 0.5}
        result = counterfactual_probability(
            _toy_predictor, base, {"mp": 0.2}
        )
        self.assertEqual(result.interpretation, "no change")

    def test_predictor_error_safe(self):
        bad_predictor = lambda f: 1 / 0
        # Should not raise
        result = counterfactual_probability(
            bad_predictor, {"mp": 0.2}, {"mp": 0.5}
        )
        self.assertEqual(result.base_prob, 0.5)


class TestFeatureImportance(unittest.TestCase):
    def test_multiple_values(self):
        base = {"mp": 0.2}
        results = feature_importance_via_perturbation(
            _toy_predictor, base, "mp", [0.0, 0.2, 0.4, 0.6, 0.8]
        )
        self.assertEqual(len(results), 5)
        # Monotonically increasing CF prob
        cf_probs = [r.counterfactual_prob for r in results]
        for i in range(1, len(cf_probs)):
            self.assertGreaterEqual(cf_probs[i], cf_probs[i - 1] - 0.001)


class TestJockeySwap(unittest.TestCase):
    def test_swap_to_better_jockey(self):
        base = {"mp": 0.2, "jockey_overall_top4": 0.4}
        result = whatif_jockey_swap(
            _toy_predictor, base,
            jockey_a_stats={"jockey_overall_top4": 0.4},
            jockey_b_stats={"jockey_overall_top4": 0.7},
        )
        self.assertGreater(result.counterfactual_prob, result.base_prob)

    def test_swap_to_worse_jockey(self):
        base = {"mp": 0.2, "jockey_overall_top4": 0.7}
        result = whatif_jockey_swap(
            _toy_predictor, base,
            jockey_a_stats={"jockey_overall_top4": 0.7},
            jockey_b_stats={"jockey_overall_top4": 0.4},
        )
        self.assertLess(result.counterfactual_prob, result.base_prob)


class TestDistanceChange(unittest.TestCase):
    def test_distance_perturbation(self):
        base = {"mp": 0.2, "distance": 1600}
        result = whatif_distance_change(_toy_predictor, base, 2400)
        # Toy predictor doesn't use distance — so no change expected
        self.assertEqual(result.interpretation, "no change")


if __name__ == "__main__":
    unittest.main()
