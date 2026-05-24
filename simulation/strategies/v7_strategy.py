"""V7 adaptör — yerli_engine._v7_build_preview wrap (read-only).

_v7_build_preview legs_summary'den çalışır (model.predict çağırmaz; model_prob zaten
snapshot'ta). REPAIRED/agf_missing → status skipped, legs_selected boş döner.
"""
from __future__ import annotations


def v7_strategy(result: dict) -> dict:
    from yerli_engine import _v7_build_preview
    v7 = _v7_build_preview(result)
    if not isinstance(v7, dict) or v7.get("status") == "skipped" or "legs" not in v7:
        return {"name": "v7", "legs_selected": [], "combo": 0, "cost": 0.0,
                "note": v7.get("reason") if isinstance(v7, dict) else "no_v7"}
    legs = v7.get("legs") or []
    legs_selected = [[s.get("number") for s in (l.get("selected") or [])] for l in legs]
    combo = 1
    for ls in legs_selected:
        combo *= max(1, len(ls))
    cost = v7.get("cost")
    if cost is None:
        bf = v7.get("bf", 1.25) or 1.25
        cost = combo * bf
    return {
        "name": "v7",
        "legs_selected": legs_selected,
        "combo": combo,
        "cost": round(float(cost), 2),
        "budget_status": v7.get("budget_status"),
        "singles": sum(1 for ls in legs_selected if len(ls) == 1),
    }
