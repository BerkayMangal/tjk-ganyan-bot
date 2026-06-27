"""V8 Backtest — walk-forward, honest, no look-ahead.

Critical safety: training never sees future data. Walk-forward folds
strictly chronological.

API
---
- `walk_forward_backtest(samples, n_folds=5)` → list of fold metrics
- `single_fold_test(train, test, feature_keys)` → dict of metrics
"""
from __future__ import annotations

from typing import Iterable, Optional

from .metrics import (
    auc_roc, brier_score, expected_calibration_error, log_loss,
    top_k_accuracy,
)
from .model import V8Model


def single_fold_test(
    train_X: list[dict],
    train_Y: dict[str, list[int]],
    test_X: list[dict],
    test_Y: dict[str, list[int]],
    feature_keys: list[str],
    lr: float = 0.05,
    n_iter: int = 100,
) -> dict:
    """Train on `train`, test on `test`. Returns metrics dict.

    Each head: brier, log_loss, ECE, AUC.
    """
    model = V8Model()
    model.fit(train_X, train_Y, feature_keys, lr=lr, n_iter=n_iter)
    out = {"n_train": len(train_X), "n_test": len(test_X), "heads": {}}
    for head_name in ("top1", "top2", "top3", "top4"):
        head = getattr(model, f"head_{head_name}")
        preds = [head.predict(x) for x in test_X]
        y_test = test_Y.get(head_name) or [0] * len(test_X)
        out["heads"][head_name] = {
            "brier": brier_score(y_test, preds),
            "log_loss": log_loss(y_test, preds),
            "ece": expected_calibration_error(y_test, preds),
            "auc": auc_roc(y_test, preds),
            "n_positives": sum(y_test),
        }
    return out


def walk_forward_backtest(
    samples: list[dict],
    feature_keys: list[str],
    n_folds: int = 5,
    label_keys: tuple = ("y_top1", "y_top2", "y_top3", "y_top4"),
    sort_key: str = "race_date",
) -> list[dict]:
    """Walk-forward backtest.

    `samples`: list of {features..., y_top1, y_top2, ..., race_date}
    Each entry chronologically sorted.

    Returns: list of fold metrics (one per fold).
    """
    if not samples:
        return []
    # Sort chronologically
    samples_sorted = sorted(samples, key=lambda s: s.get(sort_key, ""))
    n = len(samples_sorted)
    fold_size = max(1, n // (n_folds + 1))
    results = []
    for fold_idx in range(n_folds):
        train_end = fold_size * (fold_idx + 1)
        test_start = train_end
        test_end = min(n, test_start + fold_size)
        if test_end <= test_start:
            continue
        train = samples_sorted[:train_end]
        test = samples_sorted[test_start:test_end]
        train_X = [{k: v for k, v in s.items() if k in feature_keys
                    or not k.startswith("y_")} for s in train]
        test_X = [{k: v for k, v in s.items() if k in feature_keys
                   or not k.startswith("y_")} for s in test]
        train_Y = {
            label_keys[i].replace("y_", ""):
            [int(s.get(label_keys[i]) or 0) for s in train]
            for i in range(min(4, len(label_keys)))
        }
        test_Y = {
            label_keys[i].replace("y_", ""):
            [int(s.get(label_keys[i]) or 0) for s in test]
            for i in range(min(4, len(label_keys)))
        }
        metrics = single_fold_test(train_X, train_Y, test_X, test_Y,
                                    feature_keys)
        metrics["fold"] = fold_idx
        metrics["train_range"] = (
            samples_sorted[0].get(sort_key),
            samples_sorted[train_end - 1].get(sort_key) if train_end else None,
        )
        metrics["test_range"] = (
            samples_sorted[test_start].get(sort_key),
            samples_sorted[test_end - 1].get(sort_key),
        )
        results.append(metrics)
    return results


def aggregate_fold_metrics(fold_results: list[dict]) -> dict:
    """Across-folds aggregate: mean Brier, mean log_loss, mean ECE per head."""
    if not fold_results:
        return {}
    agg = {"n_folds": len(fold_results), "heads": {}}
    for head_name in ("top1", "top2", "top3", "top4"):
        briers = [f["heads"][head_name]["brier"] for f in fold_results
                   if f["heads"][head_name]["brier"] is not None]
        losses = [f["heads"][head_name]["log_loss"] for f in fold_results
                   if f["heads"][head_name]["log_loss"] is not None]
        eces = [f["heads"][head_name]["ece"] for f in fold_results
                if f["heads"][head_name]["ece"] is not None]
        aucs = [f["heads"][head_name]["auc"] for f in fold_results
                if f["heads"][head_name]["auc"] is not None]
        agg["heads"][head_name] = {
            "mean_brier": sum(briers) / len(briers) if briers else None,
            "mean_log_loss": sum(losses) / len(losses) if losses else None,
            "mean_ece": sum(eces) / len(eces) if eces else None,
            "mean_auc": sum(aucs) / len(aucs) if aucs else None,
            "n_folds_with_data": len(briers),
        }
    return agg
