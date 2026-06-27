"""V8 Metrics — top-K accuracy, Brier, log-loss, calibration error.

Honest backtesting metric suite. Pure-Python, no scipy.

API
---
- `brier_score(y_true, y_pred)` → MSE on probabilities
- `log_loss(y_true, y_pred)` → cross-entropy
- `top_k_accuracy(probs, y_true_idx)` → top-K hit rate
- `expected_calibration_error(y_true, y_pred, n_bins=10)` → ECE
- `reliability_curve(y_true, y_pred, n_bins=10)` → (mean_pred, mean_obs) per bin
"""
from __future__ import annotations

import math
from typing import Iterable, Optional


def brier_score(y_true: list[int], y_pred: list[float]) -> Optional[float]:
    """Brier score = mean((p - y)^2). Lower is better."""
    if not y_true or len(y_true) != len(y_pred):
        return None
    return sum((p - y) ** 2 for p, y in zip(y_pred, y_true)) / len(y_true)


def log_loss(y_true: list[int], y_pred: list[float],
             eps: float = 1e-9) -> Optional[float]:
    """Binary cross-entropy. Lower is better. NaN-safe."""
    if not y_true or len(y_true) != len(y_pred):
        return None
    total = 0.0
    for p, y in zip(y_pred, y_true):
        p = max(eps, min(1.0 - eps, p))
        total -= y * math.log(p) + (1 - y) * math.log(1 - p)
    return total / len(y_true)


def top_k_accuracy(probs: list[float], k: int,
                    y_top_k_indices: set[int]) -> Optional[float]:
    """For a single race: top-K predicted indices ∩ actual top-K.

    `probs`: sorted by horse_index (0..n-1)
    `y_top_k_indices`: set of actual top-K finishers (by index)

    Returns: |predicted_topK ∩ actual_topK| / k
    """
    if not probs:
        return None
    sorted_idx = sorted(range(len(probs)), key=lambda i: -probs[i])
    pred_topk = set(sorted_idx[:k])
    hit = len(pred_topk & y_top_k_indices)
    return hit / k


def expected_calibration_error(
    y_true: list[int], y_pred: list[float], n_bins: int = 10,
) -> Optional[float]:
    """ECE: |Pr - acc| weighted by bin frequency."""
    if not y_true or len(y_true) != len(y_pred):
        return None
    bins = [[] for _ in range(n_bins)]
    for p, y in zip(y_pred, y_true):
        b = min(n_bins - 1, int(p * n_bins))
        bins[b].append((p, y))
    n = len(y_true)
    ece = 0.0
    for b in bins:
        if not b:
            continue
        mean_p = sum(p for p, _ in b) / len(b)
        mean_y = sum(y for _, y in b) / len(b)
        weight = len(b) / n
        ece += abs(mean_p - mean_y) * weight
    return ece


def reliability_curve(
    y_true: list[int], y_pred: list[float], n_bins: int = 10,
) -> list[tuple[float, float, int]]:
    """Return list of (mean_predicted, mean_observed, n_in_bin) per bin.

    Useful for plotting reliability diagrams.
    """
    bins = [[] for _ in range(n_bins)]
    for p, y in zip(y_pred, y_true):
        b = min(n_bins - 1, int(p * n_bins))
        bins[b].append((p, y))
    out = []
    for b in bins:
        if not b:
            out.append((None, None, 0))
            continue
        mean_p = sum(p for p, _ in b) / len(b)
        mean_y = sum(y for _, y in b) / len(b)
        out.append((mean_p, mean_y, len(b)))
    return out


def auc_roc(y_true: list[int], y_pred: list[float]) -> Optional[float]:
    """AUC-ROC via Mann-Whitney U formula. Pure Python.

    AUC = (sum(rank_positive) - n_pos * (n_pos + 1) / 2) /
          (n_pos * n_neg)
    """
    if not y_true or len(y_true) != len(y_pred):
        return None
    # Sort by prediction ascending, assign ranks
    pairs = sorted(zip(y_pred, y_true))
    n = len(pairs)
    ranks = list(range(1, n + 1))
    # Average ranks for ties
    i = 0
    while i < n:
        j = i
        while j < n - 1 and pairs[j][0] == pairs[j + 1][0]:
            j += 1
        if j > i:
            avg_rank = sum(ranks[i:j + 1]) / (j - i + 1)
            for k in range(i, j + 1):
                ranks[k] = avg_rank
        i = j + 1
    n_pos = sum(y for _, y in pairs)
    n_neg = n - n_pos
    if n_pos == 0 or n_neg == 0:
        return None
    sum_pos_ranks = sum(ranks[i] for i, (_, y) in enumerate(pairs) if y == 1)
    auc = (sum_pos_ranks - n_pos * (n_pos + 1) / 2) / (n_pos * n_neg)
    return auc
