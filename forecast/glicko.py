"""Glicko-2 Bayesian rating system for horses and jockeys.

Mark Glickman'ın 2012 paperı: A.E. Glickman (2012), "Example of the
Glicko-2 system". Standard rating volatility = 0.06, system constant
τ = 0.5 (recommended for sporadic events).

Why Glicko-2 (forecast'a katkısı):

1. **Latent ability** estimation: at'ın "gerçek gücü" μ (rating)
   tahmini, bu güce ne kadar GÜVENDİĞİMİZ σ (RD = rating deviation).
   Career averages bunu vermez — Glicko verir.

2. **Bayesian update**: her yarış sonrası rating Bayes kuralıyla
   güncellenir. Beklenmedik sonuçlar büyük güncelleme yapar.

3. **Volatility tracking**: τ (volatility) at performansının ne
   kadar tutarlı olduğunu yansıtır. Yüksek volatility = belirsiz
   gelecek tahmini.

4. **Forward-looking projection**: yarış öncesi P(top4) hesabı
   N(μ, σ²) kümülatif dağılımı ile yapılır.

Algorithm
---------
Glickman'ın orijinal Step 1-8'ini Python'a port ettik. Standard
constants (rating 1500, RD 350, vol 0.06) — at yarışında jokey
rating'leri için kullanırız. At rating'i 2000 ± 600 başlar
(daha gevşek prior).

API
---
- `GlickoRating(mu, phi, sigma)` dataclass
- `expected_top_finish(rating, opponents) -> probability`
- `update_rating(rating, race_results) -> new_rating`
- `GlickoLedger` — at × jokey × hipodrom rating defteri (persistent)
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional

# Glicko-2 constants
GLICKO2_SCALE = 173.7178   # μ scale conversion
SYSTEM_TAU = 0.5           # volatility constraint
EPSILON = 1e-6             # iteration tolerance

# Default starting rating
DEFAULT_RATING_HORSE = 1500.0
DEFAULT_RD_HORSE = 350.0
DEFAULT_VOL_HORSE = 0.06

DEFAULT_RATING_JOCKEY = 1500.0
DEFAULT_RD_JOCKEY = 350.0
DEFAULT_VOL_JOCKEY = 0.06


@dataclass
class GlickoRating:
    """A Glicko-2 rating triple.

    rating: float in 'Glicko-1 scale' (most users see this; ≈ chess
        Elo, 1500 is average, ±400 is typical)
    rd: rating deviation, 'how uncertain we are' (200 = very confident,
        350 = unknown / fresh entry)
    volatility: rate of expected fluctuation in performance
    """
    rating: float = DEFAULT_RATING_HORSE
    rd: float = DEFAULT_RD_HORSE
    volatility: float = DEFAULT_VOL_HORSE

    def to_g2(self) -> tuple[float, float]:
        """Convert to Glicko-2 internal scale (μ, φ)."""
        mu = (self.rating - 1500.0) / GLICKO2_SCALE
        phi = self.rd / GLICKO2_SCALE
        return mu, phi

    @classmethod
    def from_g2(cls, mu: float, phi: float, volatility: float) -> "GlickoRating":
        """Build from Glicko-2 internal scale."""
        return cls(
            rating=mu * GLICKO2_SCALE + 1500.0,
            rd=phi * GLICKO2_SCALE,
            volatility=volatility,
        )


def _g(phi: float) -> float:
    """Glickman's g(φ)."""
    return 1.0 / math.sqrt(1.0 + 3.0 * phi * phi / (math.pi * math.pi))


def _E(mu: float, mu_j: float, phi_j: float) -> float:
    """Expected outcome E(s|μ, μ_j, φ_j)."""
    return 1.0 / (1.0 + math.exp(-_g(phi_j) * (mu - mu_j)))


