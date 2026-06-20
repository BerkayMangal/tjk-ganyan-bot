"""Role assignment: BANKER / CORE / SPREAD / CHAOS / AVOID / NO_SIGNAL.

Roles are ticket-construction primitives. They are NOT a guarantee of a
finish position. A BANKER says: "this horse is, by calibrated estimate
and market consensus, very likely to make the top-4, and removing it from
a ticket would meaningfully degrade coverage."

The classifier is intentionally conservative. If calibrated probability
is missing, the maximum role allowed is CORE (never BANKER). If AGF
strongly disagrees with the model, BANKER is downgraded to CORE or
SPREAD.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional

ROLE_BANKER = "BANKER"
ROLE_CORE = "CORE"
ROLE_SPREAD = "SPREAD"
ROLE_CHAOS = "CHAOS"
ROLE_AVOID = "AVOID"
ROLE_NO_SIGNAL = "NO_SIGNAL"

ROLE_ORDER = [ROLE_BANKER, ROLE_CORE, ROLE_SPREAD, ROLE_CHAOS, ROLE_AVOID, ROLE_NO_SIGNAL]


@dataclass
class RoleAssignment:
    horse_no: int
    role: str
    reasons: list[str]
    confidence: str  # HIGH | MEDIUM | LOW


def _model_vs_agf_gap(mp: float, agf: Optional[float]) -> Optional[float]:
    if agf is None:
        return None
    return mp - (agf / 100.0)


def assign_roles(
    rows: Iterable[Mapping],
    field_size: int,
    uncertainty: Optional[str] = None,
) -> list[RoleAssignment]:
    """Assign one role per horse.

    Expected row keys: horse_no, mp, agf (optional), p_top4_cal (optional),
    p_win_cal (optional), tier (optional), model_rank (optional).
    """
    rows = list(rows)
    if not rows:
        return []

    # Compute model rank if not present
    sorted_idx = sorted(
        range(len(rows)), key=lambda i: rows[i].get("mp", 0.0), reverse=True
    )
    rank_map = {orig: r for r, orig in enumerate(sorted_idx, start=1)}

    out: list[RoleAssignment] = []
    for i, row in enumerate(rows):
        rank = row.get("model_rank") or rank_map[i]
        mp = float(row.get("mp", 0.0))
        agf = row.get("agf")
        p_t4 = row.get("p_top4_cal")
        p_win = row.get("p_win_cal")
        tier = row.get("tier", "")

        reasons: list[str] = []
        confidence = "MEDIUM"
        gap = _model_vs_agf_gap(mp, agf)

        if p_t4 is None and mp == 0.0:
            out.append(RoleAssignment(
                horse_no=int(row.get("horse_no", i + 1)),
                role=ROLE_NO_SIGNAL,
                reasons=["no model output"],
                confidence="LOW",
            ))
            continue

        # ---- BANKER ----
        banker_ok = (
            p_t4 is not None
            and p_t4 >= 0.55
            and rank <= 2
            and (agf is None or agf >= 25)
            and uncertainty not in {"CHAOS", "NO_BET"}
        )
        if banker_ok:
            reasons.append(f"p_top4_cal={p_t4:.2f}")
            reasons.append(f"rank={rank}")
            if agf is not None:
                reasons.append(f"agf={agf:.1f}")
            confidence = "HIGH"
            out.append(RoleAssignment(int(row.get("horse_no", i + 1)),
                                      ROLE_BANKER, reasons, confidence))
            continue

        # ---- AVOID: public trap (high AGF, low model) ----
        if agf is not None and agf >= 35 and rank >= 5 and (p_t4 is None or p_t4 < 0.30):
            reasons.append("public_trap")
            reasons.append(f"agf={agf:.1f} but rank={rank}")
            out.append(RoleAssignment(int(row.get("horse_no", i + 1)),
                                      ROLE_AVOID, reasons, "MEDIUM"))
            continue

        # ---- CORE ----
        core_ok = (
            (p_t4 is not None and p_t4 >= 0.38)
            or (rank <= 3 and (p_t4 is None or p_t4 >= 0.30))
        )
        if core_ok:
            if p_t4 is not None:
                reasons.append(f"p_top4_cal={p_t4:.2f}")
            reasons.append(f"rank={rank}")
            confidence = "MEDIUM" if p_t4 is not None else "LOW"
            out.append(RoleAssignment(int(row.get("horse_no", i + 1)),
                                      ROLE_CORE, reasons, confidence))
            continue

        # ---- SPREAD: model likes more than AGF (positive gap) ----
        if gap is not None and gap > 0.05 and rank <= 6:
            reasons.append(f"model_over_agf_gap={gap:+.3f}")
            reasons.append(f"rank={rank}")
            out.append(RoleAssignment(int(row.get("horse_no", i + 1)),
                                      ROLE_SPREAD, reasons, "LOW"))
            continue

        # ---- CHAOS: very low AGF (longshot), mid model ----
        if (agf is not None and agf <= 5 and rank <= 8):
            reasons.append("longshot_with_model_signal")
            out.append(RoleAssignment(int(row.get("horse_no", i + 1)),
                                      ROLE_CHAOS, reasons, "LOW"))
            continue

        # ---- default: NO_SIGNAL or filler ----
        out.append(RoleAssignment(
            horse_no=int(row.get("horse_no", i + 1)),
            role=ROLE_NO_SIGNAL,
            reasons=["below thresholds"],
            confidence="LOW",
        ))

    # Enforce: cannot have more than 2 BANKERs per race (too aggressive)
    bankers = [r for r in out if r.role == ROLE_BANKER]
    if len(bankers) > 2:
        # keep top by horse rank, demote rest to CORE
        bankers_sorted = sorted(
            bankers,
            key=lambda r: next((rows[i].get("mp", 0.0)
                                for i in range(len(rows))
                                if int(rows[i].get("horse_no", i + 1)) == r.horse_no), 0.0),
            reverse=True,
        )
        keep = set(r.horse_no for r in bankers_sorted[:2])
        for r in out:
            if r.role == ROLE_BANKER and r.horse_no not in keep:
                r.role = ROLE_CORE
                r.reasons.append("downgraded: too many bankers in race")
    return out
