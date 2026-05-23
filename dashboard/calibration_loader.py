"""Phase 5.2 — kalibratör loader (SHADOW, no decision impact).

active.pkl yoksa None döner → apply_calibration no-op (None). Var olunca (Phase 5.2
forward fit sonrası) calibrated_prob hesaplar. yerli_engine bunu shadow meta'ya yazar;
kupon kararına GİRMEZ. Never-raises.
"""
from __future__ import annotations

import os
from typing import Optional

_FITTED = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                       "simulation", "calibrators", "fitted", "active.pkl")
_cache = None
_loaded = False


def get_calibrator():
    """active.pkl'i lazy yükle + cache. Yoksa/hata → None (safe)."""
    global _cache, _loaded
    if _loaded:
        return _cache
    _loaded = True
    try:
        if os.path.exists(_FITTED):
            import pickle
            with open(_FITTED, "rb") as f:
                _cache = pickle.load(f)
    except Exception:
        _cache = None
    return _cache


def apply_calibration(raw_prob: Optional[float]) -> Optional[float]:
    """raw_prob (0-1) → calibrated_prob. Calibrator yoksa None (no-op). Never-raises."""
    if raw_prob is None:
        return None
    cal = get_calibrator()
    if cal is None:
        return None
    try:
        return round(float(cal.predict([raw_prob])[0]), 4)
    except Exception:
        return None


# ── Phase 5.5 — FLB compensator (SHADOW, env-flag TJK_FLB_ACTIVE) ──
_FLB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "simulation", "calibrators", "fitted", "flb_compensator.pkl")
_flb_cache = None
_flb_loaded = False


def get_flb_compensator():
    """flb_compensator.pkl'i lazy yükle + cache. Yoksa/hata → None (safe). Never-raises."""
    global _flb_cache, _flb_loaded
    if _flb_loaded:
        return _flb_cache
    _flb_loaded = True
    try:
        if os.path.exists(_FLB):
            import pickle
            with open(_FLB, "rb") as f:
                _flb_cache = pickle.load(f)
    except Exception:
        _flb_cache = None
    return _flb_cache


def flb_multiplier(agf_pct: Optional[float]) -> float:
    """agf_pct (0-100) → FLB multiplier. Compensator yoksa 1.0 (no-op). Never-raises."""
    fc = get_flb_compensator()
    if fc is None:
        return 1.0
    try:
        return round(float(fc.multiplier(agf_pct)), 4)
    except Exception:
        return 1.0


def apply_flb_compensation(raw_value: Optional[float], agf_pct: Optional[float]) -> Optional[float]:
    """raw_value × flb_multiplier(agf_pct). Compensator yoksa raw_value (no-op). Never-raises."""
    if raw_value is None:
        return raw_value
    fc = get_flb_compensator()
    if fc is None:
        return raw_value
    try:
        return round(float(fc.compensate(float(raw_value), agf_pct)), 6)
    except Exception:
        return raw_value


# ── Phase 5.6 — v9 9-layer + strateji router (SHADOW, env TJK_V8_STRATEGY_ROUTER) ──
def get_v9_pipeline():
    """v9 shadow runner döndürür: f(result) → shadow META. simulation importable değilse None.

    PROD'da jockey/form YOK → L5/L6 neutral; dataset yoksa skill/surprise graceful-degrade
    (FLB+router yine çalışır). Telegram'a GİTMEZ (bu tur UX kapsam dışı). Never-raises.
    """
    import os as _os
    import sys as _sys
    _repo = _os.path.dirname(_os.path.dirname(_os.path.abspath(__file__)))
    if _repo not in _sys.path:
        _sys.path.insert(0, _repo)
    try:
        import simulation.v9.pipeline as _p  # noqa: F401
    except Exception:
        return None

    def _run(result):
        try:
            from simulation.v9.pipeline import build_v9_race, run_pipeline
            from simulation.v9.carryover_detector import detect_carryover_state
            race = build_v9_race(result, None)   # enr=None → prod: jockey/form yok
            cs = detect_carryover_state(result.get("date"))
            out = run_pipeline(race, cs)
            k, r = out["kupon"], out["routing"]
            return {
                "strategy": r["strategy"], "reason": r["reason"], "budget_band": r["budget_band"],
                "kupon_preview": {
                    "legs_selected": k.get("legs_selected"),
                    "total_cost_proxy": k.get("total_cost"),
                    "tickets": [{"name": t["name"], "combo": t["combo"], "cost": t["cost"]}
                                for t in k.get("tickets", [])]},
                "signals": (k.get("signal_summary") or [])[:6],
                "carryover": cs,
                "router_active": _os.getenv("TJK_V8_STRATEGY_ROUTER", "off") == "on",
                "note": "SHADOW — Telegram'a gitmez; prod'da jockey/form yok→L5/L6 neutral",
            }
        except Exception as e:
            return {"error": repr(e)[:150]}
    return _run
