"""Entity embeddings — At/Jokey/Sire için SVD-based gizli karakter vektörleri.

Berkay (2026-06-29): 'olmayan şeylere bakmalıyız' → her atın/jokeyin/soyun
"yıllar boyu imzası", Word2Vec mantığında matrix factorization ile.

Yöntem:
  • At × At co-occurrence matrix (aynı yarışta birlikte koşma sayısı)
  • SVD → k-boyutlu latent vector her at için
  • Benzer pozisyondaki atlar yakın vektör → kümeleme + similarity
  • Sıralama tahmin için ek feature: 8-dim her at için

NumPy only — gensim/sklearn dependency yok.

API
---
- `build_horse_embedding(outcomes_records, dim=8)` → {name: vec[8]}
- `build_jockey_embedding(outcomes_records, dim=8)`
- `build_sire_embedding(outcomes_records, dim=8)`
- `embedding_features(name, embed_map)` → flat dict {emb_0..emb_7}
"""
from __future__ import annotations

import logging
import math
from collections import defaultdict
from typing import Optional

import numpy as np

logger = logging.getLogger(__name__)


def _build_cooccurrence(records: list[dict], entity_key: str = "name"):
    """Aynı (date, hippo, kosu_no) içinde co-occurrence matrix.

    Returns: (entities list, M [n×n] co-count matrix).
    """
    # group by race
    race_entities = defaultdict(set)
    for r in records:
        key = (r.get("date"), r.get("hippo"), r.get("kosu_no"))
        ent = r.get(entity_key)
        if ent:
            race_entities[key].add(ent)
    entities = sorted({e for ents in race_entities.values() for e in ents})
    idx = {e: i for i, e in enumerate(entities)}
    n = len(entities)
    if n == 0:
        return [], np.zeros((0, 0))
    M = np.zeros((n, n), dtype=np.float32)
    for ents in race_entities.values():
        ent_list = list(ents)
        for i, a in enumerate(ent_list):
            for b in ent_list[i + 1:]:
                ia, ib = idx[a], idx[b]
                M[ia, ib] += 1
                M[ib, ia] += 1
    return entities, M


def _ppmi(M: np.ndarray) -> np.ndarray:
    """Positive Pointwise Mutual Information — Word2Vec'in matematiksel temeli."""
    if M.size == 0:
        return M
    row_sum = M.sum(axis=1, keepdims=True)
    col_sum = M.sum(axis=0, keepdims=True)
    total = M.sum()
    if total <= 0:
        return M
    # PPMI(i,j) = max(0, log( P(i,j) / (P(i)P(j)) ))
    with np.errstate(divide="ignore", invalid="ignore"):
        ppmi = np.log((M * total) / (row_sum @ col_sum + 1e-9) + 1e-9)
    return np.maximum(ppmi, 0)


def _svd_embed(M: np.ndarray, dim: int = 8) -> np.ndarray:
    """Truncated SVD → dim-boyutlu embedding."""
    if M.size == 0:
        return np.zeros((0, dim))
    # PPMI ile transform
    P = _ppmi(M)
    try:
        U, S, _ = np.linalg.svd(P, full_matrices=False)
        # First `dim` components weighted by sqrt(singular value)
        k = min(dim, len(S))
        embed = U[:, :k] * np.sqrt(S[:k])
        # Pad if necessary
        if k < dim:
            pad = np.zeros((embed.shape[0], dim - k))
            embed = np.hstack([embed, pad])
        return embed.astype(np.float32)
    except Exception as exc:
        logger.warning(f"SVD failed: {exc}")
        return np.zeros((M.shape[0], dim))


def build_entity_embedding(records: list[dict], entity_key: str,
                            dim: int = 8) -> dict:
    """Bir entity tipi (at/jokey/sire) için embedding dict."""
    entities, M = _build_cooccurrence(records, entity_key=entity_key)
    if not entities:
        return {}
    embed = _svd_embed(M, dim=dim)
    return {e: embed[i].tolist() for i, e in enumerate(entities)}


def build_horse_embedding(records, dim=8):
    return build_entity_embedding(records, "name", dim=dim)


def build_jockey_embedding(records, dim=8):
    return build_entity_embedding(records, "jockey", dim=dim)


def build_sire_embedding(records, dim=8):
    return build_entity_embedding(records, "sire", dim=dim)


def embedding_features(entity: Optional[str], embed_map: dict,
                       prefix: str, dim: int = 8) -> dict:
    """Bir entity için embedding'i flat feature dict'e dönüştür.

    Output: {prefix_0: float, ..., prefix_{dim-1}: float}.
    Eksik entity → tüm features 0.
    """
    vec = embed_map.get(entity) if entity else None
    if vec is None:
        return {f"{prefix}_{i}": 0.0 for i in range(dim)}
    return {f"{prefix}_{i}": float(vec[i]) for i in range(min(dim, len(vec)))}


def cosine_similarity(v1, v2) -> float:
    """İki vektörün kosinus benzerliği."""
    a, b = np.array(v1), np.array(v2)
    na, nb = np.linalg.norm(a), np.linalg.norm(b)
    if na < 1e-9 or nb < 1e-9:
        return 0.0
    return float(a @ b / (na * nb))
