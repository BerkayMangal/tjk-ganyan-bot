"""Kangal builder — durum-uyarlamalı, 2 ticket (Ana + Yıkıcı). Bankerler aynı, yıkıcı ayaklarda
farklı longshot dağılımı. Spread yok (sıkı kupon). Bütçe ≤5000 (öneri)."""
from __future__ import annotations

from simulation.v9.builders import (finalize, make_ticket, shrink_to_budget,
                                     top_by_v9, top_by_value)
from simulation.v9.strategy_router import MED_GAP


def build(aggregated, routing):
    legs = aggregated.get("legs") or []
    sigs = routing["ticket_design_params"]["sigs"]
    band_max = routing["budget_band"][1] or 5000
    ana, yikici, summary = [], [], []
    for i, leg in enumerate(legs):
        profs = leg["profiles"]
        s = sigs[i] if i < len(sigs) else {}
        fav = s.get("fav_number")
        if s.get("is_fy"):
            ana.append(top_by_value(profs, 4, exclude=fav))      # yıkma: value top-4
            yikici.append(top_by_value(profs, 5, exclude=fav))   # yıkıcı: daha derin (5)
            summary.append(f"Ayak {leg.get('ayak')}: YIKMA #{fav} dış (Ana 4 / Yıkıcı 5 longshot)")
        elif leg.get("surprise_prob", 0) >= 0.84:
            cov = top_by_v9(profs, 5)
            ana.append(cov); yikici.append(cov)
            summary.append(f"Ayak {leg.get('ayak')}: SÜRPRİZ — 5 at coverage")
        elif (s.get("gap", 0) > MED_GAP):
            tek = top_by_v9(profs, 1)
            ana.append(tek); yikici.append(tek)                  # sağlam → TEK (banker, ortak)
            summary.append(f"Ayak {leg.get('ayak')}: BANKER TEK #{tek[0] if tek else '?'}")
        else:
            t2 = top_by_v9(profs, 2)
            ana.append(t2); yikici.append(t2)
            summary.append(f"Ayak {leg.get('ayak')}: 2 at")
    half = max(1000, band_max // 2)
    tickets = [make_ticket("Kangal Ana", shrink_to_budget(ana, half)),
               make_ticket("Kangal Yıkıcı", shrink_to_budget(yikici, half))]
    return finalize("kangal", tickets, summary)
