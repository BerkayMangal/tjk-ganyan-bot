"""Phase 5.1 — Altılı simulator core.

simulate_altili: bir altılı (snapshot result + gerçek sonuç) + bir strateji adaptörü →
hit/partial/payout/ROI. Strateji adaptörleri (simulation/strategies/) mevcut kupon
builder'larını read-only wrap eder; bu modül onları skorlar.

NOT: payout bir PROXY'dir (pari-mutuel ters-olasılık yaklaşımı), gerçek TJK ödeme tablosu
DEĞİL. SLOW track'te (geçmiş AGF yok) gerçek payout backtest'i Phase 5.2+ sonrası.
"""
from __future__ import annotations

from typing import Any, Callable, Optional

# Surprise tanımı (magic_numbers.md): kazanan AGF rank > 3 VEYA AGF% < 20.
SURPRISE_AGF_RANK = 3
SURPRISE_AGF_PCT = 20.0


def _winner_agf_pct(result: dict, ayak: int, winner_no: int) -> Optional[float]:
    """legs_summary[ayak].all_horses_with_mp içinden kazananın AGF%'i."""
    for leg in result.get("legs_summary", []) or []:
        if leg.get("ayak") == ayak:
            for h in leg.get("all_horses_with_mp", []) or []:
                if h.get("number") == winner_no:
                    return h.get("agf_pct")
    return None


def _is_surprise(result: dict, ayak: int, winner_no: int) -> bool:
    """Kazanan sürpriz mi: AGF% < eşik (rank verisi yoksa pct proxy)."""
    pct = _winner_agf_pct(result, ayak, winner_no)
    if pct is None:
        return True  # bilinmiyorsa sürpriz say (konservatif)
    return pct < SURPRISE_AGF_PCT


def _payout_proxy(result: dict, actual_results: list, unit_price: float, combo: int) -> float:
    """Pari-mutuel ters-olasılık PROXY'si (gerçek ödeme DEĞİL).

    payout ≈ unit · combo / Π(winner_agf_share). Düşük-AGF kazananlar (sürpriz) →
    yüksek payout. Sadece relative karşılaştırma için; mutlak TL anlamı yok.
    """
    joint = 1.0
    for ayak, winner in enumerate(actual_results, start=1):
        pct = _winner_agf_pct(result, ayak, winner)
        share = (pct / 100.0) if pct and pct > 0 else 0.02  # bilinmeyen → düşük
        joint *= max(0.01, share)
    if joint <= 0:
        return 0.0
    return round(unit_price * combo / joint, 2)


def simulate_altili(
    race_data: dict,            # snapshot result (live_tests formatı: legs_summary, hippodrome, ...)
    actual_results: list,       # [ayak1_winner, ..., ayak6_winner] gerçek kazanan at no
    strategy_fn: Callable[[dict], dict],  # result → {name, legs_selected, cost, combo}
    unit_price: float = 1.25,
    prob_field: str = "model_prob",  # "model_prob" | "calibrated_prob" (forward: kalibre vs raw)
) -> dict:
    """Tek altılı simülasyonu. Returns hit/partial/payout/roi.

    prob_field: adaptöre hangi olasılık alanını kullanacağını bildirir (race_data._prob_field).
    Forward kullanım — tarihsel model_prob yok (Phase 5.2), şu an adaptörler model_prob default.
    """
    race_data = {**race_data, "_prob_field": prob_field}
    try:
        kupon = strategy_fn(race_data)
    except Exception as e:
        return {"strategy_name": getattr(strategy_fn, "__name__", "?"),
                "error": f"strategy_failed:{repr(e)[:80]}", "hit": False,
                "partial_hits": 0, "cost": 0.0, "payout": 0.0, "roi": 0.0, "kupon": None}

    legs_selected = kupon.get("legs_selected") or []
    cost = float(kupon.get("cost") or 0.0)
    combo = int(kupon.get("combo") or 1)

    # Hit / partial: her ayakta gerçek kazanan seçilenler içinde mi
    partial = 0
    for ayak, winner in enumerate(actual_results, start=1):
        if ayak - 1 < len(legs_selected):
            if winner in (legs_selected[ayak - 1] or []):
                partial += 1
    hit = (partial == len(actual_results) and len(actual_results) > 0)

    payout = _payout_proxy(race_data, actual_results, unit_price, combo) if hit else 0.0
    roi = ((payout - cost) / cost) if cost > 0 else 0.0

    surprises = sum(1 for ay, w in enumerate(actual_results, 1) if _is_surprise(race_data, ay, w))

    return {
        "strategy_name": kupon.get("name", getattr(strategy_fn, "__name__", "?")),
        "kupon": kupon,
        "cost": round(cost, 2),
        "hit": hit,
        "partial_hits": partial,
        "n_surprises": surprises,
        "payout": payout,           # PROXY
        "roi": round(roi, 3),       # PROXY (payout proxy'ye dayalı)
        "combo": combo,
    }


def compare_strategies(race_data: dict, actual_results: list,
                       strategy_fns: list, unit_price: float = 1.25,
                       prob_field: str = "model_prob") -> list:
    """Aynı altılıda birden fazla stratejiyi yan yana koştur."""
    return [simulate_altili(race_data, actual_results, fn, unit_price, prob_field)
            for fn in strategy_fns]
