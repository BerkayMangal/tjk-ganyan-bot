"""Top-4 ticket proposal builder.

This NEVER places bets. It returns a structured proposal that downstream
reporting (Telegram / dashboard / audit) can render. The proposal includes
a stake-cap recommendation and a list of horses by role. When the no-bet
gate fires, the proposal carries `skip=True` and an empty horse list.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Iterable

from .no_bet_gate import NoBetDecision
from .roles import (
    ROLE_BANKER, ROLE_CHAOS, ROLE_CORE, ROLE_SPREAD, RoleAssignment,
)


@dataclass
class TicketProposal:
    skip: bool
    mode: str  # no_bet | small | balanced | wide
    banker: list[int] = field(default_factory=list)
    core: list[int] = field(default_factory=list)
    spread: list[int] = field(default_factory=list)
    chaos: list[int] = field(default_factory=list)
    horse_total: int = 0
    estimated_combinations: int = 0
    stake_cap_suggestion: str = "small"
    reasons: list[str] = field(default_factory=list)
    is_proposal_only: bool = True  # never auto-bets

    def all_horses(self) -> list[int]:
        return self.banker + self.core + self.spread + self.chaos


def _comb(n: int, k: int) -> int:
    from math import comb
    if k <= 0 or k > n:
        return 0
    return comb(n, k)


def build(decision: NoBetDecision, roles: Iterable[RoleAssignment]) -> TicketProposal:
    if decision.skip:
        return TicketProposal(
            skip=True,
            mode="no_bet",
            reasons=decision.reasons,
            stake_cap_suggestion="none",
        )

    roles = list(roles)
    bankers = [r.horse_no for r in roles if r.role == ROLE_BANKER]
    cores = [r.horse_no for r in roles if r.role == ROLE_CORE]
    spreads = [r.horse_no for r in roles if r.role == ROLE_SPREAD]
    chaos = [r.horse_no for r in roles if r.role == ROLE_CHAOS]

    if decision.mode == "small":
        sel_b = bankers[:2]
        sel_c = cores[:2]
        sel_s = spreads[:1]
        sel_x: list[int] = []
        stake = "small"
    elif decision.mode == "balanced":
        sel_b = bankers[:2]
        sel_c = cores[:3]
        sel_s = spreads[:2]
        sel_x = chaos[:1]
        stake = "small"
    elif decision.mode == "wide":
        sel_b = bankers[:2]
        sel_c = cores[:4]
        sel_s = spreads[:3]
        sel_x = chaos[:2]
        stake = "small_only"  # wide => stake cap small per ticket
    else:
        return TicketProposal(skip=True, mode="no_bet",
                              reasons=["unknown mode " + decision.mode],
                              stake_cap_suggestion="none")

    total = sel_b + sel_c + sel_s + sel_x
    # dedupe preserving order
    seen: set[int] = set()
    dedup: list[int] = []
    for h in total:
        if h not in seen:
            seen.add(h)
            dedup.append(h)
    if len(dedup) < 4:
        return TicketProposal(
            skip=True, mode="no_bet",
            reasons=["fewer than 4 horses with signal"],
            stake_cap_suggestion="none",
        )

    combos = _comb(len(dedup), 4)
    return TicketProposal(
        skip=False,
        mode=decision.mode,
        banker=sel_b,
        core=sel_c,
        spread=sel_s,
        chaos=sel_x,
        horse_total=len(dedup),
        estimated_combinations=combos,
        stake_cap_suggestion=stake,
        reasons=decision.reasons,
    )
