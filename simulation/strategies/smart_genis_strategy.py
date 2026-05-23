"""smart_genis adaptör — yerli_engine.build_smart_genis wrap (read-only).

build_smart_genis çıktısı: {legs:[{selected:[{number,...}], n_pick, ...}], combo, cost, ...}.
"""
from __future__ import annotations


def smart_genis_strategy(result: dict) -> dict:
    from yerli_engine import build_smart_genis
    gs = build_smart_genis(result)
    if not isinstance(gs, dict):
        return {"name": "smart_genis", "legs_selected": [], "combo": 0, "cost": 0.0,
                "note": "no_output"}
    legs = gs.get("legs") or []
    legs_selected = [[s.get("number") for s in (l.get("selected") or [])] for l in legs]
    return {
        "name": "smart_genis",
        "legs_selected": legs_selected,
        "combo": gs.get("combo", 0),
        "cost": gs.get("cost", 0.0),
        "singles": sum(1 for ls in legs_selected if len(ls) == 1),
    }
