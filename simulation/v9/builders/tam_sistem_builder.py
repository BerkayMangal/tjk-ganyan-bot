"""Tam Sistem builder — Main / Coverage / Spread (3 ticket). Dengeli, 9-layer aktif."""
from __future__ import annotations

from simulation.v9.builders import finalize, make_ticket, shrink_to_budget, top_by_v9
from simulation.v9.strategy_router import MED_GAP


def build(aggregated, routing):
    legs = aggregated.get("legs") or []
    sigs = routing["ticket_design_params"]["sigs"]
    band_max = routing["budget_band"][1] or 6000
    main, cover, spread, summary = [], [], [], []
    for i, leg in enumerate(legs):
        profs = leg["profiles"]
        gap = sigs[i]["gap"] if i < len(sigs) else 0
        surp = leg.get("surprise_prob", 0)
        main.append(top_by_v9(profs, 1 if gap > MED_GAP else 2))
        cover.append(top_by_v9(profs, 3))
        spread.append(top_by_v9(profs, 5 if surp >= 0.84 else 2))
        lead = profs[0] if profs else {}
        summary.append(f"Ayak {leg.get('ayak')}: lider #{lead.get('number')} "
                       f"({'TEK' if gap > MED_GAP else 'çekişme'}) — {', '.join(lead.get('signal_summary', [])[:2])}")
    # her ticket band'ın ~1/3'üne (öneri)
    per = max(1000, band_max // 3)
    tickets = [
        make_ticket("Main", shrink_to_budget(main, per)),
        make_ticket("Coverage", shrink_to_budget(cover, per)),
        make_ticket("Spread", shrink_to_budget(spread, per)),
    ]
    return finalize("tam_sistem", tickets, summary)
