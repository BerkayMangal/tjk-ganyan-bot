"""V7 prod-time race-relative features (rr__ prefix).

Phase 5.8.28: V7 (225 feature) = V6 (210) + 15 race-relative.
Bu modül yarış-bazlı (cross-section) yüksek-yoğun feature'ları üretir.

Her at için:
  - rank (1..N, yarış-içi sıra)
  - zscore (yarış mean/std'sine göre)
  - gap-from-top1
  - above-field-mean (binary)

V6 SHADOW'da hesaplanan career, race-context, interactions, polynomials
zaten dashboard.feature_compute_v6'da. V7 ek olarak rr__'ları üretir.
"""
from __future__ import annotations

from typing import List, Dict
import numpy as np

# Spec: source_col → (rr_col, kind), kind ∈ {'rank_desc', 'rank_asc', 'zscore', 'gap', 'above_mean'}
SPECS = [
    # RANK descending (yüksek değer = düşük rank, rank 1 = en iyi)
    ('cf__career_top4_rate', 'rr__career_top4_rate_rank', 'rank_desc'),
    ('cf__career_top3_rate', 'rr__career_top3_rate_rank', 'rank_desc'),
    ('cf__career_avg_finish', 'rr__career_avg_finish_rank', 'rank_asc'),  # düşük finish = iyi
    ('mf__jockey_cond_top4', 'rr__jockey_cond_top4_rank', 'rank_desc'),
    ('cf__career_recent5_top4_rate', 'rr__career_recent5_top4_rank', 'rank_desc'),
    ('cf__same_dist_top3_rate', 'rr__same_dist_top3_rate_rank', 'rank_desc'),
    ('agf_pct', 'rr__agf_rank', 'rank_desc'),

    # Z-SCORE
    ('cf__career_top4_rate', 'rr__career_top4_rate_zscore', 'zscore'),
    ('cf__career_top3_rate', 'rr__career_top3_rate_zscore', 'zscore'),
    ('mf__jockey_cond_top4', 'rr__jockey_cond_top4_zscore', 'zscore'),

    # GAP-from-top1
    ('cf__career_top4_rate', 'rr__career_top4_rate_gap_top1', 'gap'),
    ('agf_pct', 'rr__agf_gap_top1', 'gap'),
    ('cf__career_recent5_top4_rate', 'rr__career_recent5_top4_gap_top1', 'gap'),

    # ABOVE-FIELD-MEAN
    ('cf__career_top4_rate', 'rr__career_top4_above_field_mean', 'above_mean'),
    ('mf__jockey_cond_top4', 'rr__jockey_cond_above_field_mean', 'above_mean'),
]


def compute_race_relative(horse_features: List[Dict]) -> List[Dict]:
    """horse_features: V6 compute_horse() çıktısı list (yarış-bazlı).

    Returns: aynı list, her dict'e rr__* eklenmiş.
    """
    if not horse_features:
        return horse_features
    n = len(horse_features)
    out = [dict(h) for h in horse_features]

    # Her source col için race-içi vector
    for src, rr, kind in SPECS:
        values = np.array([float(h.get(src) or 0) for h in out], dtype=float)
        if kind == 'rank_desc':
            # Yüksek değer → düşük rank (1 = en iyi)
            order = np.argsort(-values)
            ranks = np.empty(n, dtype=int)
            ranks[order] = np.arange(1, n + 1)
            # Tie-break: aynı değer → aynı rank (min method)
            ranks = _min_rank(values, ascending=False)
            for i in range(n):
                out[i][rr] = float(ranks[i])
        elif kind == 'rank_asc':
            ranks = _min_rank(values, ascending=True)
            for i in range(n):
                out[i][rr] = float(ranks[i])
        elif kind == 'zscore':
            mean = float(values.mean())
            std = float(values.std()) or 1.0
            for i in range(n):
                out[i][rr] = (values[i] - mean) / std
        elif kind == 'gap':
            top1 = float(values.max())
            for i in range(n):
                out[i][rr] = values[i] - top1
        elif kind == 'above_mean':
            mean = float(values.mean())
            for i in range(n):
                out[i][rr] = 1.0 if values[i] > mean else 0.0
    return out


def _min_rank(values, ascending=False):
    """Pandas rank(method='min'). Tie-break: aynı değer → min rank."""
    n = len(values)
    arr = np.asarray(values, dtype=float)
    sign = 1 if ascending else -1
    sorted_idx = np.argsort(sign * arr)
    ranks = np.empty(n, dtype=int)
    rank_counter = 1
    i = 0
    while i < n:
        j = i
        # Tie group
        while j + 1 < n and arr[sorted_idx[j]] == arr[sorted_idx[j+1]]:
            j += 1
        for k in range(i, j + 1):
            ranks[sorted_idx[k]] = rank_counter
        rank_counter = j + 2
        i = j + 1
    return ranks


def feature_names():
    """V7'nin 15 yeni rr__ feature isimleri (sıralı)."""
    return [rr for _, rr, _ in SPECS]
