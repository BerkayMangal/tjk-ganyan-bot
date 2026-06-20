"""Risk-adjusted EV estimation for Top-4 tickets.

Given a list of historical payouts (sampled from prior races matching the
proposed ticket profile), produce robust EV diagnostics. The point is to
make extreme-tail skew explicit rather than to celebrate one big payout.
"""
from __future__ import annotations

import math
import random
import statistics
from dataclasses import dataclass
from typing import Sequence


@dataclass
class RobustEV:
    n: int
    hit_rate: float
    mean_payout: float
    median_payout: float
    trimmed_mean: float
    p5: float
    p25: float
    p75: float
    p95: float
    bootstrap_lo: float
    bootstrap_hi: float
    skew_warning: bool
    max_drawdown_estimate: float
    risk_of_ruin_proxy: float
    note: str = ""


def _percentile(sorted_xs: list[float], pct: float) -> float:
    if not sorted_xs:
        return 0.0
    k = (len(sorted_xs) - 1) * pct
    f = int(math.floor(k))
    c = int(math.ceil(k))
    if f == c:
        return sorted_xs[f]
    return sorted_xs[f] + (sorted_xs[c] - sorted_xs[f]) * (k - f)


def _trimmed_mean(xs: list[float], trim: float = 0.1) -> float:
    if not xs:
        return 0.0
    s = sorted(xs)
    k = int(len(s) * trim)
    if len(s) - 2 * k <= 0:
        return statistics.fmean(s)
    return statistics.fmean(s[k:len(s) - k])


def _bootstrap_ci(xs: list[float], iters: int = 1000, alpha: float = 0.05) -> tuple[float, float]:
    if not xs:
        return (0.0, 0.0)
    means: list[float] = []
    n = len(xs)
    rng = random.Random(1234)
    for _ in range(iters):
        sample = [xs[rng.randrange(n)] for _ in range(n)]
        means.append(sum(sample) / n)
    means.sort()
    return (_percentile(means, alpha / 2), _percentile(means, 1 - alpha / 2))


def _max_drawdown(returns: Sequence[float]) -> float:
    """Estimate max drawdown from a sequence of per-ticket net returns.
    Each `returns[i]` = payout - cost (already net).
    """
    peak = 0.0
    equity = 0.0
    dd = 0.0
    for r in returns:
        equity += r
        peak = max(peak, equity)
        dd = max(dd, peak - equity)
    return dd


def _risk_of_ruin(returns: Sequence[float], bankroll: float = 100.0) -> float:
    if not returns:
        return 1.0
    equity = bankroll
    floor_hits = 0
    trials = 500
    rng = random.Random(99)
    n = len(returns)
    for _ in range(trials):
        e = bankroll
        for _ in range(n):
            e += returns[rng.randrange(n)]
            if e <= 0:
                floor_hits += 1
                break
    return floor_hits / trials


def compute(
    payouts: Sequence[float],
    ticket_cost: float,
    hits: int,
    total_tickets: int,
) -> RobustEV:
    """`payouts`: payout amounts for HIT tickets only. `total_tickets`:
    total attempts (hit + miss). `ticket_cost`: avg cost per ticket.
    """
    n = total_tickets
    pl = list(payouts)
    pl_sorted = sorted(pl)
    hit_rate = (hits / n) if n > 0 else 0.0
    mean_p = (sum(pl) / len(pl)) if pl else 0.0
    median_p = _percentile(pl_sorted, 0.5) if pl_sorted else 0.0
    trimmed = _trimmed_mean(pl) if pl else 0.0
    p5 = _percentile(pl_sorted, 0.05) if pl_sorted else 0.0
    p25 = _percentile(pl_sorted, 0.25) if pl_sorted else 0.0
    p75 = _percentile(pl_sorted, 0.75) if pl_sorted else 0.0
    p95 = _percentile(pl_sorted, 0.95) if pl_sorted else 0.0
    lo, hi = _bootstrap_ci(pl) if pl else (0.0, 0.0)

    # build per-ticket net returns for drawdown estimation
    miss_returns = [-ticket_cost] * (n - hits)
    hit_returns = [(p - ticket_cost) for p in pl]
    # interleave roughly
    all_returns = miss_returns + hit_returns
    random.Random(2026).shuffle(all_returns)
    mdd = _max_drawdown(all_returns)
    ror = _risk_of_ruin(all_returns)

    # Skew warning if median is far below mean
    skew = bool(mean_p > 0 and median_p < 0.5 * mean_p)

    return RobustEV(
        n=n,
        hit_rate=hit_rate,
        mean_payout=mean_p,
        median_payout=median_p,
        trimmed_mean=trimmed,
        p5=p5, p25=p25, p75=p75, p95=p95,
        bootstrap_lo=lo, bootstrap_hi=hi,
        skew_warning=skew,
        max_drawdown_estimate=mdd,
        risk_of_ruin_proxy=ror,
        note="payouts may be proxy; verify before action" if skew else "",
    )
