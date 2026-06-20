"""User-facing Telegram/dashboard renderer for the scientific Top-4 layer.

Forbidden language is enforced. The renderer NEVER claims certainty.
"""
from __future__ import annotations

from typing import Iterable

from .calibration import CalibratedRow
from .no_bet_gate import NoBetDecision
from .roles import RoleAssignment
from .ticket_builder import TicketProposal
from .uncertainty import UncertaintyReport

FORBIDDEN_TERMS = {
    "guaranteed", "garanti", "certain", "kesin", "free money", "bedava para",
    "insider", "must bet", "mutlaka oyna", "safe profit", "garantili",
    "kesin kazanc", "kesin kazanç",
}


def has_forbidden_language(text: str) -> list[str]:
    low = text.lower()
    return sorted([t for t in FORBIDDEN_TERMS if t in low])


def render_race(
    race_label: str,
    calibrated: Iterable[CalibratedRow],
    roles: Iterable[RoleAssignment],
    uncertainty: UncertaintyReport,
    decision: NoBetDecision,
    ticket: TicketProposal,
) -> str:
    cal_map = {c.horse_no: c for c in calibrated}
    roles = list(roles)
    lines: list[str] = []
    lines.append(f"🏇 {race_label}")
    lines.append(f"Güven: {uncertainty.level} | Mod: {decision.mode.upper()}")
    if uncertainty.reasons:
        lines.append("Sebep: " + "; ".join(uncertainty.reasons))

    if decision.skip:
        lines.append("🛑 NO-BET (öneri): " + "; ".join(decision.reasons))
        lines.append("Not: bu bir tahmin/araştırma çıktısıdır, otomatik bahis YOK.")
        return "\n".join(lines)

    def _block(label: str, role_name: str):
        sel = [r for r in roles if r.role == role_name]
        if not sel:
            return
        lines.append(f"\n{label}:")
        for r in sel:
            c = cal_map.get(r.horse_no)
            ptxt = "p_top4 ?"
            if c and c.p_top4_cal is not None:
                ptxt = f"p_top4≈{c.p_top4_cal:.2f}"
            lines.append(f"  #{r.horse_no} — {ptxt} — {'; '.join(r.reasons)}")

    _block("BANKER", "BANKER")
    _block("CORE", "CORE")
    _block("SPREAD", "SPREAD")
    _block("CHAOS", "CHAOS")
    _block("AVOID (halk tuzağı)", "AVOID")

    if ticket and not ticket.skip:
        lines.append(
            f"\nKupon önerisi: {ticket.horse_total} at — ~{ticket.estimated_combinations} kombinasyon"
        )
        lines.append(f"Stake önerisi: {ticket.stake_cap_suggestion}")
    lines.append("\nNot: kalibre edilmiş tahmin, varyans yüksek olabilir; oto-bahis yok.")
    return "\n".join(lines)
