"""Cross-source validation.

Multi-source veriyi karşılaştır (TJK + theracingapi + Betfair) ve:
  1) Inconsistencies tespit et (X kaynağında at adı, Y'de farklı)
  2) Confidence weighting: hangi source güvenilir
  3) Source agreement signal: model tahminini güçlendir/zayıflat

API
---
- `match_horse_across_sources(name, sources) -> MatchResult`
- `compare_odds_across_sources(odds_dict) -> ConsistencyMetric`
"""
from __future__ import annotations

import unicodedata
from dataclasses import dataclass
from typing import Iterable, Mapping, Optional


def normalize_name(name: str) -> str:
    """Aggressive name normalization for cross-source matching.

    'RABOVO' = 'RABOVO' = 'Rabovo' = 'rabovo'
    'BAY NALÇAKAN' = 'BAY NALCAKAN'
    """
    if not name:
        return ""
    s = str(name).strip().upper()
    # Strip accents (Turkish-aware)
    replacements = {"Ç": "C", "Ğ": "G", "İ": "I", "Ş": "S",
                    "Ü": "U", "Ö": "O", "I": "I"}
    for src, dst in replacements.items():
        s = s.replace(src, dst)
    # Unicode normalize
    s = unicodedata.normalize("NFKD", s)
    s = "".join(c for c in s if not unicodedata.combining(c))
    # Collapse whitespace
    s = " ".join(s.split())
    return s


@dataclass
class MatchResult:
    """Cross-source matching result for one horse."""
    target_name: str
    normalized: str
    matches: dict  # source_name -> raw_record
    confidence: float = 0.0  # 0..1


def match_horse_across_sources(
    target_name: str,
    sources: Mapping[str, list[Mapping]],
    name_keys: Iterable[str] = ("horse_name", "name", "at_adi"),
) -> MatchResult:
    """Bir atı her source'ta ara, eşleşen kaydı döndür.

    `sources`: {source_name: list_of_records}
    `name_keys`: olası at-adı anahtarları (kaynak farklı isimler kullanır)

    Returns MatchResult with confidence proportional to matches found.
    """
    target_norm = normalize_name(target_name)
    matches: dict[str, Mapping] = {}
    for source_name, records in sources.items():
        for rec in records:
            if not isinstance(rec, Mapping):
                continue
            for k in name_keys:
                if k in rec:
                    if normalize_name(str(rec[k])) == target_norm:
                        matches[source_name] = rec
                        break
            if source_name in matches:
                break
    # Confidence: matches / total sources
    conf = len(matches) / max(1, len(sources))
    return MatchResult(
        target_name=target_name,
        normalized=target_norm,
        matches=matches,
        confidence=conf,
    )


@dataclass
class ConsistencyMetric:
    """Multiple sources arası tahmin tutarlılığı."""
    n_sources: int
    mean_prob: Optional[float]
    std_prob: Optional[float]
    min_prob: Optional[float]
    max_prob: Optional[float]
    agreement: str   # 'high', 'medium', 'low'


def compare_predictions_across_sources(
    predictions: dict[str, float],
) -> ConsistencyMetric:
    """Multiple source'tan gelen tahminleri karşılaştır.

    `predictions`: {source_name: probability}
    """
    vals = [v for v in predictions.values() if v is not None]
    if not vals:
        return ConsistencyMetric(
            n_sources=0, mean_prob=None, std_prob=None,
            min_prob=None, max_prob=None, agreement="unknown",
        )
    import math
    n = len(vals)
    mean = sum(vals) / n
    var = sum((v - mean) ** 2 for v in vals) / n if n > 1 else 0.0
    std = math.sqrt(var)
    if std < 0.05:
        agreement = "high"
    elif std < 0.15:
        agreement = "medium"
    else:
        agreement = "low"
    return ConsistencyMetric(
        n_sources=n,
        mean_prob=mean,
        std_prob=std,
        min_prob=min(vals),
        max_prob=max(vals),
        agreement=agreement,
    )
