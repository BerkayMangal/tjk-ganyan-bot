"""Ranking Head — binary classifier prob'larından top-k tutarlı türetim.

Plackett-Luce: P(sıralı a,b,c,...) = ∏ (p_i / Σ p_remaining).
Harville aproksimasyonu (top-k SIRASIZ): tüm permütasyonlar üzerinde toplam.
Henery düzeltmesi: ikinci/üçüncü pozisyonda fark katsayısı (sıralama variance).

Tek-at top-k MODELİNDEN (audit/21) çıkan kalibre prob:
  p_top1_i = at i'nin kazanma olasılığı (binary classifier kalibre)

Bu modülden:
  - P(exacta a,b)        = p_a × p_b / (1-p_a)
  - P(quinella {a,b})    = exacta(a,b) + exacta(b,a)
  - P(sıralı trifecta a,b,c) = p_a × p_b/(1-p_a) × p_c/(1-p_a-p_b)
  - P(top-3 sırasız {a,b,c}) = Σ perm exacta türetimi
  - P(top-4 sıralı tabela)
"""
from __future__ import annotations
import numpy as np
from typing import List, Tuple
from itertools import permutations


def _safe_norm(probs: np.ndarray) -> np.ndarray:
    """Ayak içi prob'ları toplamı 1'e normalize. NaN-safe."""
    p = np.asarray(probs, dtype=float)
    p = np.clip(p, 1e-9, 1 - 1e-9)
    s = p.sum()
    return p / s if s > 0 else np.full_like(p, 1.0 / len(p))


def plackett_luce_sequence_prob(p: np.ndarray, indices: List[int]) -> float:
    """P(sıralı: indices[0] 1., indices[1] 2., ..., indices[k-1] k.).
    PL formülü: ∏ p_i / Σ p_remaining.
    """
    p = _safe_norm(p)
    remaining = list(range(len(p)))
    out = 1.0
    for idx in indices:
        if idx not in remaining:
            return 0.0
        denom = sum(p[r] for r in remaining)
        if denom <= 0:
            return 0.0
        out *= p[idx] / denom
        remaining.remove(idx)
    return float(out)


def exacta_prob(p: np.ndarray, a: int, b: int) -> float:
    """P(a 1., b 2.). PL."""
    return plackett_luce_sequence_prob(p, [a, b])


def quinella_prob(p: np.ndarray, a: int, b: int) -> float:
    """P(top-2 = {a,b} sırasız)."""
    return exacta_prob(p, a, b) + exacta_prob(p, b, a)


def trifecta_prob(p: np.ndarray, a: int, b: int, c: int) -> float:
    """P(a 1., b 2., c 3.)."""
    return plackett_luce_sequence_prob(p, [a, b, c])


def trio_prob(p: np.ndarray, a: int, b: int, c: int) -> float:
    """P(top-3 = {a,b,c} sırasız) = Σ 6 permütasyon."""
    return sum(plackett_luce_sequence_prob(p, list(perm)) for perm in permutations([a, b, c]))


def tabela_prob_ordered(p: np.ndarray, a: int, b: int, c: int, d: int) -> float:
    """P(top-4 sıralı a,b,c,d)."""
    return plackett_luce_sequence_prob(p, [a, b, c, d])


def tabela_prob_unordered(p: np.ndarray, four_set: List[int]) -> float:
    """P(top-4 = set sırasız) = 24 permütasyon."""
    return sum(plackett_luce_sequence_prob(p, list(perm)) for perm in permutations(four_set))


