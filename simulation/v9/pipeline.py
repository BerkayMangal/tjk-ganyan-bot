"""Phase 5.6 — v9 pipeline orchestrator (race kurulum + aggregate + route + build).

build_v9_race: snapshot_builder result + enriched lookup (jokey/form) → v9 race contract.
run_pipeline: race → aggregate (L1-L9) → route → kupon. Backtest + shadow ortak kullanır.
"""
from __future__ import annotations

import os
import sys
from collections import defaultdict

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def enriched_lookup():
    """{(date, hip_normed, at_no): {jockey, form_score, age, distance}}. form = pencere-içi prior S ort."""
    from simulation.analytics.dataset import build
    rows = build()
    by_name = defaultdict(list)
    for r in sorted(rows, key=lambda x: x["date"]):
        if r.get("name"):
            by_name[r["name"]].append(r)
    form_of = {}
    for name, apps in by_name.items():
        prior = []
        for r in apps:
            form_of[id(r)] = (sum(prior) / len(prior)) if prior else None
            if r.get("S"):
                prior.append(r["S"])
    out = {}
    for r in rows:
        out[(r["date"], r["hip"], r["at_no"])] = {
            "jockey": r.get("jockey"), "form_score": form_of.get(id(r)),
            "age": r.get("age"), "distance": r.get("distance")}
    return out


_FOLD = str.maketrans("İıÇçĞğÖöŞşÜü", "iiccggoossuu")


def _norm(s):
    return (s or "").strip().translate(_FOLD).lower()


def build_v9_race(snap_result: dict, enr=None) -> dict:
    """snapshot result → v9 race contract (jokey/form enriched lookup'tan).
    Phase 9: horse'a 'name', leg'e 'mesafe' eklendi → L6_CANLI form_loader plumbing."""
    date = snap_result.get("date")
    hip = snap_result.get("hippodrome")
    hipn = _norm(hip)
    legs = []
    for ls in snap_result.get("legs_summary", []) or []:
        horses = []
        for h in ls.get("all_horses_with_mp", []) or []:
            num = h.get("number")
            extra = (enr or {}).get((date, hipn, num), {}) if enr else {}
            horses.append({"number": num, "agf_pct": h.get("agf_pct", 0),
                           "score": (h.get("model_prob") or 0) / 100.0,
                           "jockey": extra.get("jockey"), "form_score": extra.get("form_score"),
                           "name": h.get("name")})   # Phase 9: form_loader için at_adi
        legs.append({"ayak": ls.get("ayak"), "horses": horses,
                     "mesafe": ls.get("distance")})  # Phase 9: form_loader için yarış mesafesi
    return {"date": date, "hippodrome": hip, "legs": legs}


def run_pipeline(race: dict, carryover_state=None) -> dict:
    """race → {aggregated, routing, kupon}."""
    from simulation.v9.layer_aggregator import aggregate_race
    from simulation.v9.strategy_router import route_strategy
    from simulation.v9.builders import build_for_strategy
    agg = aggregate_race(race, carryover_state)
    routing = route_strategy(race, agg, carryover_state)
    kupon = build_for_strategy(routing["strategy"], agg, routing)
    return {"aggregated": agg, "routing": routing, "kupon": kupon}
