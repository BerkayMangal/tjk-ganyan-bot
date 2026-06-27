"""Counterfactual queries — 'what if' forward-looking sorgular.

Berkay'ın asıl arzuladığı: "Bu jokey/at/parkur kombinasyonu olmasaydı
ne olurdu?" gibi sorulara cevap. Bu modül feature perturbation ile
karşıt-olgu tahmini yapar.

Yaklaşım:
  1) Tahmin fonksiyonu (V7 model + stacking meta)
  2) Feature dictionary'i değiştir
  3) Yeniden tahmin et
  4) Δ probability = causal effect

Bu modül model-agnostic — herhangi bir scoring function alabilir.

API
---
- `counterfactual_probability(predictor, base_features, perturbation)`
- `feature_importance_via_perturbation(predictor, features, key)`
- `whatif_jockey_swap(predictor, base, jockey_a_stats, jockey_b_stats)`
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping, Optional


@dataclass
class CounterfactualResult:
    """Counterfactual sorgu sonucu."""
    base_prob: float                 # mevcut tahmin
    counterfactual_prob: float       # perturbation sonrası tahmin
    delta: float                     # cf - base
    interpretation: str              # "+X%", "-X%", "no change"


def counterfactual_probability(
    predictor: Callable[[Mapping], float],
    base_features: Mapping,
    perturbation: Mapping,
) -> CounterfactualResult:
    """Tahminci + base features + perturbation → counterfactual sonuç.

    `predictor`: features dict → probability (0..1)
    `base_features`: original feature dict
    `perturbation`: değiştirilecek feature'lar (key: new_value)

    NEVER raises.
    """
    try:
        base_p = float(predictor(base_features))
    except Exception:
        base_p = 0.5
    cf_features = dict(base_features)
    cf_features.update(perturbation)
    try:
        cf_p = float(predictor(cf_features))
    except Exception:
        cf_p = base_p
    delta = cf_p - base_p
    if abs(delta) < 0.01:
        interp = "no change"
    elif delta > 0:
        interp = f"+{abs(delta) * 100:.1f}%"
    else:
        interp = f"-{abs(delta) * 100:.1f}%"
    return CounterfactualResult(
        base_prob=base_p,
        counterfactual_prob=cf_p,
        delta=delta,
        interpretation=interp,
    )


def feature_importance_via_perturbation(
    predictor: Callable[[Mapping], float],
    base_features: Mapping,
    feature_key: str,
    new_values: list,
) -> list[CounterfactualResult]:
    """Bir feature için multiple counterfactual değer dene.

    Returns list of CounterfactualResult — her bir yeni değer için.
    """
    return [
        counterfactual_probability(
            predictor, base_features, {feature_key: v}
        )
        for v in new_values
    ]


def whatif_jockey_swap(
    predictor: Callable[[Mapping], float],
    base_features: Mapping,
    jockey_a_stats: Mapping,
    jockey_b_stats: Mapping,
) -> CounterfactualResult:
    """Yaygın counterfactual: jokey değişimi.

    `jockey_a_stats`: bu atın şu anki jokey istatistikleri
    `jockey_b_stats`: alternatif jokey istatistikleri

    Beklenen anahtarlar:
      - jockey_overall_top4 (float)
      - jockey_cond_top4 (float)
      - jockey_cond_win (float)

    Returns: counterfactual P(top4 | jockey_b) vs current P(top4).
    """
    perturbation = {}
    for key in ("jockey_overall_top4", "jockey_cond_top4",
                "jockey_cond_win"):
        if key in jockey_b_stats:
            perturbation[key] = jockey_b_stats[key]
    return counterfactual_probability(predictor, base_features, perturbation)


def whatif_distance_change(
    predictor: Callable[[Mapping], float],
    base_features: Mapping,
    new_distance: int,
) -> CounterfactualResult:
    """At başka mesafede koşsaydı ne olurdu?"""
    return counterfactual_probability(
        predictor, base_features, {"distance": new_distance}
    )


def whatif_class_change(
    predictor: Callable[[Mapping], float],
    base_features: Mapping,
    new_class_score: float,
) -> CounterfactualResult:
    """At daha düşük/yüksek sınıfta koşsaydı?"""
    return counterfactual_probability(
        predictor, base_features, {"class_score": new_class_score}
    )
