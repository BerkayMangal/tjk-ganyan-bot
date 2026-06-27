"""V7 pipeline'a forward-looking feature augmentation.

Bu modül V7 ndcg@4 modeline DOKUNMAZ. Sadece her at için yeni feature
dict'i hesaplar ve dashboard / debug çıktısına ekler. V8 retrain'inde
bu feature'lar training data'ya dahil edilecek; şimdilik **shadow**
olarak gözlem.

Berkay'ın hipotezi: bu feature'lar modelin "geçmiş özet" sınırlamasını
yıkar. Dashboard'da yan-yana mevcut V7 MP + forward signals görünür.

API
---
- `compute_horse_forward_features(horse, history, ref_date)` → dict
- `enrich_pool(pool, history_lookup)` → pool (in-place augment)
"""
from __future__ import annotations

from dataclasses import asdict
from typing import Callable, Iterable, Mapping, Optional

from .recency import compute_recency_features
from .recovery import compute_recovery_features
from .trajectory import compute_trajectory_features
from .glicko import GlickoLedger, GlickoRating, predict_top_n_probability


def compute_horse_forward_features(
    horse_name: str,
    history: list[Mapping],
    ref_date: Optional[str] = None,
    glicko_ledger: Optional[GlickoLedger] = None,
) -> dict:
    """Tek atın tarihsel kayıt listesinden forward feature dict.

    `history`: list of dicts, en taze ÖNCE. Beklenen alanlar:
        - finish (or derece_no) → int  (bitiş sırası)
        - date or race_date → str
        - kosu_cinsi → str
        - mesafe → int

    `ref_date`: None → bugün UTC

    Returns dict (JSON-safe). NEVER raises.
    """
    out: dict = {
        "horse_name": horse_name,
        "history_n": len(history),
    }
    try:
        # 1) Recency (positions için finish key'i deneyelim)
        positions = []
        for rec in history:
            if not isinstance(rec, Mapping):
                positions.append(None)
                continue
            for k in ("finish", "derece_no", "siralama"):
                if rec.get(k) is not None:
                    positions.append(rec[k])
                    break
            else:
                positions.append(None)
        recency = compute_recency_features(positions, target_top=4)
        out["recency"] = asdict(recency)
    except Exception as exc:
        out["recency_error"] = repr(exc)[:120]

    try:
        # 2) Trajectory
        trajectory = compute_trajectory_features(history)
        out["trajectory"] = asdict(trajectory)
    except Exception as exc:
        out["trajectory_error"] = repr(exc)[:120]

    try:
        # 3) Recovery
        recovery = compute_recovery_features(history, ref_date)
        out["recovery"] = asdict(recovery)
    except Exception as exc:
        out["recovery_error"] = repr(exc)[:120]

    # 4) Glicko rating (if ledger provided)
    if glicko_ledger is not None:
        try:
            r = glicko_ledger.get(horse_name)
            out["glicko"] = {
                "rating": r.rating,
                "rd": r.rd,
                "volatility": r.volatility,
                "rating_low_ci": r.rating - 2 * r.rd,    # 95% CI
                "rating_high_ci": r.rating + 2 * r.rd,
            }
        except Exception as exc:
            out["glicko_error"] = repr(exc)[:120]

    return out


def forward_signal_summary(features: dict) -> dict:
    """Forward feature dict → tek satırlık özet, dashboard için.

    Çıktı:
      {
        "trend": "improving" | "declining" | "stable" | "unknown",
        "form_recent_top4": float | None,
        "form_career_top4": float | None,
        "recovery_status": str,
        "comeback_risk": float | None,
        "glicko_rating": float | None,
        "glicko_certainty": str,  # "high", "medium", "low"
        "verdict": str,
      }
    """
    recency = features.get("recency") or {}
    trajectory = features.get("trajectory") or {}
    recovery = features.get("recovery") or {}
    glicko = features.get("glicko") or {}

    # Trend interpretation
    ft = trajectory.get("finish_trend")
    if ft is None:
        trend = "unknown"
    elif ft >= 0.2:
        trend = "improving"
    elif ft <= -0.2:
        trend = "declining"
    else:
        trend = "stable"

    # Glicko certainty bucket (RD: <100=high, <200=medium, else low)
    rd = glicko.get("rd")
    if rd is None:
        certainty = "unknown"
    elif rd < 100:
        certainty = "high"
    elif rd < 200:
        certainty = "medium"
    else:
        certainty = "low"

    # Verdict — simple heuristic combining signals
    pieces = []
    rec = recency.get("last5_top4")
    if rec is not None and rec >= 0.6:
        pieces.append("form son 5'te güçlü")
    elif rec is not None and rec <= 0.2:
        pieces.append("form son 5'te zayıf")
    if trend == "improving":
        pieces.append("trajectory yükseliyor")
    elif trend == "declining":
        pieces.append("trajectory düşüyor")
    if recovery.get("is_long_mola"):
        pieces.append("uzun mola sonrası comeback")
    elif recovery.get("is_fresh"):
        pieces.append("taze form (14-30 gün)")
    if certainty == "high" and glicko.get("rating"):
        pieces.append(f"Glicko {glicko['rating']:.0f}±{rd:.0f} (güvenilir)")

    return {
        "trend": trend,
        "form_recent_top4": rec,
        "form_career_top4": recency.get("shrunk_top4_career"),
        "recency_gap": recency.get("gap_recent5_career_top4"),
        "recovery_status": recovery.get("bucket", "unknown"),
        "comeback_risk": recovery.get("comeback_score"),
        "glicko_rating": glicko.get("rating"),
        "glicko_rd": glicko.get("rd"),
        "glicko_certainty": certainty,
        "verdict": "; ".join(pieces) if pieces else "yetersiz veri",
    }
