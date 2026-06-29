"""Race-level META features — atın kendi başına değil field içindeki yeri.

Berkay (2026-06-29): 'olmayan şeylere bakmalıyız' → field-relative
features, V7'de ve V8'de YOK olan "yarışın karakteri" sinyalleri.

Atın absolute skor (örn glicko 1500) zayıf bir sinyal:
  • 22-atlı G1'de glicko 1500 = ortalama
  • 8-atlı KV-9'da glicko 1500 = lider
→ Field içindeki GÖRECELI skor çok daha predictive.

API
---
- `compute_field_meta(rows)` → dict (per-race, 8 metric)
- `add_relative_features(horse_feat, field_meta)` → enriched feat

Pure-Python (numpy opsiyonel, default math).
"""
from __future__ import annotations

import math
from typing import Iterable


def _safe_div(a, b, default=1.0):
    return (a / b) if (b and abs(b) > 1e-9) else default


def _mean(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    return sum(xs) / len(xs) if xs else 0.0


def _std(xs):
    xs = [x for x in xs if isinstance(x, (int, float))]
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    return math.sqrt(sum((x - m) ** 2 for x in xs) / len(xs))


def _entropy(rates):
    """Shannon entropy of pace style distribution (4 kategori)."""
    rates = [r for r in rates if r > 0]
    if not rates:
        return 0.0
    total = sum(rates)
    ps = [r / total for r in rates]
    return -sum(p * math.log(p + 1e-9) for p in ps)


def compute_field_meta(rows: Iterable[dict]) -> dict:
    """Bir yarış için at-bazlı feature listesi → field meta.

    Args:
        rows: list of horse feature dicts (V8 train_real._build_features_for_horse
              çıktısı; her at için Glicko + recency + career stats vs.)
    Returns:
        dict (8 metric, hepsi float):
          field_glicko_mean, field_glicko_std, field_glicko_max,
          field_top4_rate_mean, field_recency_form_mean,
          field_avg_finish_mean, field_size, field_pace_entropy
    """
    rows = list(rows)
    if not rows:
        return {}
    glickos = [r.get("glicko_rating") for r in rows]
    top4s = [r.get("career_top4_rate") for r in rows]
    recencies = [r.get("recency_w_top4_85") for r in rows]
    finishes = [r.get("career_avg_finish") for r in rows]
    pace_counts = [
        sum(1 for r in rows if r.get("pace_front")),
        sum(1 for r in rows if r.get("pace_stalker")),
        sum(1 for r in rows if r.get("pace_mid")),
        sum(1 for r in rows if r.get("pace_closer")),
    ]
    return {
        "field_glicko_mean": _mean(glickos),
        "field_glicko_std": _std(glickos),
        "field_glicko_max": max([g for g in glickos
                                  if isinstance(g, (int, float))],
                                 default=1500),
        "field_top4_rate_mean": _mean(top4s),
        "field_recency_form_mean": _mean(recencies),
        "field_avg_finish_mean": _mean(finishes),
        "field_size": len(rows),
        "field_pace_entropy": _entropy(pace_counts),
    }


def add_relative_features(horse_feat: dict, field_meta: dict) -> dict:
    """At feature'larına field-relative metrics ekle (in-place).

    Yeni features (8 adet):
      rel_glicko_to_mean — atın glicko / field ort
      rel_glicko_to_max  — atın glicko / field max
      glicko_gap_to_max  — max - atın glicko (kayıp)
      rel_top4_to_mean   — atın top4 / field ort
      rel_recency_to_mean — atın recency / field ort
      rel_avg_finish_diff — atın avg_finish - field ort (negatif=iyi)
      is_top3_glicko_in_field — at field'in top-3 glicko'sunda mı (0/1)
      field_competitiveness — field std/mean (homojenlik tersi)
    """
    if not field_meta:
        return horse_feat

    g = horse_feat.get("glicko_rating") or 1500
    t4 = horse_feat.get("career_top4_rate") or 0
    rec = horse_feat.get("recency_w_top4_85") or 0
    af = horse_feat.get("career_avg_finish") or 5.0

    horse_feat["rel_glicko_to_mean"] = _safe_div(
        g, field_meta.get("field_glicko_mean", 1500))
    horse_feat["rel_glicko_to_max"] = _safe_div(
        g, field_meta.get("field_glicko_max", 1500))
    horse_feat["glicko_gap_to_max"] = (
        field_meta.get("field_glicko_max", 1500) - g)
    horse_feat["rel_top4_to_mean"] = _safe_div(
        t4, field_meta.get("field_top4_rate_mean", 0.3))
    horse_feat["rel_recency_to_mean"] = _safe_div(
        rec, field_meta.get("field_recency_form_mean", 0.3))
    horse_feat["rel_avg_finish_diff"] = (
        af - field_meta.get("field_avg_finish_mean", 5.0))
    horse_feat["field_competitiveness"] = _safe_div(
        field_meta.get("field_glicko_std", 0),
        field_meta.get("field_glicko_mean", 1500), 0)
    # Top-3 in field glicko?
    horse_feat["is_top3_glicko_in_field"] = 0  # caller compute eder
    # Field-wide stats (her at için aynı)
    horse_feat["field_size_meta"] = field_meta.get("field_size", 10)
    horse_feat["field_pace_entropy"] = field_meta.get(
        "field_pace_entropy", 0)
    return horse_feat


def mark_top_k_glicko(rows: list[dict], k: int = 3) -> None:
    """is_top3_glicko_in_field flag'ini in-place set et."""
    sorted_by_g = sorted(
        rows, key=lambda r: -(r.get("glicko_rating") or 0))
    top_k_set = set(id(r) for r in sorted_by_g[:k])
    for r in rows:
        r["is_top3_glicko_in_field"] = 1 if id(r) in top_k_set else 0
