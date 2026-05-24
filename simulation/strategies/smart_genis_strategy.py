"""smart_genis adaptör — yerli_engine.build_smart_genis wrap (read-only).

build_smart_genis çıktısı: {legs:[{selected:[{number,...}], n_pick, ...}], combo, cost, ...}.

Phase 5.3: build_smart_genis CANLI-STATE bağımlı — result['dar']['legs'] + result['genis']
ister (pure-function değil). Reconstructed snapshot'larda bu yok. Wrapper bridge:
result'ta dar.legs yoksa, V5.1'i (dar+genis) koştur → native dar/genis enjekte → expand.
live_test snapshot'larında dar zaten var → doğrudan kullan.
"""
from __future__ import annotations


def _native_dar(result: dict, mode: str) -> dict:
    """V5.1 build_kupon çıktısını yerli_engine-native dar/genis formatına çevir."""
    from simulation.strategies.v5_1_strategy import v5_1_strategy
    v5 = v5_1_strategy(result, mode=mode)
    sel_per_leg = v5.get("legs_selected") or []
    legs_summary = result.get("legs_summary") or []
    dar_legs = []
    for i, sel_nums in enumerate(sel_per_leg):
        by_num = {}
        if i < len(legs_summary):
            for h in legs_summary[i].get("all_horses_with_mp", []) or []:
                by_num[h.get("number")] = h
        selected = [{"number": n, "name": (by_num.get(n) or {}).get("name", f"at_{n}"),
                     "score": (by_num.get(n) or {}).get("score", 0.0)} for n in sel_nums]
        dar_legs.append({"leg_number": i + 1, "race_number": i + 1,
                         "n_pick": len(sel_nums), "is_tek": len(sel_nums) == 1,
                         "selected": selected})
    return {"mode": mode, "legs": dar_legs, "combo": v5.get("combo", 0),
            "cost": v5.get("cost", 0.0)}


def _ensure_dar_genis(result: dict) -> None:
    """dar.legs yoksa V5.1 dar+genis enjekte et (in-place, replay için)."""
    dar = result.get("dar") or {}
    if dar.get("legs"):
        return  # live_test snapshot — zaten var
    result["dar"] = _native_dar(result, "dar")
    result["genis"] = _native_dar(result, "genis")  # daha geniş havuz (expand için)


def smart_genis_strategy(result: dict) -> dict:
    from yerli_engine import build_smart_genis
    _ensure_dar_genis(result)
    build_smart_genis(result)  # result'ı mutate eder → result['genis_smart'] yazar
    sm = result.get("genis_smart") or {}
    if not isinstance(sm, dict) or "legs" not in sm:
        return {"name": "smart_genis", "legs_selected": [], "combo": 0, "cost": 0.0,
                "note": "no_output"}
    legs = sm.get("legs") or []
    legs_selected = [[s.get("number") for s in (l.get("selected") or [])] for l in legs]
    return {
        "name": "smart_genis",
        "legs_selected": legs_selected,
        "combo": sm.get("combo", 0),
        "cost": sm.get("cost", 0.0),
        "singles": sum(1 for ls in legs_selected if len(ls) == 1),
    }