def expected_score(player: GlickoRating,
                   opponent: GlickoRating) -> float:
    """Expected score (probability of beating opponent) using Glicko-2.

    Returns probability in [0, 1].
    """
    mu_p, phi_p = player.to_g2()
    mu_o, phi_o = opponent.to_g2()
    return _E(mu_p, mu_o, phi_o)


def update_rating(player: GlickoRating,
                  results: Iterable[tuple["GlickoRating", float]]) -> GlickoRating:
    """Update player's rating based on a list of (opponent, score) pairs.

    `score`: 1.0 = won, 0.5 = draw, 0.0 = lost.

    For multi-runner races we discretize: at finishes ABOVE opponent
    → 1.0, BELOW → 0.0. (Each pairwise comparison treated as a 1v1.)

    Returns new GlickoRating. NEVER raises (graceful on bad input).
    """
    results = list(results)
    mu, phi = player.to_g2()

    if not results:
        # No games — increase RD slightly (rating period drift)
        new_phi = math.sqrt(phi * phi + player.volatility ** 2)
        return GlickoRating.from_g2(mu, new_phi, player.volatility)

    # Step 3: compute v (estimated variance)
    v_inv = 0.0
    delta_sum = 0.0
    for opp, score in results:
        try:
            score = float(score)
        except (TypeError, ValueError):
            continue
        mu_j, phi_j = opp.to_g2()
        g_j = _g(phi_j)
        e_j = _E(mu, mu_j, phi_j)
        v_inv += g_j * g_j * e_j * (1.0 - e_j)
        delta_sum += g_j * (score - e_j)
    if v_inv == 0:
        new_phi = math.sqrt(phi * phi + player.volatility ** 2)
        return GlickoRating.from_g2(mu, new_phi, player.volatility)
    v = 1.0 / v_inv

    # Step 4: delta
    delta = v * delta_sum

    # Step 5: new volatility (illinois iteration)
    a = math.log(player.volatility ** 2)

    def f(x: float) -> float:
        ex = math.exp(x)
        d2 = delta * delta
        phi2 = phi * phi
        return (ex * (d2 - phi2 - v - ex)
                / (2.0 * (phi2 + v + ex) ** 2)
                - (x - a) / (SYSTEM_TAU * SYSTEM_TAU))

    A = a
    if delta * delta > phi * phi + v:
        B = math.log(delta * delta - phi * phi - v)
    else:
        k = 1
        while f(a - k * SYSTEM_TAU) < 0 and k < 100:
            k += 1
        B = a - k * SYSTEM_TAU

    fA = f(A)
    fB = f(B)
    iterations = 0
    while abs(B - A) > EPSILON and iterations < 100:
        C = A + (A - B) * fA / (fB - fA)
        fC = f(C)
        if fC * fB <= 0:
            A = B
            fA = fB
        else:
            fA = fA / 2.0
        B = C
        fB = fC
        iterations += 1
    new_vol = math.exp(A / 2.0)

    # Step 6: pre-rating-period RD update
    phi_star = math.sqrt(phi * phi + new_vol ** 2)

    # Step 7: new RD and rating
    new_phi = 1.0 / math.sqrt(1.0 / (phi_star * phi_star) + 1.0 / v)
    new_mu = mu + new_phi * new_phi * delta_sum

    return GlickoRating.from_g2(new_mu, new_phi, new_vol)


def race_results_to_pairwise(
    horses_finishes: list[tuple["GlickoRating", int]],
    horse_index: int,
) -> list[tuple["GlickoRating", float]]:
    """Convert a multi-runner race into pairwise (opponent, score) for
    a specific horse.

    `horses_finishes`: list of (rating, finish_position) — finish 1 = winner.
    `horse_index`: which horse we're computing for.

    Returns: list of (opponent_rating, score) where score:
        1.0 if `horse_index` finished BEFORE opponent (lower position)
        0.0 if `horse_index` finished AFTER opponent (higher position)
        0.5 if tie
    """
    if horse_index < 0 or horse_index >= len(horses_finishes):
        return []
    my_rating, my_finish = horses_finishes[horse_index]
    pairs: list[tuple[GlickoRating, float]] = []
    for i, (opp_rating, opp_finish) in enumerate(horses_finishes):
        if i == horse_index:
            continue
        if my_finish is None or opp_finish is None:
            continue
        if my_finish < opp_finish:
            pairs.append((opp_rating, 1.0))
        elif my_finish > opp_finish:
            pairs.append((opp_rating, 0.0))
        else:
            pairs.append((opp_rating, 0.5))
    return pairs


