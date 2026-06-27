"""Propensity score matching — causal effect estimation.

Karşılaştırma: "Bu jokeyle bindiğinde top-4 oranı X. Bu jokey
olmasaydı oran ne olurdu?"

Yaklaşım:
  1) Treatment = jokey değişikliği (ya da herhangi bir intervention)
  2) Propensity = aslında "treated olma olasılığı" tahmini
  3) Match: benzer propensity'li treated ve control gözlemleri eşle
  4) Treatment effect = matched outcome farkı

Bu modül lightweight implementation — küçük dataset için yeterli.
Tam scikit-learn'lü için ileri sürüm gerek.

API
---
- `compute_propensity_score(treatment, covariates) -> list[float]`
- `nearest_neighbor_match(propensity, treatment) -> list[tuple]`
- `average_treatment_effect(matched_pairs, outcomes) -> float`
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


def _sigmoid(x: float) -> float:
    if x >= 0:
        e = math.exp(-x)
        return 1.0 / (1.0 + e)
    e = math.exp(x)
    return e / (1.0 + e)


def compute_propensity_score(
    treatments: list[int],
    covariates: list[list[float]],
    lr: float = 0.05,
    n_iter: int = 200,
) -> list[float]:
    """Logistic regression for P(treatment = 1 | covariates).

    Pure-Python SGD fit. NEVER raises.

    `treatments`: 0/1 list
    `covariates`: list of feature vectors (same length, all same len)

    Returns predicted P(treatment=1) for each sample.
    """
    if not treatments or not covariates:
        return []
    n = len(treatments)
    if len(covariates) != n:
        return []
    d = len(covariates[0]) if covariates else 0
    if d == 0:
        return [0.5] * n

    # Initialize weights
    w = [0.0] * d
    b = 0.0

    for _ in range(n_iter):
        for t, x in zip(treatments, covariates):
            if len(x) != d:
                continue
            z = b + sum(w[i] * x[i] for i in range(d))
            p = _sigmoid(z)
            err = t - p
            b += lr * err
            for i in range(d):
                w[i] += lr * err * x[i]

    # Predict
    out = []
    for x in covariates:
        if len(x) != d:
            out.append(0.5)
            continue
        z = b + sum(w[i] * x[i] for i in range(d))
        out.append(_sigmoid(z))
    return out


def nearest_neighbor_match(
    propensity: list[float],
    treatments: list[int],
    caliper: Optional[float] = 0.05,
) -> list[tuple[int, int]]:
    """Greedy 1-to-1 nearest neighbor matching by propensity score.

    Returns list of (treated_index, control_index) pairs.
    Caliper: max allowed propensity distance (skip if exceeded).

    NEVER raises.
    """
    if not propensity or len(propensity) != len(treatments):
        return []
    treated_idx = [i for i, t in enumerate(treatments) if t == 1]
    control_idx = [i for i, t in enumerate(treatments) if t == 0]
    used_controls = set()
    pairs: list[tuple[int, int]] = []
    for t_idx in treated_idx:
        best_c = None
        best_dist = float("inf")
        for c_idx in control_idx:
            if c_idx in used_controls:
                continue
            d = abs(propensity[t_idx] - propensity[c_idx])
            if d < best_dist:
                best_dist = d
                best_c = c_idx
        if best_c is not None:
            if caliper is None or best_dist <= caliper:
                pairs.append((t_idx, best_c))
                used_controls.add(best_c)
    return pairs


def average_treatment_effect(
    matched_pairs: list[tuple[int, int]],
    outcomes: list[float],
) -> Optional[float]:
    """ATE = mean(outcome_treated - outcome_control) over matched pairs.

    Returns the **causal effect estimate** of treatment on outcome.
    `outcomes` 1=top4 hit, 0=miss (or any binary outcome).

    NEVER raises. Returns None if no pairs.
    """
    if not matched_pairs:
        return None
    diffs = []
    for t_idx, c_idx in matched_pairs:
        if 0 <= t_idx < len(outcomes) and 0 <= c_idx < len(outcomes):
            diffs.append(outcomes[t_idx] - outcomes[c_idx])
    if not diffs:
        return None
    return sum(diffs) / len(diffs)


@dataclass
class CausalEffect:
    """Causal effect estimate with metadata."""
    ate: Optional[float]              # Average Treatment Effect
    n_treated: int
    n_control: int
    n_matched_pairs: int
    interpretation: str               # "positive", "negative", "null", "unknown"


def estimate_causal_effect(
    treatments: list[int],
    outcomes: list[float],
    covariates: list[list[float]],
    caliper: float = 0.05,
) -> CausalEffect:
    """Tek shot propensity score matching workflow.

    Berkay's "what if jockey X were swapped with Y" question:
      - treatments = 1 if "treated" jockey (Halis Karataş), 0 if "control"
      - outcomes = 1 if top4, 0 if not
      - covariates = horse profile features

    Returns CausalEffect with ATE estimate.

    NEVER raises.
    """
    n_t = sum(1 for t in treatments if t == 1)
    n_c = sum(1 for t in treatments if t == 0)
    if n_t == 0 or n_c == 0:
        return CausalEffect(
            ate=None, n_treated=n_t, n_control=n_c,
            n_matched_pairs=0, interpretation="unknown",
        )
    propensity = compute_propensity_score(treatments, covariates)
    pairs = nearest_neighbor_match(propensity, treatments, caliper)
    ate = average_treatment_effect(pairs, outcomes)
    if ate is None:
        interp = "unknown"
    elif ate > 0.05:
        interp = "positive"
    elif ate < -0.05:
        interp = "negative"
    else:
        interp = "null"
    return CausalEffect(
        ate=ate, n_treated=n_t, n_control=n_c,
        n_matched_pairs=len(pairs), interpretation=interp,
    )
