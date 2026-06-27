"""Recency-weighted form features.

Mevcut V7'deki kariyer ortalamaları (`career_top4_rate` gibi) TÜM
geçmişe eşit ağırlık veriyor. Bu, **yön bilgisini** kaybeder:
- Bir at 50 koşuda %30 top-4 yapmış olsun
- Ama SON 5 koşuda %80 yapıyor → trend yukarı, gerçek güç bambaşka

Bu modül **exponential decay** ile recency-weighted oranlar hesaplar:

    w_i = decay ** i      (i = en yeniden geriye, i=0 en taze)
    rate = sum(w_i * y_i) / sum(w_i)

`decay=0.85` → en taze koşu yarısı kadar ağırlığı 4 koşu öncesi
alır. Daha keskin trendler için `decay=0.7` kullanın.

Ayrıca:
- Pencere-bazlı oranlar (son 3, 5, 10)
- Career vs recent gap (trend signal: + = yükseliyor, − = düşüyor)
- Empirical Bayes shrinkage (az koşulu atlar için)

API
---
- `weighted_rate(positions: list[int], target: int, decay=0.85)`
- `window_rate(positions, window, target)`
- `recent_vs_career_gap(positions, recent_window=5, target=4)`
- `compute_recency_features(records, target_top=4)` → dict
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


def weighted_rate(
    positions: Iterable[Optional[int]],
    target: int = 4,
    decay: float = 0.85,
) -> Optional[float]:
    """Exponential recency-weighted top-N rate.

    `positions` ÖN TARAFI EN TAZE → arka SON ESKİ. None entry'ler
    skip edilir. Decay 0..1 arası (1=hiç decay yok = career mean).

    Returns None if no valid positions.
    """
    if decay <= 0 or decay > 1:
        raise ValueError("decay must be in (0, 1]")
    positions = [p for p in positions if p is not None]
    if not positions:
        return None
    num = 0.0
    den = 0.0
    for i, p in enumerate(positions):
        try:
            pos = int(p)
        except (TypeError, ValueError):
            continue
        w = decay ** i
        num += w * (1.0 if pos <= target else 0.0)
        den += w
    if den == 0:
        return None
    return num / den


def window_rate(
    positions: Iterable[Optional[int]],
    window: int,
    target: int = 4,
) -> Optional[float]:
    """Top-N rate over last `window` races (unweighted)."""
    positions = list(positions)[:window]
    valid = [int(p) for p in positions if p is not None]
    if not valid:
        return None
    hits = sum(1 for p in valid if p <= target)
    return hits / len(valid)


def recent_vs_career_gap(
    positions: Iterable[Optional[int]],
    recent_window: int = 5,
    target: int = 4,
) -> Optional[float]:
    """Recent window rate − career rate.

    + → trend yükseliyor (at son zamanlarda kariyer ortalamasından
        daha iyi performans gösteriyor)
    − → trend düşüyor
    0 → stabil
    None → veri yetersiz

    Negatif sayılar genelde "at form düşüşünde" anlamına gelir.
    """
    positions = list(positions)
    if not positions:
        return None
    career = window_rate(positions, len(positions), target)
    recent = window_rate(positions, recent_window, target)
    if career is None or recent is None:
        return None
    return recent - career


def empirical_bayes_shrinkage(
    rate: Optional[float],
    n: int,
    prior_rate: float = 0.40,
    prior_n: int = 8,
) -> Optional[float]:
    """Shrinkage estimator — küçük örnekleri prior'a doğru çek.

    rate_shrunk = (n * rate + prior_n * prior_rate) / (n + prior_n)

    Bu, "at 2 koşuda %100 top-4 yapmış" gibi yanıltıcı sample'ları
    yumuşatır.
    """
    if rate is None or n is None or n <= 0:
        return None
    return (n * rate + prior_n * prior_rate) / (n + prior_n)


@dataclass
class RecencyFeatures:
    """Tek bir atın recency feature setı."""
    n_races: int
    # weighted ratios
    weighted_top1_85: Optional[float]
    weighted_top3_85: Optional[float]
    weighted_top4_85: Optional[float]
    weighted_top4_70: Optional[float]  # daha agresif decay
    # window-based
    last3_top4: Optional[float]
    last5_top4: Optional[float]
    last10_top4: Optional[float]
    # gap signals
    gap_recent5_career_top4: Optional[float]  # YÖN SİNYALİ
    # shrunk versions
    shrunk_top4_career: Optional[float]
    shrunk_last5_top4: Optional[float]


def compute_recency_features(
    positions: Iterable[Optional[int]],
    target_top: int = 4,
) -> RecencyFeatures:
    """Tek atın koşu sekansından recency feature setı üret.

    `positions`: en taze koşu önce. Örn: 3 koşu eski → [pos_son, pos_önceki, pos_eski]

    Eksik veri => alanlar None. Hiçbir ZAMAN raise etmez.
    """
    pos_list = list(positions)
    n_valid = sum(1 for p in pos_list if p is not None)

    return RecencyFeatures(
        n_races=n_valid,
        weighted_top1_85=weighted_rate(pos_list, target=1, decay=0.85),
        weighted_top3_85=weighted_rate(pos_list, target=3, decay=0.85),
        weighted_top4_85=weighted_rate(pos_list, target=target_top, decay=0.85),
        weighted_top4_70=weighted_rate(pos_list, target=target_top, decay=0.70),
        last3_top4=window_rate(pos_list, 3, target_top),
        last5_top4=window_rate(pos_list, 5, target_top),
        last10_top4=window_rate(pos_list, 10, target_top),
        gap_recent5_career_top4=recent_vs_career_gap(pos_list, 5, target_top),
        shrunk_top4_career=empirical_bayes_shrinkage(
            window_rate(pos_list, len(pos_list), target_top), n_valid,
        ),
        shrunk_last5_top4=empirical_bayes_shrinkage(
            window_rate(pos_list, 5, target_top),
            min(5, n_valid),
        ),
    )
