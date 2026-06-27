"""FAZ B — Sequence Model testleri."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from forecast.sequence.lightweight import (
    CareerEmbedding, compare_horses, encode_career,
    top_n_probability_from_embeddings,
)
from forecast.sequence.stacking import (
    DEFAULT_WEIGHTS, StackingMeta,
)


# ----- LIGHTWEIGHT ENCODER -------------------------------------------------
class TestEncodeCareer(unittest.TestCase):
    def test_empty(self):
        emb = encode_career([])
        self.assertEqual(emb.n_records, 0)
        self.assertIsNone(emb.strength)

    def test_simple_career(self):
        records = [
            {"finish": 1, "kosu_cinsi": "G 2", "mesafe": 2000},
            {"finish": 3, "kosu_cinsi": "G 3", "mesafe": 1800},
            {"finish": 4, "kosu_cinsi": "KV-8", "mesafe": 1800},
        ]
        emb = encode_career(records)
        self.assertEqual(emb.n_records, 3)
        self.assertIsNotNone(emb.strength)
        self.assertGreater(emb.strength, 100)
        self.assertGreater(emb.top4_rate, 0.9)

    def test_strong_horse_higher_strength(self):
        strong = encode_career([
            {"finish": 1, "kosu_cinsi": "G 1", "mesafe": 2400},
            {"finish": 1, "kosu_cinsi": "G 2", "mesafe": 2200},
            {"finish": 2, "kosu_cinsi": "G 1", "mesafe": 2400},
        ])
        weak = encode_career([
            {"finish": 8, "kosu_cinsi": "Maiden", "mesafe": 1600},
            {"finish": 7, "kosu_cinsi": "ŞARTLI 5", "mesafe": 1400},
            {"finish": 9, "kosu_cinsi": "Maiden", "mesafe": 1600},
        ])
        self.assertGreater(strong.strength, weak.strength)


class TestCompareHorses(unittest.TestCase):
    def test_strong_vs_weak(self):
        strong = CareerEmbedding(strength=150.0, finish_avg=1.5,
                                  finish_std=1.0)
        weak = CareerEmbedding(strength=80.0, finish_avg=7.0,
                                finish_std=1.0)
        out = compare_horses(strong, weak)
        self.assertGreater(out.a_stronger_prob, 0.85)

    def test_equal(self):
        a = CareerEmbedding(strength=100.0, finish_avg=3.0, finish_std=1.0)
        b = CareerEmbedding(strength=100.0, finish_avg=3.0, finish_std=1.0)
        out = compare_horses(a, b)
        self.assertAlmostEqual(out.a_stronger_prob, 0.5, places=2)

    def test_missing_data(self):
        a = CareerEmbedding()
        b = CareerEmbedding()
        out = compare_horses(a, b)
        self.assertIsNone(out.a_stronger_prob)


class TestTopNProbability(unittest.TestCase):
    def test_strong_target_high_top1(self):
        target = CareerEmbedding(strength=180.0, finish_std=0.8)
        opponents = [
            CareerEmbedding(strength=80.0, finish_std=2.0) for _ in range(8)
        ]
        p = top_n_probability_from_embeddings(target, opponents,
                                              target_n=1, n_samples=1500)
        self.assertGreater(p, 0.5)

    def test_weak_target_low_top1(self):
        target = CareerEmbedding(strength=70.0, finish_std=2.0)
        opponents = [
            CareerEmbedding(strength=160.0, finish_std=1.0) for _ in range(8)
        ]
        p = top_n_probability_from_embeddings(target, opponents,
                                              target_n=1, n_samples=1500)
        self.assertLess(p, 0.1)

    def test_no_strength_returns_uniform(self):
        target = CareerEmbedding()  # all None
        opponents = [CareerEmbedding() for _ in range(4)]
        p = top_n_probability_from_embeddings(target, opponents,
                                              target_n=1, n_samples=500)
        # uniform default = 1/5 = 0.2
        self.assertAlmostEqual(p, 0.2, places=1)


# ----- STACKING META -------------------------------------------------------
class TestStackingMeta(unittest.TestCase):
    def test_default_weights_present(self):
        meta = StackingMeta()
        self.assertIn("v7_mp", meta.weights)
        self.assertIn("recency_gap", meta.weights)

    def test_predict_returns_probability(self):
        meta = StackingMeta()
        p = meta.predict({
            "v7_mp": 0.30, "strength": 120,
            "glicko_rating": 1600, "recency_gap": 0.10,
            "comeback_risk": 0.1, "trend_signal": 0.5,
        })
        self.assertGreater(p, 0.0)
        self.assertLess(p, 1.0)

    def test_higher_v7_mp_higher_prob(self):
        meta = StackingMeta()
        low = meta.predict({"v7_mp": 0.05})
        high = meta.predict({"v7_mp": 0.50})
        self.assertGreater(high, low)

    def test_positive_recency_gap_raises_prob(self):
        meta = StackingMeta()
        base = meta.predict({"v7_mp": 0.20})
        improving = meta.predict({"v7_mp": 0.20, "recency_gap": 0.30})
        self.assertGreater(improving, base)

    def test_negative_recency_gap_lowers_prob(self):
        meta = StackingMeta()
        base = meta.predict({"v7_mp": 0.20})
        declining = meta.predict({"v7_mp": 0.20, "recency_gap": -0.30})
        self.assertLess(declining, base)

    def test_predict_race(self):
        meta = StackingMeta()
        ps = meta.predict_race([
            {"v7_mp": 0.30, "strength": 130},
            {"v7_mp": 0.10, "strength": 80},
        ])
        self.assertEqual(len(ps), 2)
        self.assertGreater(ps[0], ps[1])

    def test_fit_with_data(self):
        meta = StackingMeta()
        # Synthetic: high v7_mp & positive recency → top4 hit
        X = [
            {"v7_mp": 0.40, "recency_gap": 0.20, "strength": 130},
            {"v7_mp": 0.05, "recency_gap": -0.15, "strength": 80},
            {"v7_mp": 0.35, "recency_gap": 0.15, "strength": 120},
            {"v7_mp": 0.10, "recency_gap": -0.10, "strength": 90},
        ]
        y = [1, 0, 1, 0]
        meta.fit(X, y, lr=0.1, n_iter=100)
        # Higher v7_mp pred should still be > lower
        self.assertGreater(
            meta.predict({"v7_mp": 0.40, "recency_gap": 0.20, "strength": 130}),
            meta.predict({"v7_mp": 0.05, "recency_gap": -0.15, "strength": 80}),
        )

    def test_json_roundtrip(self):
        meta = StackingMeta()
        meta.weights["v7_mp"] = 5.5
        data = meta.to_json()
        meta2 = StackingMeta.from_json(data)
        self.assertAlmostEqual(meta2.weights["v7_mp"], 5.5)


if __name__ == "__main__":
    unittest.main()
