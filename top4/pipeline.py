"""Top-level pipeline: race rows -> calibrated -> roles -> uncertainty ->
decision -> ticket -> rendered text.

This is what production wires in behind TJK_TOP4_SCIENTIFIC=1. The
function is pure and side-effect free; logging is the caller's job.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping, Optional

from .calibration import calibrate_race
from .candidate_sets import coverage_required_for_target
from .no_bet_gate import decide
from .report import render_race
from .roles import assign_roles
from .ticket_builder import build as build_ticket
from .uncertainty import evaluate


@dataclass
class RaceForecast:
    race_label: str
    field_size: int
    calibrated: list
    roles: list
    uncertainty: dict
    decision: dict
    ticket: dict
    rendered: str


def forecast_race(race_label: str, rows: Iterable[Mapping]) -> RaceForecast:
    rows = list(rows)
    calibrated = calibrate_race(rows)
    # enrich rows with calibrated probs for role assignment
    cal_map = {c.horse_no: c for c in calibrated}
    enriched = []
    for r in rows:
        c = cal_map.get(int(r.get("horse_no", -1)))
        enriched.append({
            **r,
            "p_top4_cal": c.p_top4_cal if c else None,
            "p_win_cal": c.p_win_cal if c else None,
        })
    field_size = len(rows)
    req = coverage_required_for_target(enriched, target=0.80)
    unc = evaluate(enriched, required_set_size=req)
    roles = assign_roles(enriched, field_size=field_size, uncertainty=unc.level)
    dec = decide(unc, roles)
    ticket = build_ticket(dec, roles)
    rendered = render_race(race_label, calibrated, roles, unc, dec, ticket)
    return RaceForecast(
        race_label=race_label,
        field_size=field_size,
        calibrated=[asdict(c) for c in calibrated],
        roles=[asdict(r) for r in roles],
        uncertainty=asdict(unc),
        decision=asdict(dec),
        ticket=asdict(ticket),
        rendered=rendered,
    )
