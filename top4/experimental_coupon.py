"""BERKAY BİLİMSEL DENEME TOP4 — experimental coupon builder.

Builds an explicitly-labeled SHADOW/research coupon view using the
scientific Top-4 framework. NOT a production betting recommendation.
NOT auto-betting. NOT a replacement for V7.

Public API
----------
- `build_berkay_scientific_top4_coupon(race_snapshot, agf_snapshot=None, cutoff="latest")`
  returns a structured dict (see docs/BERKAY_BILIMSEL_DENEME_TOP4.md).
- `EXPERIMENTAL_LABEL`, `DISCLAIMER`: constants.
- `is_shadow_enabled()`, `is_telegram_enabled()`, `is_forward_log_enabled()`:
  env-flag accessors.

Inputs are permissive. Missing AGF / missing model rank / missing horse
names are tolerated. The builder NEVER raises; on internal error it
returns `engine_status="error"` with an empty coupon and a note.
"""
from __future__ import annotations

import hashlib
import json
import os
import traceback
from dataclasses import asdict
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional

from .agf_drift import compute_drift, drift_reason_for
from .calibration import calibrate_race
from .candidate_sets import coverage_required_for_target
from .no_bet_gate import decide
from .roles import (
    ROLE_AVOID, ROLE_BANKER, ROLE_CHAOS, ROLE_CORE, ROLE_NO_SIGNAL, ROLE_SPREAD,
    assign_roles,
)
from .ticket_builder import build as build_ticket
from .uncertainty import evaluate

EXPERIMENTAL_LABEL = "BERKAY_BILIMSEL_DENEME_TOP4"
EXPERIMENTAL_LABEL_DISPLAY = "BERKAY BİLİMSEL DENEME TOP4"
DISCLAIMER = (
    "Deneme / shadow kuponudur. Resmi bot kuponu değildir. "
    "Otomatik bahis değildir."
)

FLAG_SHADOW = "TJK_TOP4_BERKAY_SHADOW"
FLAG_TELEGRAM = "TJK_TOP4_BERKAY_TELEGRAM"
FLAG_FORWARD_LOG = "TJK_TOP4_FORWARD_LOG"

VALID_CUTOFFS = {"morning", "T-15", "T-5", "T-3", "latest"}


def is_shadow_enabled() -> bool:
    return os.getenv(FLAG_SHADOW, "0") == "1"


def is_telegram_enabled() -> bool:
    return os.getenv(FLAG_TELEGRAM, "0") == "1"


def is_forward_log_enabled() -> bool:
    return os.getenv(FLAG_FORWARD_LOG, "0") == "1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _snapshot_hash(payload: Mapping) -> str:
    blob = json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    return hashlib.sha256(blob).hexdigest()[:16]


def _coerce_int(x: Any, default: int = 0) -> int:
    try:
        return int(x)
    except (TypeError, ValueError):
        return default


def _coerce_float(x: Any) -> Optional[float]:
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _label_variance(uncertainty_level: str, field_size: int, required_set: int) -> str:
    if uncertainty_level in {"NO_BET", "CHAOS"}:
        return "HIGH"
    if required_set >= 7 or field_size >= 14:
        return "HIGH"
    if required_set <= 4 and field_size <= 10:
        return "LOW"
    return "MEDIUM"


def _empty_coupon(race_label: str, cutoff: str, reason: str,
                  generated_at: Optional[str] = None) -> dict:
    return {
        "label": EXPERIMENTAL_LABEL,
        "label_display": EXPERIMENTAL_LABEL_DISPLAY,
        "race_id": race_label,
        "race_label": race_label,
        "race_time": "",
        "generated_at": generated_at or _now_iso(),
        "agf_snapshot_time": None,
        "prediction_cutoff": cutoff,
        "model_version": "v7_ndcg4+top4cal",
        "feature_snapshot_hash": "0" * 16,
        "confidence": "NO_BET",
        "variance": "HIGH",
        "recommended_mode": "NO_BET",
        "bankers": [], "core": [], "spread": [], "chaos": [], "avoid": [],
        "candidate_set": [],
        "small_ticket": {}, "balanced_ticket": {}, "wide_ticket": {},
        "no_bet_reason": reason,
        "notes": [reason],
        "engine_status": "error",
        "disclaimer": DISCLAIMER,
        "horses": [],
    }


def _build_ticket_proposal(decision, roles, candidate_horses, mode_override: Optional[str] = None) -> dict:
    """Return a JSON-safe ticket dict for a given mode override.
    Re-runs ticket builder with a fake decision object so we can emit
    small + balanced + wide all at once for the experimental view.
    """
    from .no_bet_gate import NoBetDecision
    if decision.skip:
        return {
            "skip": True,
            "mode": "no_bet",
            "horses": [],
            "estimated_combinations": 0,
            "stake_cap_suggestion": "none",
            "reasons": list(decision.reasons),
        }
    target_mode = mode_override or decision.mode
    fake_dec = NoBetDecision(False, target_mode, list(decision.reasons))
    t = build_ticket(fake_dec, roles)
    return {
        "skip": t.skip,
        "mode": t.mode,
        "banker": t.banker,
        "core": t.core,
        "spread": t.spread,
        "chaos": t.chaos,
        "horse_total": t.horse_total,
        "estimated_combinations": t.estimated_combinations,
        "stake_cap_suggestion": t.stake_cap_suggestion,
        "reasons": t.reasons,
        "is_proposal_only": True,
    }


