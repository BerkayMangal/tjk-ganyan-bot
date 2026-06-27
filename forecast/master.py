"""Master orchestrator — tüm fazları tek atın forward forecast'ına bağlar.

Berkay (2026-06-27): "model gecmis dataya bakiyor ama oyle bir sonuc
cikiyorki yani ileriye yonelik bir sonuc degil".

Bu modül cevabın **tek noktası**: bir at için forward-looking
forecast üret. İçeride 5 faz birlikte çalışır:

  FAZ A → recency, trajectory, recovery, Glicko ratings
  FAZ B → sequence embedding, stacking meta
  FAZ C → pace style, race-day drift dynamics
  FAZ D → counterfactual queries (opsiyonel sorgu zamanı)
  FAZ E → cross-source validation (multi-source agreement)

Tek API: `forecast_horse(name, history, race_context, ...)` → tüm
forward sinyalleri içeren dict döner. Dashboard / Telegram / PDF
hepsi bunu kullanabilir.

NEVER raises. Eksik veri kategorize edilir, None gönderir.
"""
from __future__ import annotations

import logging
from dataclasses import asdict
from typing import Iterable, Mapping, Optional

from .integration import (
    compute_horse_forward_features, forward_signal_summary,
)
from .pace.pace import infer_pace_style
from .pace.dynamics import (
    classify_market_move, compute_drift_metrics,
    confidence_from_volatility, steam_move_advantage,
)
from .sequence.lightweight import encode_career
from .sequence.stacking import StackingMeta
from .glicko import GlickoLedger

logger = logging.getLogger(__name__)


def forecast_horse(
    name: str,
    history: list[Mapping],
    race_context: Optional[Mapping] = None,
    drift_snapshots: Optional[list[float]] = None,
    glicko_ledger: Optional[GlickoLedger] = None,
    v7_model_prob: Optional[float] = None,
    stacking_meta: Optional[StackingMeta] = None,
    ref_date: Optional[str] = None,
) -> dict:
    """Tek at için forward-looking forecast — tüm fazları birleştirir.

    Parameters
    ----------
    name : str
        At adı.
    history : list[dict]
        Geçmiş koşu kayıtları (EN TAZE ÖNCE).
    race_context : dict, optional
        Yarış bağlamı: distance, going, race_class, field_size.
    drift_snapshots : list[float], optional
        AGF time series (chronological).
    glicko_ledger : GlickoLedger, optional
        Persistent rating defteri.
    v7_model_prob : float, optional
        V7 ranker'ın mevcut tahmini (mp).
    stacking_meta : StackingMeta, optional
        Yoksa default weights kullanılır.
    ref_date : str, optional
        Recovery hesabı için referans (None → today).

    Returns
    -------
    dict
        Tüm forward signals + composite refined probability.
        NEVER raises.
    """
    out: dict = {"horse_name": name, "history_n": len(history)}

    # ---- FAZ A: Forward foundation -------------------------------------
    try:
        faza = compute_horse_forward_features(
            name, history, ref_date=ref_date,
            glicko_ledger=glicko_ledger,
        )
        out["faza"] = faza
        out["summary"] = forward_signal_summary(faza)
    except Exception as exc:
        out["faza_error"] = repr(exc)[:160]
        logger.warning("faza error %s: %s", name, exc)

    # ---- FAZ B: Sequence embedding -------------------------------------
    try:
        embedding = encode_career(history)
        out["fazb"] = {
            "n_records": embedding.n_records,
            "strength": embedding.strength,
            "top4_rate_ewma": embedding.top4_rate,
            "top1_rate_ewma": embedding.top1_rate,
            "finish_avg": embedding.finish_avg,
            "finish_recent": embedding.finish_recent,
            "finish_std": embedding.finish_std,
        }
    except Exception as exc:
        out["fazb_error"] = repr(exc)[:160]
        embedding = None

    # ---- FAZ C: Pace style + AGF drift ---------------------------------
    try:
        pace = infer_pace_style(history)
        out["fazc_pace"] = {
            "primary": pace.primary,
            "confidence": pace.confidence,
            "front_bias": pace.front_bias,
            "closer_bias": pace.closer_bias,
        }
    except Exception as exc:
        out["fazc_pace_error"] = repr(exc)[:160]

    if drift_snapshots and len(drift_snapshots) >= 2:
        try:
            drift = compute_drift_metrics(drift_snapshots)
            move_class = classify_market_move(drift)
            steam_adv = steam_move_advantage(drift)
            volatility_conf = confidence_from_volatility(drift.volatility, 1.0)
            out["fazc_drift"] = {
                "abs_drift": drift.abs_drift,
                "rel_drift": drift.rel_drift,
                "volatility": drift.volatility,
                "direction_consistency": drift.direction_consistency,
                "move_class": move_class,
                "steam_advantage": steam_adv,
                "volatility_confidence_factor": volatility_conf,
            }
        except Exception as exc:
            out["fazc_drift_error"] = repr(exc)[:160]

    # ---- Refined probability via stacking meta -------------------------
    try:
        meta = stacking_meta or StackingMeta()
        features = {
            "v7_mp": v7_model_prob,
            "strength": embedding.strength if embedding else None,
            "glicko_rating": (
                (out.get("faza") or {}).get("glicko", {}).get("rating")
            ),
            "recency_gap": (
                (out.get("summary") or {}).get("recency_gap")
            ),
            "comeback_risk": (
                (out.get("summary") or {}).get("comeback_risk")
            ),
            "trend_signal": (
                (out.get("faza") or {}).get("trajectory", {}).get("finish_trend")
            ),
        }
        refined = meta.predict(features)
        out["refined_probability"] = refined
        out["stacking_features"] = features
    except Exception as exc:
        out["refined_error"] = repr(exc)[:160]

    return out