def top_k_membership_probs(p: np.ndarray, k: int = 3) -> np.ndarray:
    """Per-at: P(at i ∈ top-k) — Plackett-Luce.
    EXACT için tüm k-permütasyonlar topla. n=18, k=4 → 73k perm/race ≈ 0.5s — kabul edilebilir.
    Çok büyük (n>16 + k>4) Monte Carlo M=20000 fallback.
    """
    p = _safe_norm(p)
    n = len(p)
    if n <= k:
        return np.ones(n)
    # Exact: O(n! / (n-k)!) per call. n=14 k=4 → 24024 perm. n=18 k=4 → 73440.
    # Bu hızlı (Python loop ile race başına 50ms-500ms).
    if n <= 18 and k <= 4:
        mem = np.zeros(n)
        for perm in permutations(range(n), k):
            prob = plackett_luce_sequence_prob(p, list(perm))
            for idx in perm:
                mem[idx] += prob
        return mem
    # Fallback Monte Carlo for very large k
    rng = np.random.default_rng(42)
    M = 20000
    mem = np.zeros(n)
    for _ in range(M):
        remaining = list(range(n))
        for _step in range(k):
            r_p = np.array([p[r] for r in remaining])
            r_p = r_p / r_p.sum()
            choice = remaining[rng.choice(len(remaining), p=r_p)]
            mem[choice] += 1
            remaining.remove(choice)
    return mem / M


def fast_harville_topk_mc(p: np.ndarray, k: int, M: int = 500,
                          seed: int = 42) -> np.ndarray:
    """Plackett-Luce Monte Carlo top-k membership — n=any, fast.
    Per-race ~1ms, 20k races ~20s. Variance 1/√M ≈ ±4.5% at M=500.
    Returns (n,) membership prob array; sum ≈ k.
    """
    p = np.asarray(p, dtype=float)
    p = np.clip(p, 1e-12, 1 - 1e-12)
    p = p / p.sum()
    n = len(p)
    if k >= n:
        return np.ones(n)
    rng = np.random.default_rng(seed)
    mem = np.zeros(n)
    for _ in range(M):
        remaining = p.copy()
        for _step in range(k):
            s = remaining.sum()
            if s <= 0: break
            r = remaining / s
            choice = int(rng.choice(n, p=r))
            mem[choice] += 1.0
            remaining[choice] = 0.0
    return mem / M


def henery_adjustment(p: np.ndarray, beta_2: float = 0.70, beta_3: float = 0.60) -> dict:
    """Henery düzeltmesi: 2. ve 3. pozisyonda variance daha düşük.
    Adjusted prob = p**beta_pos.
    β2=0.70, β3=0.60 — audit/36_henery_fit ile TR AGF prob 2023-2025 fit edildi
    (Brier minimize). Önceki hardcoded değerler: 0.85/0.70 (literatür) — TR'de daha flat.
    Returns {pos1: p_pos1, pos2: p_pos2_adj, pos3: p_pos3_adj}.
    """
    p = _safe_norm(p)
    p2 = p ** beta_2; p2 = p2 / p2.sum()
    p3 = p ** beta_3; p3 = p3 / p3.sum()
    return {'pos1': p, 'pos2': p2, 'pos3': p3}


if __name__ == '__main__':
    # Smoke
    # 8-at yarışı, kalibre prob'lar
    p = np.array([0.30, 0.20, 0.15, 0.10, 0.08, 0.07, 0.06, 0.04])
    print(f"Probs (sum={p.sum():.3f}):", p)
    print(f"Exacta (0,1): {exacta_prob(p, 0, 1):.4f}")
    print(f"Quinella {{0,1}}: {quinella_prob(p, 0, 1):.4f}")
    print(f"Trifecta (0,1,2): {trifecta_prob(p, 0, 1, 2):.4f}")
    print(f"Trio {{0,1,2}}: {trio_prob(p, 0, 1, 2):.4f}")
    print(f"Tabela ordered (0,1,2,3): {tabela_prob_ordered(p, 0, 1, 2, 3):.4f}")
    print(f"Tabela unordered {{0,1,2,3}}: {tabela_prob_unordered(p, [0,1,2,3]):.4f}")
    print(f"Top-3 membership: {top_k_membership_probs(p, 3)}")
    print(f"  (sum={top_k_membership_probs(p, 3).sum():.3f} — beklenen ≈ 3.0)")
