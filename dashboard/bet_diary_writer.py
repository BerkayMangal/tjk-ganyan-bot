"""Phase 1E.1/1E.2 — Pipeline ↔ bet_diary köprüsü.

write_predictions_for_altili: her altılının top-3/ayak model pick'ini BetRecord'a
  çevirip bet_diary'ye yazar (prediction-time). (Phase 1E.1)
update_outcomes_for_date: retro sonuçlarıyla outcome günceller. (Phase 1E.2)

Coupling: `bet_diary`'yi import eder; yerli_engine / retro'yu ETMEZ (loose).
Never-raises: hata pipeline'ı/retro'yu bloklamaz, sayaç/errors döner.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

import bet_diary as bd

logger = logging.getLogger(__name__)

BANKROLL = 1000.0  # half-Kelly stake birimi (varsayım; recommended_bet_size hesabı)


def _compute_confidence_grade(consensus_all_agree: bool, value_detected: bool,
                              model_agrees_agf: bool) -> str:
    score = int(bool(consensus_all_agree)) + int(bool(value_detected)) + int(bool(model_agrees_agf))
    return {3: "strong", 2: "moderate", 1: "limited", 0: "insufficient"}[score]


def _norm_hippo(s: Any) -> str:
    return (str(s or "")).lower().replace(" hipodromu", "").replace(" hipodrom", "").strip()


def write_predictions_for_altili(
    altili_result: dict,
    agf_alt: Any = None,
    consensus_result: Optional[dict] = None,
    target_date: Any = None,
) -> dict:
    """Top-3/ayak model pick → BetRecord. Returns {records_written, value_bets, errors}."""
    out = {"records_written": 0, "value_bets": 0, "errors": []}
    try:
        legs = altili_result.get("legs_summary") or []
        hippo = altili_result.get("hippodrome")
        altili_no = altili_result.get("altili_no")
        per_leg = (consensus_result or {}).get("per_leg_consensus") or []
        value_set = {(v.get("leg"), v.get("number"))
                     for v in (altili_result.get("value_horses") or [])}

        for leg in legs:
            ayak = leg.get("ayak")
            horses = sorted(leg.get("all_horses_with_mp") or [],
                            key=lambda h: -(h.get("model_prob") or 0))
            cons_leg = next((c for c in per_leg if c.get("ayak") == ayak), {})
            cons_all_agree = bool(cons_leg.get("all_agree"))
            mp_pick, agf_pick = cons_leg.get("model"), cons_leg.get("agf")
            model_agrees_agf = (mp_pick is not None and mp_pick == agf_pick)

            for rank, hr in enumerate(horses[:3], 1):
                try:
                    num = hr.get("number")
                    model_prob = (hr.get("model_prob") or 0.0) / 100.0   # yüzde → 0-1
                    agf_pct = hr.get("agf_pct")
                    odds = bd.odds_from_agf(agf_pct)
                    ev = bd.compute_ev(model_prob, odds) if odds else None
                    kelly = bd.compute_kelly(model_prob, odds) if odds else None
                    rec_size = round(0.5 * kelly * BANKROLL, 2) if kelly else None
                    did_we_bet = (ayak, num) in value_set
                    rec = bd.BetRecord(
                        hippodrome=hippo, race_number=ayak, horse_number=num,
                        model_prob=model_prob, altili_no=altili_no,
                        horse_name=hr.get("name"),
                        agf_pct_at_prediction=agf_pct, odds_at_prediction=odds,
                        ev_at_prediction=ev, kelly_fraction=kelly,
                        recommended_bet_size=rec_size, did_we_bet=did_we_bet,
                        bet_rationale={
                            "value_detected": did_we_bet,
                            "consensus_banko": cons_all_agree,
                            "model_top_pick": rank == 1,
                            "model_vs_agf_agree": model_agrees_agf,
                            "value_edge": hr.get("value_edge"),
                            "model_rank": rank,
                        },
                        confidence_grade=_compute_confidence_grade(
                            cons_all_agree, did_we_bet, model_agrees_agf),
                        consensus_snapshot=cons_leg or None,
                    )
                    if bd.write_bet_decision(rec):
                        out["records_written"] += 1
                        if did_we_bet:
                            out["value_bets"] += 1
                except Exception as e:
                    out["errors"].append(f"{ayak}/{hr.get('number')}: {repr(e)[:60]}")
    except Exception as e:
        out["errors"].append(f"fatal: {repr(e)[:80]}")
    return out


def update_outcomes_for_date(target_date: Any, results: Any,
                             agf_close_data: Optional[dict] = None) -> dict:
    """Retro sonuçlarıyla outcome güncelle. Never-raises.

    results: retro.fetch_results çıktısı — [{hippodrome, altili_no, winners:[{leg_number,
      horse_number}]}]. agf_close_data: opsiyonel {(hippo_norm, altili_no, ayak): agf_pct}
      → CLV proxy. Returns {records_updated, wins, losses, total_pnl_flat, errors}.
    """
    out = {"records_updated": 0, "wins": 0, "losses": 0, "total_pnl_flat": 0.0, "errors": []}
    try:
        wmap = {}
        for r in (results or []):
            hp = _norm_hippo(r.get("hippodrome"))
            ano = r.get("altili_no")
            for w in (r.get("winners") or []):
                wmap[(hp, ano, w.get("leg_number"))] = w.get("horse_number")
        if not wmap:
            return out

        # Phase 1E.2 BUG FIX (2026-06-13): tarih dışı kayıt match etmesin.
        # Önceki: since=date-1d (sadece alt sınır) → gelecek tüm günleri dahil ediyordu;
        # aynı (hippo, altili_no, leg) farklı gün outcome'ları sahte üst-üste update yapıyordu.
        # Yeni: target_date GÜNÜNE ait kayıtları filtre et (predicted_at date == target_date).
        target_iso = None
        if hasattr(target_date, "isoformat"):
            target_iso = target_date.isoformat()[:10]

        for rec in bd.read_bets():
            try:
                if target_iso is not None:
                    rec_day = (rec.get("predicted_at") or "")[:10]
                    if rec_day != target_iso:
                        continue
                key = (_norm_hippo(rec.get("hippodrome")), rec.get("altili_no"),
                       rec.get("race_number"))
                if key not in wmap:
                    continue
                winner = wmap[key]
                won = (rec.get("horse_number") == winner)
                odds = rec.get("odds_at_prediction")
                flat = rec.get("flat_bet_size") or 0.0
                payout = round((odds or 0) * flat, 2) if (won and odds) else 0.0
                odds_close = None
                if agf_close_data:
                    ac = agf_close_data.get(key)
                    odds_close = bd.odds_from_agf(ac) if ac else None
                if bd.update_bet_outcome(rec["prediction_id"], winner, payout,
                                         odds_at_close=odds_close):
                    out["records_updated"] += 1
                    out["wins" if won else "losses"] += 1
                    pnl = (flat * (odds - 1)) if (won and odds) else -flat
                    out["total_pnl_flat"] = round(out["total_pnl_flat"] + pnl, 2)
            except Exception as e:
                out["errors"].append(f"{str(rec.get('prediction_id'))[:8]}: {repr(e)[:50]}")
    except Exception as e:
        out["errors"].append(f"fatal: {repr(e)[:80]}")
    return out
