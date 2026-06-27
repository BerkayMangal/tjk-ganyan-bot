"""V8 — Multi-head model + feature builder + backtest tests."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from model.v8.feature_builder import (
    FORECAST_FEATURE_KEYS, add_race_relative_features, build_horse_features,
    build_race_matrix,
)
from model.v8.model import V8Head, V8Model
from model.v8.metrics import (
    auc_roc, brier_score, expected_calibration_error, log_loss,
    reliability_curve, top_k_accuracy,
)
from model.v8.backtest import (
    aggregate_fold_metrics, single_fold_test, walk_forward_backtest,
)


# ----- FEATURE BUILDER -----------------------------------------------------
class TestFeatureBuilder(unittest.TestCase):
    def test_empty_horse(self):
        feat = build_horse_features({}, [], None)
        # Should not crash; returns dict
        self.assertIsInstance(feat, dict)

    def test_forecast_keys_present(self):
        feat = build_horse_features(
            {"horse_name": "X", "model_prob": 0.3},
            [{"finish": 1, "kosu_cinsi": "G 2", "mesafe": 2000, "date": "2026-06-01"}],
            ref_date="2026-06-27",
        )
        # At least some forecast features should be filled
        fc_keys = [k for k in feat if k.startswith("fc_")]
        self.assertGreater(len(fc_keys), 5)

    def test_v7_passthrough(self):
        horse = {
            "horse_name": "X",
            "model_prob": 0.30, "agf_value": 25.0,
            "jockey_overall_top4": 0.65,
        }
        feat = build_horse_features(horse, [], None)
        self.assertAlmostEqual(feat["v7_model_prob"], 0.30)
        self.assertAlmostEqual(feat["v7_agf_value"], 25.0)


class TestRaceMatrix(unittest.TestCase):
    def test_full_race(self):
        horses = [
            {"horse_name": "A", "model_prob": 0.30, "agf_value": 30.0},
            {"horse_name": "B", "model_prob": 0.10, "agf_value": 15.0},
        ]
        out = build_race_matrix(
            horses, history_lookup=lambda n: [],
        )
        self.assertEqual(len(out), 2)

    def test_race_relative_features_added(self):
        horses_feat = [
            {"v7_model_prob": 0.30, "v7_agf_value": 30.0,
             "horse_no": 1, "horse_name": "A"},
            {"v7_model_prob": 0.10, "v7_agf_value": 15.0,
             "horse_no": 2, "horse_name": "B"},
        ]
        out = add_race_relative_features(horses_feat)
        self.assertIn("v7_model_prob_rank", out[0])
        self.assertIn("v7_model_prob_zscore", out[0])
        # A has higher mp → rank 1
        self.assertEqual(out[0]["v7_model_prob_rank"], 1)


# ----- METRICS -------------------------------------------------------------
class TestMetrics(unittest.TestCase):
    def test_brier_perfect(self):
        self.assertAlmostEqual(brier_score([1, 0], [1.0, 0.0]), 0.0)

    def test_brier_worst(self):
        self.assertAlmostEqual(brier_score([1, 0], [0.0, 1.0]), 1.0)

    def test_log_loss(self):
        # Perfect: ~0
        v = log_loss([1, 0], [0.99, 0.01])
        self.assertLess(v, 0.05)

    def test_top_k_accuracy(self):
        # Probs sorted asc: indices [4, 3, 2, 1, 0] descending
        probs = [0.1, 0.2, 0.3, 0.4, 0.5]
        actual_top4 = {0, 1, 2, 4}
        acc = top_k_accuracy(probs, k=4, y_top_k_indices=actual_top4)
        # Top-4 by probs: [4, 3, 2, 1] → ∩ {0,1,2,4} = {1,2,4} → 3/4
        self.assertAlmostEqual(acc, 0.75)

    def test_ece_perfect_calibration(self):
        # All preds 0.5, half are 1
        y = [1, 0] * 50
        p = [0.5] * 100
        ece = expected_calibration_error(y, p, n_bins=10)
        # mean_p=0.5, mean_y=0.5 → ECE 0
        self.assertLess(ece, 0.01)

    def test_auc_perfect(self):
        y = [0, 0, 1, 1]
        p = [0.1, 0.2, 0.7, 0.8]
        self.assertAlmostEqual(auc_roc(y, p), 1.0)


# ----- V8 MODEL ------------------------------------------------------------
class TestV8Model(unittest.TestCase):
    def test_predict_default(self):
        m = V8Model()
        out = m.predict({})
        # Empty model → 0.5 (sigmoid(0))
        self.assertAlmostEqual(out["p_top1"], 0.5)
        self.assertGreaterEqual(out["p_top2"], out["p_top1"])
        self.assertGreaterEqual(out["p_top3"], out["p_top2"])
        self.assertGreaterEqual(out["p_top4"], out["p_top3"])

    def test_fit_simple(self):
        # Synthetic linearly separable
        X = [
            {"a": 5.0}, {"a": 4.0}, {"a": 3.0},
            {"a": -3.0}, {"a": -4.0}, {"a": -5.0},
        ]
        Y = {
            "top1": [1, 1, 0, 0, 0, 0],
            "top2": [1, 1, 1, 0, 0, 0],
            "top3": [1, 1, 1, 1, 0, 0],
            "top4": [1, 1, 1, 1, 1, 0],
        }
        m = V8Model()
        m.fit(X, Y, feature_keys=["a"], lr=0.1, n_iter=300)
        # High a → high p
        high = m.predict({"a": 5.0})
        low = m.predict({"a": -5.0})
        self.assertGreater(high["p_top1"], low["p_top1"])
        self.assertGreater(high["p_top4"], low["p_top4"])

    def test_monotonicity_enforced(self):
        m = V8Model()
        # Manually break monotonicity in heads → predict still enforces
        m.head_top1.intercept = 2.0
        m.head_top2.intercept = -2.0
        out = m.predict({})
        self.assertGreaterEqual(out["p_top2"], out["p_top1"])

    def test_serialize_roundtrip(self):
        m = V8Model()
        m.head_top1.weights = {"a": 1.5}
        m.head_top1.intercept = -0.5
        data = m.to_json()
        m2 = V8Model.from_json(data)
        self.assertEqual(m2.head_top1.weights["a"], 1.5)
        self.assertEqual(m2.head_top1.intercept, -0.5)


# ----- BACKTEST ------------------------------------------------------------
class TestBacktest(unittest.TestCase):
    def test_single_fold_runs(self):
        train_X = [{"a": float(i)} for i in range(20)]
        train_Y = {
            "top1": [1 if i > 10 else 0 for i in range(20)],
            "top2": [1 if i > 8 else 0 for i in range(20)],
            "top3": [1 if i > 5 else 0 for i in range(20)],
            "top4": [1 if i > 3 else 0 for i in range(20)],
        }
        test_X = [{"a": float(i)} for i in range(20, 30)]
        test_Y = {
            "top1": [1 if i > 25 else 0 for i in range(20, 30)],
            "top2": [1 if i > 23 else 0 for i in range(20, 30)],
            "top3": [1 if i > 22 else 0 for i in range(20, 30)],
            "top4": [1 if i > 21 else 0 for i in range(20, 30)],
        }
        result = single_fold_test(train_X, train_Y, test_X, test_Y,
                                   feature_keys=["a"])
        self.assertEqual(result["n_train"], 20)
        self.assertIn("brier", result["heads"]["top4"])

    def test_walk_forward_runs(self):
        samples = []
        for i in range(50):
            samples.append({
                "a": float(i % 10),
                "race_date": f"2026-01-{i + 1:02d}"[:10],
                "y_top1": 1 if (i % 10) > 7 else 0,
                "y_top2": 1 if (i % 10) > 6 else 0,
                "y_top3": 1 if (i % 10) > 5 else 0,
                "y_top4": 1 if (i % 10) > 4 else 0,
            })
        results = walk_forward_backtest(samples, feature_keys=["a"], n_folds=3)
        self.assertEqual(len(results), 3)
        agg = aggregate_fold_metrics(results)
        self.assertIn("top4", agg["heads"])


if __name__ == "__main__":
    unittest.main()
