"""Plackett-Luce Monte Carlo race simulation (Top-K Enhanced Layer-2).

Berkay (2026-06-15): "top3/top4 max'a çek, mevcut hiçbir şey değişmesin".

V6 ranker'ın race-level prob'larını Monte Carlo simulation ile empirical
P(top3) ve P(top4)'e çevirir. Plackett-Luce: sequential selection with
remaining probability normalization.

Mantık:
  - Yarışta n at, her at için ranker score s_i
  - Plackett-Luce: P(at i'nin 1. olma olasılığı) = exp(s_i) / Σ exp(s_j)
  - 2. olma: kalan atlar arasında normalize
  - 3. olma: ...
  - 10000 simulation → at başına empirical top-3/top-4 hit count
  - Bu RAW ranker softmax'tan farklı (özellikle top-K joint distribution için)

Public API:
  simulate_topk(scores, n_sims=10000) -> dict
    Returns:
      {'top1_prob': [...], 'top3_prob': [...], 'top4_prob': [...]}

Hata durumunda graceful: scores boş/tek → equiprob.
"""
from __future__ import annotations

import numpy as np


def _softmax(s, temperature=1.0):
    """Softmax with temperature; stable shift."""
    s = np.asarray(s, dtype=float) / max(temperature, 1e-6)
    s -= s.max()
    e = np.exp(s)
    total = e.sum()
    return e / (total if total > 0 else 1.0)


def simulate_topk(scores, n_sims=10000, k_max=4, temperature=1.0, seed=42):
    """V6 ranker scores → Monte Carlo empirical P(topk) per horse.

    scores: list/array of length n (race içindeki her at için ranker score)
    n_sims: simulation count (10K default, 1-2 saniye)
    k_max: top-K cap (4 yeterli)
    temperature: softmax temperature (1.0 default; <1 daha keskin, >1 daha yumuşak)
    """
    s = np.asarray(scores, dtype=float)
    n = len(s)
    if n == 0:
        return {'top1_prob': [], 'top3_prob': [], 'top4_prob': []}
    if n == 1:
        return {'top1_prob': [1.0], 'top3_prob': [1.0], 'top4_prob': [1.0]}

    base_probs = _softmax(s, temperature)
    rng = np.random.default_rng(seed)
    counts = np.zeros((k_max, n), dtype=np.int64)

    for _ in range(n_sims):
        remaining = base_probs.copy()
        # Sequential selection (Plackett-Luce)
        for pos in range(min(k_max, n)):
            r_sum = remaining.sum()
            if r_sum <= 0:
                break
            p = remaining / r_sum
            chosen = rng.choice(n, p=p)
            counts[pos, chosen] += 1
            remaining[chosen] = 0.0

    # Cumulative top-K
    top1_prob = counts[0] / n_sims
    top3_prob = counts[:3].sum(axis=0) / n_sims  # 1+2+3 anywhere
    top4_prob = counts[:4].sum(axis=0) / n_sims

    return {
        'top1_prob': top1_prob.tolist(),
        'top3_prob': top3_prob.tolist(),
        'top4_prob': top4_prob.tolist(),
    }


def simulate_topk_combo(scores, n_sims=10000, top_n_combos=10, k=4, seed=42):
    """En olası top-K sıralı kombinasyonları döndür (SİB combo bahisleri için)."""
    from collections import Counter
    s = np.asarray(scores, dtype=float)
    n = len(s)
    if n < k:
        return []
    base_probs = _softmax(s)
    rng = np.random.default_rng(seed)
    combos = Counter()
    for _ in range(n_sims):
        remaining = base_probs.copy()
        seq = []
        for _ in range(k):
            r_sum = remaining.sum()
            if r_sum <= 0: break
            chosen = rng.choice(n, p=remaining / r_sum)
            seq.append(int(chosen))
            remaining[chosen] = 0.0
        combos[tuple(sorted(seq))] += 1   # unordered top-4 combo
    return [(list(c), v / n_sims) for c, v in combos.most_common(top_n_combos)]
