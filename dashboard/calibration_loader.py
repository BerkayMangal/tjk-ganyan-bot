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