def predict_top_n_probability(
    target: GlickoRating,
    opponents: Iterable[GlickoRating],
    target_n: int = 4,
    n_samples: int = 2000,
    seed: int = 42,
) -> float:
    """Monte Carlo P(target finishes in top N of race).

    Sample each runner's "performance" from N(rating, rd² + vol²),
    then count fraction of simulations where target's score is in
    the top `target_n`.

    Pür stdlib (random.gauss) — numpy gerek değil.
    """
    import random
    rng = random.Random(seed)
    opponents = list(opponents)
    if not opponents:
        return 1.0  # alone = always top
    field_size = len(opponents) + 1
    target_n = min(target_n, field_size)
    hits = 0
    # std for performance draws
    t_std = math.sqrt(target.rd ** 2 + (target.volatility * 100) ** 2)
    o_stds = [
        math.sqrt(o.rd ** 2 + (o.volatility * 100) ** 2) for o in opponents
    ]
    for _ in range(n_samples):
        t_perf = rng.gauss(target.rating, t_std)
        o_perfs = [rng.gauss(o.rating, s) for o, s in zip(opponents, o_stds)]
        # Top-N: how many opponents beat target?
        beaten_by = sum(1 for p in o_perfs if p > t_perf)
        if beaten_by < target_n:
            hits += 1
    return hits / n_samples


# ---------------------------------------------------------------------------
# Ledger — persistent rating store
# ---------------------------------------------------------------------------
@dataclass
class GlickoLedger:
    """Per-entity Glicko ratings. Persistent via JSON.

    `entity` ID is whatever string identifies the entity (horse name,
    jockey name, etc.). Ratings are stored as dicts and serialize
    cleanly to JSON.
    """
    ratings: dict[str, GlickoRating] = field(default_factory=dict)
    default: GlickoRating = field(default_factory=GlickoRating)

    def get(self, entity: str) -> GlickoRating:
        return self.ratings.get(entity, self.default)

    def set(self, entity: str, rating: GlickoRating) -> None:
        self.ratings[entity] = rating

    def update(self, entity: str,
               results: Iterable[tuple[GlickoRating, float]]) -> GlickoRating:
        cur = self.get(entity)
        new = update_rating(cur, results)
        self.set(entity, new)
        return new

    def to_json(self) -> dict:
        return {
            "ratings": {
                k: {"rating": r.rating, "rd": r.rd, "vol": r.volatility}
                for k, r in self.ratings.items()
            },
            "default": {
                "rating": self.default.rating,
                "rd": self.default.rd,
                "vol": self.default.volatility,
            },
        }

    @classmethod
    def from_json(cls, data: Mapping) -> "GlickoLedger":
        ledger = cls()
        for k, v in (data.get("ratings") or {}).items():
            ledger.ratings[k] = GlickoRating(
                rating=v.get("rating", DEFAULT_RATING_HORSE),
                rd=v.get("rd", DEFAULT_RD_HORSE),
                volatility=v.get("vol", DEFAULT_VOL_HORSE),
            )
        d = data.get("default") or {}
        ledger.default = GlickoRating(
            rating=d.get("rating", DEFAULT_RATING_HORSE),
            rd=d.get("rd", DEFAULT_RD_HORSE),
            volatility=d.get("vol", DEFAULT_VOL_HORSE),
        )
        return ledger
