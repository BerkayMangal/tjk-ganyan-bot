"""Favori Yıkma builder — fy-ayaklarında favori fade; diğer ayaklar sade.

MODE (Phase 5.8.1 env TJK_V9_FAVYIKMA_MODE):
- "pure" (default): favori DIŞLANIR, value top-4 (eski davranış — favori kazanırsa garantili miss).
- "hybrid": favori TUTULUR + value top-3 (soft-fade; hit-rate korunur, yıkıcı-payout potansiyeli kalır).
"""
from __future__ import annotations

import os

from simulation.v9.builders import (finalize, grow_to_min, make_ticket,
                                     shrink_to_budget, top_by_v9, top_by_value)


def build(aggregated, routing):
    legs = aggregated.get("legs") or []
    sigs = routing["ticket_design_params"]["sigs"]
    band_min, band_max = routing["budget_band"][0] or 300, routing["budget_band"][1] or 800
    mode = os.getenv("TJK_V9_FAVYIKMA_MODE", "pure")
    # Sanity-floor için tüm leg'lerin v9-sıralı at listesi (grow_to_min adayı)
    ranked = [[p["number"] for p in (leg.get("profiles") or [])] for leg in legs]
    sel, summary = [], []
    for i, leg in enumerate(legs):
        profs = leg["profiles"]
        s = sigs[i] if i < len(sigs) else {}
        if s.get("is_fy"):
            fav = s.get("fav_number")
            if mode == "hybrid":
                picks = ([fav] if fav is not None else []) + top_by_value(profs, 3, exclude=fav)
                sel.append(picks)
                summary.append(f"Ayak {leg.get('ayak')}: SOFT-YIKMA — favori #{fav} TUTULDU + value {picks[1:]}")
            else:
                picks = top_by_value(profs, 4, exclude=fav)  # favori DIŞ, value top-4
                sel.append(picks)
                summary.append(f"Ayak {leg.get('ayak')}: YIKMA — favori #{fav} DIŞLANDI, value {picks}")
        else:
            sel.append(top_by_v9(profs, 2))
            lead = profs[0] if profs else {}
            summary.append(f"Ayak {leg.get('ayak')}: sade — #{lead.get('number')} +1")
    # Phase 6 P1: shrink ceiling + grow floor (band[0]) → bant ve harcama tutarlı,
    # absürd küçük (combo<240=~300TL) durumlarda en dar ayağa v9-sıralı sonraki at eklenir.
    sel_final = grow_to_min(shrink_to_budget(sel, band_max), ranked, min_cost=band_min)
    tickets = [make_ticket("Yıkma Ana", sel_final)]
    return finalize("favori_yikma", tickets, summary)
