"""Phase 5.6 — strateji kupon builder'ları + dispatcher.

Her builder: (aggregated, routing) → kupon {strategy, tickets:[{name, legs_selected, combo, cost}],
total_cost, total_combo, legs_selected(union), signal_summary}. bf=1.25 (büyük hipodrom varsayım,
backtest). Bütçe bandı = ÖNERİ → aşarsa en geniş ayaklardan shrink (öneri amaçlı).
"""
from __future__ import annotations

import os

BF = 1.25
# Min ticket maliyeti (öneri tabanı): tek-kombi "Main" (combo=1 → ~1 TL) absürtlüğünü engelle.
# Altı-ayaklı sistemde anlamlı en küçük kupon ~combo 80 (≈100 TL). Berkay env ile ayarlar.
MIN_TICKET_COST = float(os.getenv("TJK_V9_MIN_TICKET_COST", "100"))


def combo_of(legs_selected):
    c = 1
    for s in legs_selected:
        c *= max(1, len(s))
    return c


def cost_of(combo):
    return round(combo * BF, 2)


def grow_to_min(legs_selected, ranked_per_leg, min_cost=None):
    """combo·BF < min_cost ise en DAR ayaklara v9-sıralı bir sonraki atı ekle (öneri tabanı).
    ranked_per_leg[i] = leg i'nin v9_final'a göre sıralı TÜM at numaraları. Aday bitince durur."""
    if min_cost is None:
        min_cost = MIN_TICKET_COST
    ls = [list(x) for x in legs_selected]
    guard = 0
    while cost_of(combo_of(ls)) < min_cost and guard < 200:
        guard += 1
        cand = [i for i in range(len(ls)) if i < len(ranked_per_leg) and len(ls[i]) < len(ranked_per_leg[i])]
        if not cand:
            break
        i = min(cand, key=lambda k: len(ls[k]))   # en dar ayak
        ls[i].append(ranked_per_leg[i][len(ls[i])])
    return ls


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
    # TJK_COUPON_V2 — Coupon V2 (değişken genişlik greedy allocator).
    # DEFAULT ON (=1) — audit/13_v3_oos_edge backtest: V3 prob ile V2_always_V3 ROI -17.3%
    # vs eski AGF -72.0% (118 altılı OOS, 2025-05-24 → 2026-03-23, 4x kayıp azalması).
    # V3 alpha source DEĞİL (AUC 0.750 < AGF 0.775); kazanç V2 allocator'ın değişken-genişlik
    # dağılımından (banko/spread cost-optimal). Geri-al: Railway env TJK_COUPON_V2=0.
    use_v2 = os.environ.get("TJK_COUPON_V2", "1") == "1"
    if strategy == "tam_sistem":
        if use_v2:
            from simulation.v9.builders.coupon_v2 import build as build_v2
            return build_v2(aggregated, routing)
        from simulation.v9.builders.tam_sistem_builder import build
    elif strategy == "favori_yikma":
        if use_v2:
            from simulation.v9.builders.coupon_v2 import build as build_v2
            return build_v2(aggregated, routing)
        from simulation.v9.builders.favori_yikma_builder import build
    elif strategy == "kangal":
        if use_v2:
            from simulation.v9.builders.coupon_v2 import build as build_v2
            return build_v2(aggregated, routing)
        from simulation.v9.builders.kangal_builder import build
    else:
        return {"strategy": "pas", "tickets": [], "total_cost": 0.0, "total_combo": 0,
                "legs_selected": [], "combo": 0, "cost": 0.0,
                "signal_summary": ["PAS — net edge yok; Berkay manuel oynayabilir (profil görünür)"]}
    return build(aggregated, routing)
