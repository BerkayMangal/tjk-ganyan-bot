"""V8 Training script — bootstrap initial model from available data.

Phase 1 (this script): Bootstrap V8 from FORECAST priors.
Phase 2 (later): Fit on real walk-forward backfill (production retrain)

Bootstrap workflow:
  1) Generate synthetic training data from forecast feature distributions
  2) Fit logistic + isotonic per-head
  3) Save to model/v8/trained/v8_active.json

Real training requires backfilled outcomes (currently bet_diary/event_store).
This bootstrap is a CALIBRATED PRIOR — better than uniform, ready for
swap-in once real data is wired.

Usage:
    python -m model.v8.train [--out=path] [--n-samples=2000]
"""
from __future__ import annotations

import argparse
import json
import os
import random
import sys
from pathlib import Path

# Path bootstrap
THIS = Path(__file__).resolve()
ROOT = THIS.parent.parent.parent
sys.path.insert(0, str(ROOT))

from model.v8.feature_builder import FORECAST_FEATURE_KEYS
from model.v8.model import V8Model


def gen_synthetic_sample(seed: int = None) -> dict:
    """Synthetic horse feature dict drawn from realistic distributions.

    Features NORMALIZED for logistic fit stability:
      - Glicko: (rating - 1500) / 200 → ~N(0, 1)
      - Days_since: /100 → ~[0, 4]
      - Seq strength: (s - 100) / 30 → ~N(0, 1)
      - Class slope: /5 → ~N(0, 1)
      - Finish avg: /5 → ~[0, 2]
    """
    if seed is not None:
        random.seed(seed)
    rng = random
    v7_mp = max(0.01, rng.betavariate(1.5, 6.0))
    agf = max(0.5, rng.betavariate(1.5, 6.0) * 100)
    sample = {
        "v7_model_prob": v7_mp,
        "v7_agf_value_norm": agf / 50.0,           # ~0..2
        "v7_agf_rank_norm": (rng.randint(1, 16) - 8) / 8.0,  # ~-1..1
        "v7_jockey_overall_top4": max(0.2, min(0.85,
                                               rng.gauss(0.55, 0.12))),
        "v7_jockey_cond_top4": max(0.2, min(0.85, rng.gauss(0.55, 0.15))),
        "fc_recency_w_top4_85": max(0, min(1, rng.gauss(0.35, 0.25))),
        "fc_recency_last5_top4": max(0, min(1, rng.gauss(0.40, 0.30))),
        "fc_recency_gap_recent5_career": rng.gauss(0.0, 0.20),
        "fc_traj_finish_trend": rng.gauss(0, 0.5),
        "fc_traj_class_slope_norm": rng.gauss(0, 1),       # already norm
        "fc_traj_bounce_risk": rng.choice([0.1, 0.3, 0.7]),
        "fc_recov_days_since_norm": rng.choice(
            [0.07, 0.14, 0.25, 0.45, 0.90, 1.80, 3.65]),
        "fc_recov_is_fresh": 1.0 if rng.random() < 0.30 else 0.0,
        "fc_recov_comeback_score": max(0, min(1, rng.gauss(0.20, 0.30))),
        "fc_glicko_rating_norm": rng.gauss(0, 1),           # normalized
        "fc_glicko_rd_norm": rng.gauss(0, 0.5),
        "fc_seq_strength_norm": rng.gauss(0, 1),            # normalized
        "fc_seq_top4_ewma": max(0, min(1, rng.gauss(0.40, 0.25))),
        "fc_seq_finish_avg_norm": max(0.2, rng.gauss(0.9, 0.36)),  # /5
    }
    return sample


def synth_label(features: dict) -> dict:
    """Synthetic top-N labels from features (all normalized)."""
    s = (
        2.50 * (features.get("v7_model_prob") or 0)
        + 1.20 * (features.get("fc_recency_w_top4_85") or 0)
        + 0.80 * (features.get("fc_glicko_rating_norm") or 0)
        + 0.60 * (features.get("fc_traj_finish_trend") or 0)
        + 0.50 * (features.get("fc_seq_strength_norm") or 0)
        + 0.30 * (features.get("v7_agf_value_norm") or 0)
        - 0.40 * (features.get("fc_recov_comeback_score") or 0)
        - 0.40 * (features.get("fc_seq_finish_avg_norm") or 0)
    )
    # logistic threshold for each head
    import math
    def sig(z): return 1.0 / (1.0 + math.exp(-z))
    p_top1 = sig(s * 3.5 - 2.0)
    p_top2 = sig(s * 3.0 - 1.2)
    p_top3 = sig(s * 2.5 - 0.5)
    p_top4 = sig(s * 2.0 + 0.0)
    # Sample binary labels (Bernoulli)
    return {
        "top1": 1 if random.random() < p_top1 else 0,
        "top2": 1 if random.random() < p_top2 else 0,
        "top3": 1 if random.random() < p_top3 else 0,
        "top4": 1 if random.random() < p_top4 else 0,
    }


def fit_bootstrap_model(n_samples: int = 2000,
                         out_path: str = None,
                         seed: int = 42) -> V8Model:
    """Bootstrap V8 model on synthetic data calibrated to TJK distributions.

    Returns trained V8Model. Saves to out_path if provided.
    """
    random.seed(seed)
    X = []
    Y = {"top1": [], "top2": [], "top3": [], "top4": []}
    for _ in range(n_samples):
        feat = gen_synthetic_sample()
        labels = synth_label(feat)
        # Enforce monotonicity in synth labels
        labels["top2"] = max(labels["top1"], labels["top2"])
        labels["top3"] = max(labels["top2"], labels["top3"])
        labels["top4"] = max(labels["top3"], labels["top4"])
        X.append(feat)
        for k in ("top1", "top2", "top3", "top4"):
            Y[k].append(labels[k])

    # Feature keys: V7 pass-through + forecast keys
    feature_keys = list(set(X[0].keys()))
    feature_keys.sort()

    model = V8Model()
    model.fit(X, Y, feature_keys, lr=0.05, n_iter=300, l2=0.0005)
    model.fit_meta = {
        "bootstrap": True,
        "n_samples": n_samples,
        "seed": seed,
        "note": "Synthetic calibrated prior — replace with real backfill",
    }
    if out_path:
        os.makedirs(os.path.dirname(out_path), exist_ok=True)
        model.save(out_path)
        print(f"✓ V8 bootstrap model saved: {out_path}")
        print(f"  n_features: {len(feature_keys)}")
        print(f"  fit_n: {model.fit_n}")
    return model


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=os.path.join(
        os.path.dirname(__file__), "trained", "v8_active.json"))
    parser.add_argument("--n-samples", type=int, default=2000)
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()
    fit_bootstrap_model(args.n_samples, args.out, args.seed)


if __name__ == "__main__":
    main()