def forecast_race(
    horses: Iterable[Mapping],
    history_lookup: callable,
    race_context: Optional[Mapping] = None,
    glicko_ledger: Optional[GlickoLedger] = None,
    drift_lookup: Optional[callable] = None,
    stacking_meta: Optional[StackingMeta] = None,
    ref_date: Optional[str] = None,
) -> list[dict]:
    """Bir yarışın TÜM atları için forward forecast.

    Parameters
    ----------
    horses : iterable of dict
        Her at: at least {horse_name, model_prob}
    history_lookup : callable(name) → list[dict]
        At adından history listesi döndürür
    race_context : dict
        Distance, going, race_class
    drift_lookup : callable(name) → list[float] or None
        At adından AGF time-series döndürür (varsa)
    """
    out = []
    for h in horses:
        if not isinstance(h, Mapping):
            continue
        name = h.get("horse_name") or h.get("name") or "?"
        try:
            history = history_lookup(name) or []
        except Exception:
            history = []
        drift = None
        if drift_lookup is not None:
            try:
                drift = drift_lookup(name) or None
            except Exception:
                drift = None
        forecast = forecast_horse(
            name=name,
            history=history,
            race_context=race_context,
            drift_snapshots=drift,
            glicko_ledger=glicko_ledger,
            v7_model_prob=h.get("model_prob") or h.get("mp"),
            stacking_meta=stacking_meta,
            ref_date=ref_date,
        )
        forecast["horse_no"] = h.get("horse_no") or h.get("horse_number")
        forecast["v7_model_prob"] = h.get("model_prob") or h.get("mp")
        out.append(forecast)
    return out


def quick_summary(forecast: Mapping) -> str:
    """Tek atın forecast'ından insan-okuyabilir kısa özet."""
    summary = forecast.get("summary") or {}
    refined = forecast.get("refined_probability")
    parts = []
    name = forecast.get("horse_name", "?")
    parts.append(f"⚡ {name}")
    if refined is not None:
        parts.append(f"refined P={refined:.3f}")
    trend = summary.get("trend")
    if trend and trend != "unknown":
        parts.append(f"trend={trend}")
    recov = summary.get("recovery_status")
    if recov and recov != "unknown":
        parts.append(f"recovery={recov}")
    verdict = summary.get("verdict")
    if verdict and verdict != "yetersiz veri":
        parts.append(f"verdict={verdict}")
    return " | ".join(parts)
