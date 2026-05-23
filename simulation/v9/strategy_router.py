"""Phase 5.6 — strateji router. Öncelik: Kangal > Favori Yıkma > Tam Sistem > Pas.

Eşikler VERİ-TÜREVLİ (122-altılı kalibrasyon, phase_5_6_strategy_router_design.md):
- MED_GAP=0.0572 (top1-top2 v9_final gap medyanı) — Tam Sistem "belirgin ayak"
- KANGAL_FY=4 (favori-yıkma ayak sayısı 95. pct → nadir/özel) — Kangal eşiği
- favori eşiği %30 (Phase 5.5: favori-overbet ≥30 başlar)
NOT: "risk-clean" şartı KALDIRILDI — çok-favori-yıkma yüksek-AGF favori = yüksek FLB-risk →
risk-clean ∩ fy≥3 ≈ boş (çelişkili). Kangal nadir'liği fy≥4 (95.pct) + carryover ile sağlanır.
Bütçe bantları = ÖNERİ (sistem durdurmaz; Berkay karar verici). payout=PROXY.
"""
from __future__ import annotations

MED_GAP = 0.0572
KANGAL_FY = 4
FAV_AGF_PCT = 30.0
_rf = None


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
    if agf_sorted and agf_sorted[0]["agf_pct"] >= FAV_AGF_PCT:
        fav = agf_sorted[0]
        sig["fav_number"] = fav["number"]
        top3 = [p["number"] for p in profs[:3]]
        if fav["number"] not in top3:               # sistem favoriyi top-3 dışına itti
            sig["is_fy"] = True
            sig["fy_alt_numbers"] = [p["number"] for p in profs[:5]]  # v9 value top-5
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
