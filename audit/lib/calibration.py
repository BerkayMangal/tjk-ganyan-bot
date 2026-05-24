"""Calibration measurement — Phase 0 STUB.

The bot stores `model_prob` per horse in `kupon.selections` and matches against
`leg_results.actual_num` in measurement_db. Joining those two gives the
(predicted_probability, binary_outcome) pairs needed for Brier / log-loss / ECE.

That join is NOT done by the bot today. The DB has a `calibration` JSONB
column on `matches` rows, but it is always empty (placeholder).

This module's job in Phase 0:
  - Document what's needed
  - Count how many pairs CAN be reconstructed from current data
  - Return placeholder metrics so the report's section 4 has a stable shape
  - Phase 1 will implement the actual binning + scoring without changing
    the report structure
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class CalibrationReport:
    available: bool = False
    reason: str = ""
    # Diagnostic counts — true even when metrics can't be computed
    kupons_with_model_prob: int = 0
    kupons_with_outcome: int = 0
    pairs_reconstructible: int = 0
    # Phase 1 fields — left blank in Phase 0
    n_bins: int = 10
    reliability_bins: list[dict] = field(default_factory=list)  # [{p_pred, p_actual, n}]
    brier_score: float | None = None
    log_loss: float | None = None
    ece: float | None = None


def _has_outcome(kupon: dict) -> bool:
    """A kupon has 'outcome' once its matches row is populated.

    The shapes we accept (DB / JSONL may differ):
      - kupon["match"] = {"kupon_won_full": bool, "leg_results": [...]}
      - kupon["leg_results"] = [...]
      - kupon["v7_meta"]["match"] = {...}
    """
    if isinstance(kupon.get("match"), dict):
        return True
    if isinstance(kupon.get("leg_results"), list) and kupon["leg_results"]:
        return True
    meta = kupon.get("v7_meta")
    if isinstance(meta, dict) and isinstance(meta.get("match"), dict):
        return True
    return False


def _has_model_prob(kupon: dict) -> bool:
    sels = kupon.get("selections")
    if not isinstance(sels, (list, dict)):
        return False
    # selections may be {leg_no: [horses]} or list of leg dicts.
    iterable = sels.values() if isinstance(sels, dict) else sels
    for leg in iterable:
        horses = leg.get("horses") if isinstance(leg, dict) else leg
        if not isinstance(horses, list):
            continue
        for h in horses:
            if isinstance(h, dict) and isinstance(h.get("model_prob"), (int, float)):
                return True
    return False


def build_calibration_report(kupons: list[dict]) -> CalibrationReport:
    rep = CalibrationReport()
    if not kupons:
        rep.reason = "no kupon records in window"
        return rep

    for k in kupons:
        if _has_model_prob(k):
            rep.kupons_with_model_prob += 1
        if _has_outcome(k):
            rep.kupons_with_outcome += 1
        if _has_model_prob(k) and _has_outcome(k):
            rep.pairs_reconstructible += 1

    if rep.pairs_reconstructible == 0:
        rep.reason = (
            "no kupons have BOTH model_prob in selections AND a populated matches/leg_results row — "
            "calibration cannot be computed from current data"
        )
        return rep

    # Phase 1 implementation goes here:
    #   - join model_prob ↔ outcome per (kupon_id, leg, horse_num)
    #   - bin predicted_prob into deciles, compute hit-rate per bin
    #   - compute Brier = mean((p - y)^2)
    #   - compute ECE = sum(|p_bin_avg - actual_rate_bin| * n_bin / N)
    #   - compute log-loss with eps clipping
    rep.available = False
    rep.reason = (
        f"{rep.pairs_reconstructible} pairs reconstructible — metrics computation deferred to Phase 1"
    )
    return rep


# Section 4 narrative used by the orchestrator. Kept here so the wording
# lives with the data it documents.
CALIBRATION_NARRATIVE = """\
**Mevcut durum:** Kalibrasyon ölçümü için gereken iki parça:
1. **Tahmin olasılığı (`model_prob`)** — bot bunu `kupons.selections[].model_prob`
   içine yazıyor (her at için).
2. **Gerçek sonuç (`actual_outcome`)** — bot bunu `matches.leg_results[]` veya
   eşdeğeri içine yazıyor (her ayak için kazanan at numarası).

**Eksik:** İki tarafı birleştiren (kupon_id × leg × horse_num) join'i hiçbir
yerde yapılmıyor. `measurement_db.matches.calibration` JSONB kolonu var ama
**boş bırakılıyor** (placeholder).

**Reliability diagram + Brier + ECE:** Phase 1 görevidir — bu sürümde stub.
Rapor yapısı (bölüm numaraları, başlık ağacı) Phase 1'de DEĞİŞMEYECEK; sadece
şu anki "EKSİK VERİ" not'ları sayısal değerlerle dolacak.
"""
