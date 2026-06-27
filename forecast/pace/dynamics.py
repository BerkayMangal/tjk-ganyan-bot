"""Race-day AGF drift dynamics — derinlemesine.

Mevcut top4.agf_drift basit drift hesaplar (open vs now). Bu modül
daha derin sinyaller üretir:

  1) Volatility: AGF salınımı yüksek mi?
  2) Sharp money detect: ani büyük hareketler
  3) Trend confirmation: tutarlı yön mü, gürültü mü?
  4) Crowd convergence: halk birleşiyor mu, ayrışıyor mu?

Bu sinyaller race-day forward-looking — career özetten çok daha taze.

API
---
- `compute_drift_metrics(snapshots) -> DriftMetrics`
- `classify_market_move(drift_metrics) -> str`
- `confidence_from_volatility(volatility) -> float`
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Iterable, Mapping, Optional


@dataclass
class DriftMetrics:
    """AGF drift derinlemesine."""
    abs_drift: Optional[float] = None        # son - ilk
    rel_drift: Optional[float] = None        # %
    rank_movement: Optional[int] = None      # rank değişikliği
    volatility: Optional[float] = None       # AGF salınımı (std)
    n_snapshots: int = 0
    direction_consistency: Optional[float] = None  # 0..1
    sharp_move_count: int = 0                # > %25 ani jump sayısı
    is_steam: bool = False                    # steam move tespit
    is_drift_down: bool = False               # drift down (sharp away from)


def compute_drift_metrics(
    snapshots: list[float],
    rank_snapshots: Optional[list[int]] = None,
) -> DriftMetrics:
    """AGF % değerlerinin sekansından drift metrikleri.

    `snapshots`: chronological order (eski → yeni). En az 2 entry.

    NEVER raises.
    """
    vals = [v for v in snapshots if v is not None]
    if len(vals) < 2:
        return DriftMetrics(n_snapshots=len(vals))

    n = len(vals)
    first = vals[0]
    last = vals[-1]
    abs_drift = last - first
    denom = max(first, 0.5)
    rel_drift = abs_drift / denom

    # Volatility = std of consecutive differences
    diffs = [vals[i + 1] - vals[i] for i in range(n - 1)]
    if len(diffs) >= 2:
        mean_d = sum(diffs) / len(diffs)
        var = sum((d - mean_d) ** 2 for d in diffs) / len(diffs)
        volatility = math.sqrt(var)
    else:
        volatility = abs(diffs[0]) if diffs else 0.0

    # Direction consistency: positive diff oranı (eğer hep up ise 1)
    pos_diffs = sum(1 for d in diffs if d > 0)
    neg_diffs = sum(1 for d in diffs if d < 0)
    if pos_diffs + neg_diffs > 0:
        consistency = abs(pos_diffs - neg_diffs) / (pos_diffs + neg_diffs)
    else:
        consistency = 0.0

    # Sharp moves: > %25 of base in single step
    sharp = 0
    for d in diffs:
        if abs(d) / denom > 0.25:
            sharp += 1

    # Steam: consistent up + high relative drift
    # Drift-down: consistent down + significant rel drift
    is_steam = (rel_drift >= 0.25 and consistency >= 0.6
                and pos_diffs > neg_diffs)
    is_drift_down = (rel_drift <= -0.25 and consistency >= 0.6
                     and neg_diffs > pos_diffs)

    # Rank movement
    rank_mv = None
    if rank_snapshots and len(rank_snapshots) >= 2:
        try:
            rank_mv = rank_snapshots[0] - rank_snapshots[-1]
        except (TypeError, ValueError):
            pass

    return DriftMetrics(
        abs_drift=abs_drift,
        rel_drift=rel_drift,
        rank_movement=rank_mv,
        volatility=volatility,
        n_snapshots=n,
        direction_consistency=consistency,
        sharp_move_count=sharp,
        is_steam=is_steam,
        is_drift_down=is_drift_down,
    )


def classify_market_move(metrics: DriftMetrics) -> str:
    """Drift metrics → kategori.

    Returns one of:
      'steam'       : sharp money pump (büyük up, tutarlı)
      'drift_down'  : sharp money fade (büyük down, tutarlı)
      'volatile'    : yüksek volatility, yön belirsiz
      'mild_up'     : küçük artış
      'mild_down'   : küçük düşüş
      'stable'      : minimal değişim
      'unknown'     : yetersiz data
    """
    if metrics.n_snapshots < 2:
        return "unknown"
    if metrics.is_steam:
        return "steam"
    if metrics.is_drift_down:
        return "drift_down"
    # Volatility-based
    if metrics.volatility is not None and metrics.volatility > 3.0:
        return "volatile"
    if metrics.rel_drift is None:
        return "unknown"
    if metrics.rel_drift > 0.10:
        return "mild_up"
    if metrics.rel_drift < -0.10:
        return "mild_down"
    return "stable"


def confidence_from_volatility(volatility: Optional[float],
                                base_confidence: float = 1.0) -> float:
    """Yüksek volatility → düşük güven.

    Returns base × adjustment factor in (0, 1].
      vol < 1: factor ≈ 1.0
      vol 1-3: factor 0.7 - 1.0
      vol > 3: factor 0.4 - 0.7
    """
    if volatility is None or volatility < 0:
        return base_confidence
    if volatility < 1.0:
        factor = 1.0
    elif volatility < 3.0:
        factor = 1.0 - (volatility - 1.0) / 2.0 * 0.3
    else:
        factor = max(0.4, 0.7 - (volatility - 3.0) * 0.1)
    return base_confidence * factor


def steam_move_advantage(metrics: DriftMetrics) -> float:
    """Steam move detected → at için ne kadar advantage var?

    Returns 0..0.25 — additive boost to base probability.
    """
    if not metrics.is_steam:
        return 0.0
    # Stronger when rel_drift is bigger AND consistency higher
    if metrics.rel_drift is None or metrics.direction_consistency is None:
        return 0.0
    return min(0.25, metrics.rel_drift * 0.3 + metrics.direction_consistency * 0.05)


def crowd_convergence_score(
    horses_drift: list[DriftMetrics],
) -> float:
    """Yarış field için: halk birleşiyor mu (top atlara)?

    Eğer top 3-4 atın AGF artışı varken kalanlar düşüyorsa → convergence.
    Returns -1 (divergence) .. +1 (convergence). 0 = neutral.
    """
    if not horses_drift:
        return 0.0
    diffs = [d.rel_drift for d in horses_drift if d.rel_drift is not None]
    if not diffs:
        return 0.0
    diffs_sorted = sorted(diffs, reverse=True)
    top_quartile = diffs_sorted[:max(1, len(diffs_sorted) // 4)]
    bottom_quartile = diffs_sorted[-max(1, len(diffs_sorted) // 4):]
    top_avg = sum(top_quartile) / len(top_quartile)
    bot_avg = sum(bottom_quartile) / len(bottom_quartile)
    # If top_avg > 0 and bot_avg < 0 → convergence
    spread = top_avg - bot_avg
    return max(-1.0, min(1.0, spread / 2.0))
