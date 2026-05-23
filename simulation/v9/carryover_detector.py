"""Phase 5.6 L1 — carryover (devir) detection.

Probe sonucu: TJK statik sayfalarında devir/ikramiye field YOK (JS-render). Pool size + hit-data
da yok → otomatik tespit VİYABİL DEĞİL. Fallback: MANUEL env `TJK_CARRYOVER_DAY` (0/1/2/3).
Berkay sabah Telegram'da devir görürse env set eder. Never-raises.

L1 semantiği (router kullanır):
- gün 0/1: nötr (multiplier 1.0, hiçbir şey değişmez)
- gün 2: Kangal 3. tetik şartı (risk-clean) override + "ÖZEL GÜN" etiketi
- gün 3 (mandatory payout): Kangal tetik tam relax + bütçe önerisi ÜST banda kayar
"""
from __future__ import annotations

import os


def detect_carryover_state(date=None, race_id=None) -> dict:
    """Returns {is_carryover, devir_day, accumulated_pot_tl, confidence, source}."""
    raw = os.getenv("TJK_CARRYOVER_DAY", "").strip()
    try:
        day = int(raw) if raw else 0
    except ValueError:
        day = 0
    day = max(0, min(3, day))
    pot = None
    pot_raw = os.getenv("TJK_CARRYOVER_POT_TL", "").strip()
    if pot_raw:
        try:
            pot = float(pot_raw)
        except ValueError:
            pot = None
    return {
        "is_carryover": day >= 1,
        "devir_day": day,
        "accumulated_pot_tl": pot,
        "confidence": "manual" if day >= 1 else "none",
        "source": "env:TJK_CARRYOVER_DAY" if raw else "default(no_auto_source)",
    }


def kangal_trigger_override(state: dict) -> bool:
    """Devir gün ≥2 → Kangal'ın 3. şartını (risk-clean) override eder."""
    return bool(state and state.get("devir_day", 0) >= 2)


def budget_shift(state: dict) -> str:
    """Bütçe bandı önerisi kayması. gün 3 → üst banda."""
    d = state.get("devir_day", 0) if state else 0
    return "upper" if d >= 3 else "normal"


def special_day_tag(state: dict) -> str:
    d = state.get("devir_day", 0) if state else 0
    if d >= 3:
        return "ÖZEL GÜN — 3. DEVİR (mandatory payout, pozitif-EV penceresi)"
    if d >= 2:
        return "ÖZEL GÜN — 2. devir"
    if d >= 1:
        return "devir 1. gün"
    return ""
