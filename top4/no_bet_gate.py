"""No-bet decision gate.

Combines uncertainty level, role distribution, and risk-adjusted EV
guidance into a final RECOMMEND / NO_BET label with explicit reasons.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable

from .roles import RoleAssignment, ROLE_BANKER, ROLE_CORE, ROLE_SPREAD
from .uncertainty import UncertaintyReport, LEVEL_NO_BET, LEVEL_CHAOS


@dataclass
class NoBetDecision:
    skip: bool
    mode: str  # "no_bet" | "small" | "balanced" | "wide"
    reasons: list[str]


def decide(uncertainty: UncertaintyReport, roles: Iterable[RoleAssignment]) -> NoBetDecision:
    roles = list(roles)
    n_banker = sum(1 for r in roles if r.role == ROLE_BANKER)
    n_core = sum(1 for r in roles if r.role == ROLE_CORE)
    n_spread = sum(1 for r in roles if r.role == ROLE_SPREAD)
    reasons: list[str] = []

    if uncertainty.level == LEVEL_NO_BET:
        return NoBetDecision(True, "no_bet",
                             reasons=uncertainty.reasons + ["uncertainty NO_BET"])

    if uncertainty.level == LEVEL_CHAOS and n_banker == 0:
        return NoBetDecision(True, "no_bet",
                             reasons=uncertainty.reasons + ["chaotic + no banker"])

    if n_banker == 0 and n_core <= 1 and uncertainty.required_set_size >= 7:
        return NoBetDecision(True, "no_bet",
                             reasons=["weak structure: 0 banker, <=1 core, wide set"])

    if n_banker >= 1 and n_core + n_spread <= 2:
        return NoBetDecision(False, "small",
                             reasons=[f"{n_banker} banker, tight pool"])
    if n_banker >= 1 and n_core + n_spread <= 5:
        return NoBetDecision(False, "balanced",
                             reasons=[f"{n_banker} banker, {n_core} core, {n_spread} spread"])
    return NoBetDecision(False, "wide",
                         reasons=[f"{n_banker}B/{n_core}C/{n_spread}S, broad structure"])
