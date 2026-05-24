"""Phase 5.6 — strateji kupon builder'ları + dispatcher.

Her builder: (aggregated, routing) → kupon {strategy, tickets:[{name, legs_selected, combo, cost}],
total_cost, total_combo, legs_selected(union), signal_summary}. bf=1.25 (büyük hipodrom varsayım,
backtest). Bütçe bandı = ÖNERİ → aşarsa en geniş ayaklardan shrink (öneri amaçlı).
"""
from __future__ import annotations

BF = 1.25


def combo_of(legs_selected):
    c = 1
    for s in legs_selected:
        c *= max(1, len(s))
    return c


def cost_of(combo):
    return round(combo * BF, 2)


def top_by_v9(profiles, n):
    return [p["number"] for p in profiles[:max(1, n)]]


def top_by_value(profiles, n, exclude=None):
    ps = sorted(profiles, key=lambda p: -p.get("value_score", 0))
    out = [p["number"] for p in ps if p["number"] != exclude]
    return out[:max(1, n)]


def shrink_to_budget(legs_selected, budget_max):
    """En geniş ayaktan at çıkararak combo·bf ≤ budget_max (öneri). Min 1/ayak."""
    ls = [list(x) for x in legs_selected]
    while cost_of(combo_of(ls)) > budget_max and budget_max > 0:
        i = max(range(len(ls)), key=lambda k: len(ls[k]))
        if len(ls[i]) <= 1:
            break
        ls[i].pop()
    return ls


def make_ticket(name, legs_selected):
    c = combo_of(legs_selected)
    return {"name": name, "legs_selected": legs_selected, "combo": c, "cost": cost_of(c)}


def finalize(strategy, tickets, signal_summary):
    # union (generic hit-uyumluluk) + toplamlar
    n_leg = max((len(t["legs_selected"]) for t in tickets), default=0)
    union = []
    for i in range(n_leg):
        s = set()
        for t in tickets:
            if i < len(t["legs_selected"]):
                s |= set(t["legs_selected"][i])
        union.append(sorted(s))
    return {"strategy": strategy, "tickets": tickets,
            "total_cost": round(sum(t["cost"] for t in tickets), 2),
            "total_combo": sum(t["combo"] for t in tickets),
            "legs_selected": union, "combo": combo_of(union), "cost": cost_of(combo_of(union)),
            "signal_summary": signal_summary}


def build_for_strategy(strategy, aggregated, routing):
    if strategy == "tam_sistem":
        from simulation.v9.builders.tam_sistem_builder import build
    elif strategy == "favori_yikma":
        from simulation.v9.builders.favori_yikma_builder import build
    elif strategy == "kangal":
        from simulation.v9.builders.kangal_builder import build
    else:
        return {"strategy": "pas", "tickets": [], "total_cost": 0.0, "total_combo": 0,
                "legs_selected": [], "combo": 0, "cost": 0.0,
                "signal_summary": ["PAS — net edge yok; Berkay manuel oynayabilir (profil görünür)"]}
    return build(aggregated, routing)
