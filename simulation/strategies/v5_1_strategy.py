"""V5.1 adaptör — engine.kupon.build_kupon wrap (read-only).

legs_summary.all_horses_with_mp → build_kupon'ın beklediği legs formatına reconstruct.
"""
from __future__ import annotations

from typing import Any


def _reconstruct_legs(result: dict) -> list:
    legs = []
    for ls in result.get("legs_summary", []) or []:
        horses_mp = ls.get("all_horses_with_mp", []) or []
        # build_kupon horses: [(name, score, number)] model_prob desc sıralı
        horses = sorted(
            [(h.get("name"), h.get("score", 0) or 0, h.get("number")) for h in horses_mp],
            key=lambda t: -(t[1] or 0),
        )
        agf_data = [{"horse_number": h.get("number"), "agf_pct": h.get("agf_pct", 0) or 0}
                    for h in horses_mp]
        legs.append({
            "horses": horses,
            "n_runners": ls.get("n_runners", len(horses)) or len(horses),
            "confidence": ls.get("confidence", 0) or 0,
            "model_agreement": ls.get("agreement", 0.5) or 0.5,
            "agf_data": agf_data,
            "has_model": ls.get("has_model", False),
            "race_number": ls.get("race_number", ls.get("ayak")),
        })
    return legs


def v5_1_strategy(result: dict, mode: str = "dar") -> dict:
    from engine.kupon import build_kupon
    legs = _reconstruct_legs(result)
    if not legs:
        return {"name": "v5.1", "legs_selected": [], "combo": 0, "cost": 0.0,
                "note": "no_legs"}
    kupon = build_kupon(legs, result.get("hippodrome", ""), mode=mode)
    legs_selected = [[s[2] for s in (leg.get("selected") or [])]
                     for leg in kupon.get("legs", [])]
    return {
        "name": f"v5.1_{mode}",
        "legs_selected": legs_selected,
        "combo": kupon.get("combo", 0),
        "cost": kupon.get("cost", 0.0),
        "n_singles": kupon.get("n_singles", 0),
    }