def build_berkay_scientific_top4_coupon(
    race_snapshot: Mapping,
    agf_snapshot: Optional[Mapping] = None,
    cutoff: str = "latest",
    mode: str = "shadow",
) -> dict:
    """Construct one BERKAY BİLİMSEL DENEME TOP4 coupon dict for one race.

    Parameters
    ----------
    race_snapshot : dict
        Required keys: `race_label` (str), `horses` (list[dict]).
        Each horse: `horse_no`, `mp` required; `horse_name`, `agf`,
        `agf_open`, `tier`, `breed`, `race_class`, `model_rank`,
        `hippodrome` optional.
        Optional top-level: `race_id`, `race_time`, `field_size`,
        `hippodrome`, `breed`, `race_class`.
    agf_snapshot : dict | None
        Optional dict with keys `open` and `now`, each a sub-dict of
        `{ts, horses: {horse_no: pct}}`.
    cutoff : one of `morning`, `T-15`, `T-5`, `T-3`, `latest`.
    mode : "shadow" (no side-effects) | "live" (caller may write log).

    Returns a JSON-safe dict. NEVER raises.
    """
    race_label = str(race_snapshot.get("race_label")
                     or race_snapshot.get("race_id") or "race")
    cutoff = cutoff if cutoff in VALID_CUTOFFS else "latest"
    try:
        horses_raw = list(race_snapshot.get("horses") or [])
        if not horses_raw:
            return _empty_coupon(race_label, cutoff,
                                 reason="boş yarış (horses=[])")

        normalized: list[dict] = []
        for h in horses_raw:
            normalized.append({
                "horse_no": _coerce_int(h.get("horse_no"), 0),
                "horse_name": str(h.get("horse_name") or "?"),
                "mp": _coerce_float(h.get("mp")) or 0.0,
                "agf": _coerce_float(h.get("agf")
                                     or h.get("agf_now")
                                     or h.get("agf_value")),
                "agf_open": _coerce_float(h.get("agf_open")
                                          or h.get("agf_morning")),
                "tier": str(h.get("tier") or ""),
                "breed": str(h.get("breed") or race_snapshot.get("breed") or ""),
                "race_class": str(h.get("race_class")
                                  or race_snapshot.get("race_class") or ""),
                "hippodrome": str(h.get("hippodrome")
                                  or race_snapshot.get("hippodrome") or ""),
                "model_rank": _coerce_int(h.get("model_rank") or 0, 0) or None,
            })

        field_size = len(normalized)

        # calibration
        cal_rows = calibrate_race(normalized)
        cal_map = {c.horse_no: c for c in cal_rows}
        for n in normalized:
            c = cal_map.get(n["horse_no"])
            n["p_top4_cal"] = c.p_top4_cal if c else None
            n["p_win_cal"] = c.p_win_cal if c else None
            n["p_top4_method"] = c.method if c else "insufficient_data"

        # drift
        drift_open = (agf_snapshot or {}).get("open")
        drift_now = (agf_snapshot or {}).get("now")
        drift = compute_drift(normalized, drift_open, drift_now)
        drift_map = {d.horse_no: d for d in drift.rows}

        # roles
        required = coverage_required_for_target(normalized, target=0.80)
        unc = evaluate(normalized, required_set_size=required)
        roles = assign_roles(normalized, field_size=field_size,
                             uncertainty=unc.level)
        # AGF drift can add a conservative reason to existing roles
        for role in roles:
            d = drift_map.get(role.horse_no)
            if d is None:
                continue
            model_rank = None
            for idx, n in enumerate(normalized):
                if n["horse_no"] == role.horse_no:
                    sorted_idx = sorted(range(len(normalized)),
                                        key=lambda i: normalized[i]["mp"],
                                        reverse=True)
                    rank_map = {oi: r for r, oi in enumerate(sorted_idx, start=1)}
                    model_rank = rank_map.get(idx)
                    break
            reason_extra = drift_reason_for(d, model_rank or 99)
            if reason_extra:
                role.reasons.append(reason_extra)

        decision = decide(unc, roles)

        # build small + balanced + wide proposals
        small_t = _build_ticket_proposal(decision, roles, normalized,
                                         mode_override="small")
        balanced_t = _build_ticket_proposal(decision, roles, normalized,
                                            mode_override="balanced")
        wide_t = _build_ticket_proposal(decision, roles, normalized,
                                        mode_override="wide")

        # candidate set: union of all roled-in horses or top-by-p_top4
        from .candidate_sets import build_set_by_p_top4
        candidate = build_set_by_p_top4(normalized,
                                        max(4, min(required, field_size)))

        # variance label
        variance = _label_variance(unc.level, field_size, required)

        # per-role lists with rich horse detail
        sorted_idx = sorted(range(len(normalized)),
                            key=lambda i: normalized[i]["mp"], reverse=True)
        model_rank_map = {normalized[oi]["horse_no"]: r
                          for r, oi in enumerate(sorted_idx, start=1)}

        def _horse_detail(role) -> dict:
            n = next((x for x in normalized
                      if x["horse_no"] == role.horse_no), None)
            if n is None:
                return {"horse_no": role.horse_no, "role": role.role,
                        "warnings": ["horse not in snapshot"]}
            d = drift_map.get(role.horse_no)
            warnings: list[str] = []
            if d and d.status != "OK":
                warnings.append(f"AGF_{d.status}")
            if n.get("p_top4_method") == "fallback_rank_prior":
                warnings.append("p_top4_fallback")
            if n.get("p_top4_method") == "insufficient_data":
                warnings.append("p_top4_insufficient")
            return {
                "horse_no": n["horse_no"],
                "horse_name": n["horse_name"],
                "mp": n["mp"],
                "p_top4_cal": n["p_top4_cal"],
                "p_top4_method": n["p_top4_method"],
                "agf_now": n["agf"],
                "agf_open": n["agf_open"],
                "agf_drift_abs": (d.agf_drift_abs if d else None),
                "agf_drift_rel": (d.agf_drift_rel if d else None),
                "agf_rank_open": (d.agf_rank_open if d else None),
                "agf_rank_now": (d.agf_rank_now if d else None),
                "agf_rank_movement": (d.agf_rank_movement if d else None),
                "model_rank": model_rank_map.get(role.horse_no),
                "tier": n["tier"],
                "role": role.role,
                "reason": "; ".join(role.reasons),
                "confidence": role.confidence,
                "warnings": warnings,
            }

        bankers = [_horse_detail(r) for r in roles if r.role == ROLE_BANKER]
        core = [_horse_detail(r) for r in roles if r.role == ROLE_CORE]
        spread = [_horse_detail(r) for r in roles if r.role == ROLE_SPREAD]
        chaos = [_horse_detail(r) for r in roles if r.role == ROLE_CHAOS]
        avoid = [_horse_detail(r) for r in roles if r.role == ROLE_AVOID]

        notes: list[str] = []
        notes.extend(drift.notes)
        if any(n.get("p_top4_method") == "fallback_rank_prior" for n in normalized):
            notes.append("p_top4 fallback prior aktif — isotonic fit yok.")
        if unc.reasons:
            notes.append("uncertainty: " + "; ".join(unc.reasons))
        if decision.skip:
            notes.append("no_bet_reason: " + "; ".join(decision.reasons))

        snap_hash = _snapshot_hash({"horses": normalized,
                                    "race_label": race_label,
                                    "cutoff": cutoff})

        coupon = {
            "label": EXPERIMENTAL_LABEL,
            "label_display": EXPERIMENTAL_LABEL_DISPLAY,
            "race_id": str(race_snapshot.get("race_id") or race_label),
            "race_label": race_label,
            "race_time": str(race_snapshot.get("race_time") or ""),
            "hippodrome": str(race_snapshot.get("hippodrome") or ""),
            "field_size": field_size,
            "generated_at": _now_iso(),
            "agf_snapshot_time": drift.snapshot_now_ts,
            "prediction_cutoff": cutoff,
            "model_version": "v7_ndcg4+top4cal",
            "feature_snapshot_hash": snap_hash,
            "confidence": unc.level,
            "variance": variance,
            "recommended_mode": ("NO_BET" if decision.skip
                                 else decision.mode.upper()),
            "bankers": bankers,
            "core": core,
            "spread": spread,
            "chaos": chaos,
            "avoid": avoid,
            "candidate_set": list(candidate.horse_nos),
            "small_ticket": small_t,
            "balanced_ticket": balanced_t,
            "wide_ticket": wide_t,
            "no_bet_reason": ("; ".join(decision.reasons)
                              if decision.skip else None),
            "notes": notes,
            "engine_status": ("fallback"
                              if any(n.get("p_top4_method")
                                     == "fallback_rank_prior"
                                     for n in normalized)
                              else "ok"),
            "disclaimer": DISCLAIMER,
            "horses": [_horse_detail(r) for r in roles
                       if r.role != ROLE_NO_SIGNAL],
        }
        return coupon

    except Exception as exc:  # never raise
        coupon = _empty_coupon(race_label, cutoff,
                               reason=f"engine_error: {type(exc).__name__}")
        coupon["notes"].append(traceback.format_exc().splitlines()[-1][:200])
        return coupon
