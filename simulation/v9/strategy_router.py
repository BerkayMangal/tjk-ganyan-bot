"""Phase 5.6 — strateji router. Öncelik: Kangal > Favori Yıkma > Tam Sistem > Pas.

Eşikler VERİ-TÜREVLİ (122-altılı kalibrasyon, phase_5_6_strategy_router_design.md):
- MED_GAP=0.0572 (top1-top2 v9_final gap medyanı) — Tam Sistem "belirgin ayak"
- KANGAL_FY=4 (favori-yıkma ayak sayısı → nadir/özel) — Kangal eşiği
- HEAVY_FAV_PCT=40 (Phase 5.5: ≥40 favori AĞIR overbet, corr~0.55; PROD-available FLB sinyali)
NOT (Phase 5.6.5): favori-yıkma artık "favori v9-top3 dışı" DEĞİL (o L6-hard-zero'ya bağlıydı,
softening sonrası öldü + prod'da L5/L6 yok). Yeni: AĞIR favori (agf≥40) = FLB-overbet fade hedefi.
Tamamen L4(FLB)+agf ile çalışır → PROD'da (jokey/form yokken) da tetiklenir. Bütçe=öneri. payout=PROXY.
"""
from __future__ import annotations

import os

MED_GAP = 0.0572
KANGAL_FY = 4
# Phase 5.8.1 KAZANAN (VARYANT A50): eşik 40→50. Backtest: A40 hit6 %0.8 (coverage öldü) →
# A50 hit6 %4.9 (=V5.1) + cost %30 düşük + OOS-pozitif + Cohen's d +0.12. Sadece EN AĞIR
# favoriler (≥%50, FLB corr~0.51 en overbet) fade edilir; gerisi Tam Sistem (coverage korunur).
HEAVY_FAV_PCT = 50.0   # env TJK_V9_FAV_AGF_THRESHOLD ile override edilebilir
_rf = None


def _fav_threshold():
    """FavoriYıkma AĞIR-favori eşiği. env TJK_V9_FAV_AGF_THRESHOLD (default HEAVY_FAV_PCT)."""
    try:
        return float(os.getenv("TJK_V9_FAV_AGF_THRESHOLD", str(HEAVY_FAV_PCT)))
    except Exception:
        return HEAVY_FAV_PCT


def _risk():
    global _rf
    if _rf is None:
        from simulation.analytics.risk_filter import RiskFilter
        _rf = RiskFilter()
    return _rf


def _leg_signals(agg_leg, race_leg):
    profs = agg_leg.get("profiles") or []
    sig = {"gap": 0.0, "is_fy": False, "surprise": agg_leg.get("surprise_prob", 0.0),
           "fy_alt_numbers": [], "fav_number": None, "leg_risk": 0.0}
    if len(profs) >= 2:
        sig["gap"] = profs[0]["v9_final_score"] - profs[1]["v9_final_score"]
    agf_sorted = sorted(profs, key=lambda p: -p["agf_pct"])
    if agf_sorted and agf_sorted[0]["agf_pct"] >= _fav_threshold():   # AĞIR favori = FLB-overbet fade hedefi
        fav = agf_sorted[0]
        sig["fav_number"] = fav["number"]
        sig["fav_agf"] = fav["agf_pct"]
        sig["is_fy"] = True
        # value alternatifleri: favori DIŞI, value_score (FLB-edge) en yüksek 5
        alts = sorted([p for p in profs if p["number"] != fav["number"]],
                      key=lambda p: -p.get("value_score", 0))
        sig["fy_alt_numbers"] = [p["number"] for p in alts[:5]]
    rf = _risk()
    risks = [rf.risk_score(h.get("agf_pct"), h.get("jockey"), h.get("form_score"))[0]
             for h in (race_leg.get("horses") or [])]
    sig["leg_risk"] = sum(risks) / len(risks) if risks else 0.0
    return sig


def route_strategy(race: dict, aggregated: dict, carryover_state=None) -> dict:
    legs = aggregated.get("legs") or []
    rlegs = race.get("legs") or []
    sigs = [_leg_signals(legs[i], rlegs[i]) for i in range(min(len(legs), len(rlegs)))]
    n_fy = sum(1 for s in sigs if s["is_fy"])
    n_gap = sum(1 for s in sigs if s["gap"] > MED_GAP)
    avg_risk = sum(s["leg_risk"] for s in sigs) / len(sigs) if sigs else 0.0
    max_surprise = max((s["surprise"] for s in sigs), default=0.0)
    carry_day = (carryover_state or {}).get("devir_day", 0)

    from simulation.v9.carryover_detector import budget_shift, special_day_tag
    special = special_day_tag(carryover_state) if carryover_state else ""
    shift = budget_shift(carryover_state) if carryover_state else "normal"

    params = {"sigs": sigs, "n_fy": n_fy, "n_gap": n_gap, "avg_risk": round(avg_risk, 4),
              "max_surprise": round(max_surprise, 3), "carry_day": carry_day,
              "special_day": special}

    # Kangal: çok-favori-yıkma (fy≥4, 95.pct nadir) VEYA (fy≥3 + devir≥2 override)
    if n_fy >= KANGAL_FY or (n_fy >= 3 and carry_day >= 2):
        return {"strategy": "kangal",
                "reason": f"{n_fy} ayakta favori-yıkma (çok-kırılım)"
                          + (" + devir override" if (n_fy < KANGAL_FY and carry_day >= 2) else "")
                          + (f" | {special}" if special else ""),
                "budget_band": (0, 5000), "ticket_design_params": params}

    # Favori Yıkma: ≥2 favori-yıkma ayağı
    if n_fy >= 2:
        return {"strategy": "favori_yikma",
                "reason": f"{n_fy} ayakta public favori-overbet, sistem yıkıyor"
                          + (f" | {special}" if special else ""),
                "budget_band": (1000, 3000), "ticket_design_params": params}

    # Tam Sistem: belirgin kart (≥3 gap-ayak), favori-yıkma az
    if n_gap >= 3 and n_fy <= 1:
        band = (4000, 6000) if shift != "upper" else (5000, 6000)
        return {"strategy": "tam_sistem",
                "reason": f"{n_gap} ayakta belirgin v9 lider, dengeli kart"
                          + (f" | {special}" if special else ""),
                "budget_band": band, "ticket_design_params": params}

    # Pas
    return {"strategy": "pas",
            "reason": f"net edge yok (fy={n_fy}, gap-ayak={n_gap}) — sinyal zayıf",
            "budget_band": (0, 0), "ticket_design_params": params}
