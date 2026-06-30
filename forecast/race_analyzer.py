"""Tek koşu derin analiz motoru: V8 + Monte Carlo + 3 tempo + composite.

Berkay (2026-06-27): Gazi ULTRA raporundaki MC + tempo + composite mantığını
HER yarış için uygulayalım, top-4 tahminlerini zenginleştirelim.

API:
  analyze_race(leg, ref_date, ledger=None, history_lookup=None,
               n_mc=10000, n_tempo=5000) → dict

Çıktı:
  {
    "winner":            {no, name, score, mc_p1, v8_p4, tempo_top3_count, pace},
    "v8_top4":           V8 P(top-4) sıralı 4 at,
    "mc_top4":           Monte Carlo'da en sık 1. olan 4 at,
    "composite_top4":    Birleşik skor sıralı 4 at,
    "top4_overlap":      3 listenin örtüşme sayısı (0-4) → güven göstergesi,
    "race_tempo_verdict": "YAVAŞ"/"KONTROLLÜ"/"HIZLI"/"SERT",
    "per_horse_pace":    {horse_no: "front"/"stalker"/"closer"/"mid"},
    "mc":                {"rank_pct", "top4_orders", "top1_count"},
    "tempo_sims":        {"YAVAŞ"/"ORTA"/"SERT": ...},
    "composite_ranking": tüm atlar composite skor sıralı,
    "v8_preds":          V8 ham çıktı (sorted by p_top4 desc),
  }

NEVER raises — eksik veri/exception graceful boş döner.
"""
from __future__ import annotations

import logging
import random
from collections import Counter
from typing import Callable, Optional

logger = logging.getLogger(__name__)


# ─── Plackett-Luce simulation (özerk kopya) ────────────────────────────────
def _plackett_luce_sims(strengths: list, n_sims: int, seed: int = 42) -> dict:
    rng = random.Random(seed)
    if not strengths:
        return {"rank_pct": {}, "top4_orders": [], "top1_count": {}}
    n = len(strengths)
    rank_counts = {h[0]: Counter() for h in strengths}
    top4_counter: Counter = Counter()
    top1_count: Counter = Counter()
    for _ in range(n_sims):
        pool = list(strengths)
        order = []
        for rank in range(1, n + 1):
            total = sum(h[2] for h in pool)
            if total <= 0:
                break
            r = rng.random() * total
            acc = 0.0
            picked_idx = 0
            for i, h in enumerate(pool):
                acc += h[2]
                if acc >= r:
                    picked_idx = i
                    break
            picked = pool.pop(picked_idx)
            order.append(picked[0])
            key = rank if rank <= 4 else "5+"
            rank_counts[picked[0]][key] += 1
            if rank == 1:
                top1_count[picked[0]] += 1
        if len(order) >= 4:
            top4_counter[tuple(order[:4])] += 1
    rank_pct = {hid: {k: 100.0 * v / n_sims for k, v in ctr.items()}
                for hid, ctr in rank_counts.items()}
    return {"rank_pct": rank_pct,
            "top4_orders": top4_counter.most_common(10),
            "top1_count": top1_count}


# Pace × tempo strength multiplier (Gazi raporundaki defansif kalibrasyon)
_PACE_TEMPO_MULT = {
    "YAVAŞ": {"front": 1.30, "stalker": 1.05, "mid": 1.00, "closer": 0.80},
    "ORTA":  {"front": 1.00, "stalker": 1.20, "mid": 1.05, "closer": 0.95},
    "SERT":  {"front": 0.65, "stalker": 0.95, "mid": 1.10, "closer": 1.45},
}


def _tempo_scenario_sim(v8_preds: list, pace_by_no: dict, tempo: str,
                        n_sims: int) -> dict:
    mults = _PACE_TEMPO_MULT[tempo]
    strengths = []
    for p in v8_preds:
        no = p.get("horse_no")
        pace = pace_by_no.get(no, "mid")
        base = max(0.001, p.get("p_top1") or 0.01)
        strengths.append((no, p.get("horse_name"),
                          base * mults.get(pace, 1.0)))
    seed = {"YAVAŞ": 11, "ORTA": 22, "SERT": 33}.get(tempo, 42)
    return _plackett_luce_sims(strengths, n_sims, seed=seed)


def _load_calibrated_weights():
    """simulation/calibrators/composite_weights.json → (α, β, γ, δ).

    α = MC(1.olma), β = V8(p_top4), γ = tempo robust, δ = V7(model_prob).
    Eski 3-değişken composite (delta yoksa) backward-compat: δ=0.
    """
    import json
    from pathlib import Path
    p = (Path(__file__).resolve().parent.parent
         / "simulation" / "calibrators" / "composite_weights.json")
    try:
        with open(p) as f:
            d = json.load(f)
        b = d.get("best") or {}
        return (
            b.get("alpha", 0.60), b.get("beta", 0.25),
            b.get("gamma", 0.15), b.get("delta", 0.0),
        )
    except Exception:
        return (0.60, 0.25, 0.15, 0.0)


COMPOSITE_WEIGHTS = _load_calibrated_weights()


def _composite_winner(v8_preds: list, mc: dict, tempo_sims: dict,
                      pace_by_no: dict, v7_prob_by_no: dict = None,
                      agf_delta_by_no: dict = None,
                      foreign_form_by_no: dict = None,
                      big_sire_by_no: dict = None,
                      uk_champion_by_no: dict = None,
                      uk_steam_by_no: dict = None) -> dict:
    """Composite skor — V9.5 + V7 hibrit + AGF Δ + foreign form bonus.

    score = α·MC + β·V9.5(p_top4) + γ·tempo + δ·V7 + ε·AGF_Δ
            + ζ·foreign_form_cross_value

    ζ (zeta) = TJK_FOREIGN_FORM_WEIGHT (default 0.08)
      cross_value = foreign_form_score × (1 - agf/20)
      UK form güçlü + TJK AGF düşük → underrated bonus
    """
    import os
    alpha, beta, gamma, delta = COMPOSITE_WEIGHTS
    eps = float(os.environ.get("TJK_AGF_DELTA_WEIGHT", "0.05"))
    zeta = float(os.environ.get("TJK_FOREIGN_FORM_WEIGHT", "0.08"))
    eta = float(os.environ.get("TJK_BIG_SIRE_WEIGHT", "0.05"))   # ALFA 1
    theta = float(os.environ.get("TJK_UK_CHAMPION_WEIGHT", "0.04"))  # ALFA 2
    iota = float(os.environ.get("TJK_UK_STEAM_WEIGHT", "0.10"))  # ALFA 3 — en güçlü
    if v7_prob_by_no is None:
        v7_prob_by_no = {}
    if agf_delta_by_no is None:
        agf_delta_by_no = {}
    if foreign_form_by_no is None:
        foreign_form_by_no = {}
    if big_sire_by_no is None:
        big_sire_by_no = {}
    if uk_champion_by_no is None:
        uk_champion_by_no = {}
    if uk_steam_by_no is None:
        uk_steam_by_no = {}

    robust: Counter = Counter()
    for t in ("YAVAŞ", "ORTA", "SERT"):
        sim = tempo_sims.get(t, {})
        top1c = sim.get("top1_count", {})
        ranking = sorted(top1c.items(), key=lambda x: -x[1])[:3]
        for no, _ in ranking:
            robust[no] += 1

    max_p4 = max((p.get("p_top4") or 0) for p in v8_preds) or 1.0
    mc_p1 = {no: pct.get(1, 0) for no, pct in mc.get("rank_pct", {}).items()}
    max_mc1 = max(mc_p1.values()) if mc_p1 else 1.0
    max_v7 = max([(v or 0) for v in v7_prob_by_no.values()] or [0]) or 1.0

    scores = []
    for p in v8_preds:
        no = p.get("horse_no")
        mc1n = (mc_p1.get(no, 0) / max_mc1) if max_mc1 else 0
        p4n = ((p.get("p_top4") or 0) / max_p4) if max_p4 else 0
        rb = robust.get(no, 0) / 3.0
        v7_raw = v7_prob_by_no.get(no, 0) or 0
        v7n = (v7_raw / max_v7) if max_v7 else 0
        # AGF intraday Δ sinyali (steam=+1, drift=-1, nötr=0)
        agf_delta_pp = agf_delta_by_no.get(no, 0)
        if agf_delta_pp >= 5.0:
            agf_signal = 1.0
            agf_tag = "STEAM"
        elif agf_delta_pp <= -5.0:
            agf_signal = -1.0
            agf_tag = "DRIFT"
        else:
            agf_signal = 0.0
            agf_tag = ""
        # Foreign form cross-value (zeta term)
        ff = foreign_form_by_no.get(no, {}) if foreign_form_by_no else {}
        cross_val = ff.get("cross_value", 0) if ff else 0
        # ALFA 1 — Big Sire (eta)
        bs = big_sire_by_no.get(no, {}) or {}
        bs_score = bs.get("score", 0)
        # ALFA 2 — UK Champion (theta)
        uc = uk_champion_by_no.get(no, {}) or {}
        uc_score = uc.get("score", 0) / 2.0  # max 2 → normalize 0-1
        # ALFA 3 — UK Steam (iota)
        us = uk_steam_by_no.get(no, {}) or {}
        us_score = us.get("score", 0)
        scores.append({
            "no": no, "name": p.get("horse_name"),
            "score": (alpha * mc1n + beta * p4n + gamma * rb
                      + delta * v7n + eps * agf_signal
                      + zeta * cross_val + eta * bs_score
                      + theta * uc_score + iota * us_score),
            "mc_p1": mc_p1.get(no, 0),
            "v8_p4": (p.get("p_top4") or 0) * 100,
            "v8_p1": (p.get("p_top1") or 0) * 100,
            "v7_prob": v7_raw * 100,
            "tempo_top3_count": robust.get(no, 0),
            "pace": pace_by_no.get(no, "mid"),
            "agf_delta_pp": agf_delta_pp,
            "agf_tag": agf_tag,
            "foreign_form": ff.get("form_string", ""),
            "foreign_tag": ff.get("tag", ""),
            "cross_value": cross_val,
            # ALFA tags
            "big_sire_tag": bs.get("tag", ""),
            "big_sire_score": bs_score,
            "uk_champion_tags": uc.get("tags", []),
            "uk_steam_tag": us.get("tag", ""),
            "uk_steam_pct": us.get("delta_pct", 0),
        })
    scores.sort(key=lambda x: -x["score"])
    return {"ranking": scores, "winner": scores[0] if scores else None}


def _pace_style(history: list) -> str:
    """Pace style fallback (forecast.pace.pace.infer_pace_style olmazsa 'mid')."""
    try:
        from forecast.pace.pace import infer_pace_style
        ps = infer_pace_style(history or [])
        return getattr(ps, "primary", "mid")
    except Exception:
        return "mid"


def _race_tempo(n_front: int) -> str:
    if n_front >= 3:
        return "SERT"
    if n_front == 2:
        return "HIZLI"
    if n_front == 1:
        return "KONTROLLÜ"
    return "YAVAŞ"


def _top4_overlap(v8_set: set, mc_set: set, comp_set: set) -> int:
    """3 listenin (V8/MC/Composite) at başına örtüşme sayısı (0-4)."""
    common = v8_set & mc_set & comp_set
    return len(common)


def analyze_race(
    leg: list,
    ref_date: str,
    ledger=None,
    history_lookup: Optional[Callable[[str], list]] = None,
    n_mc: int = 5000,
    n_tempo: int = 3000,
) -> dict:
    """Tek bir koşunun derin analizi. NEVER raises (boş dict döner)."""
    if not leg:
        return {}
    try:
        # 1) V8 predict
        try:
            from model.v8.inference import predict_race
            v8_preds = predict_race(
                horses=leg, history_lookup=history_lookup,
                glicko_ledger=ledger, ref_date=ref_date,
            )
        except Exception as exc:
            logger.warning(f"V8 predict_race fail: {exc}")
            return {}
        if not v8_preds:
            return {}
        v8_preds.sort(key=lambda p: -(p.get("p_top4") or 0))

        # 2) Pace per horse
        per_horse_pace: dict = {}
        for h in leg:
            no = (h.get("horse_no") or h.get("horse_number")
                  or h.get("number"))
            nm = h.get("horse_name") or h.get("name") or ""
            if history_lookup is not None and nm:
                try:
                    hist = history_lookup(nm) or []
                except Exception:
                    hist = []
            else:
                hist = []
            per_horse_pace[no] = _pace_style(hist)

        # 3) Monte Carlo (baz, V8 p_top1 strength)
        strengths = [(p.get("horse_no"), p.get("horse_name"),
                      max(0.001, p.get("p_top1") or 0.01))
                     for p in v8_preds]
        mc = _plackett_luce_sims(strengths, n_mc, seed=42)

        # 4) 3 tempo senaryosu
        tempo_sims = {
            t: _tempo_scenario_sim(v8_preds, per_horse_pace, t, n_tempo)
            for t in ("YAVAŞ", "ORTA", "SERT")
        }

        # V7 model_prob per horse (smart_coupon legs'inden)
        v7_prob_by_no = {}
        for h in leg:
            no = (h.get("horse_no") or h.get("horse_number")
                  or h.get("number"))
            mp = h.get("model_prob")
            if isinstance(mp, (int, float)) and mp > 0:
                v7_prob_by_no[no] = float(mp)

        # AGF intraday Δ per horse (insider/steam signal)
        agf_delta_by_no = {}
        try:
            from forecast.agf_intraday import detect_steam_moves
            hippo_name = ""
            if leg and isinstance(leg[0], dict):
                hippo_name = (leg[0].get("hippo")
                              or leg[0].get("hippodrome") or "")
            if ref_date and hippo_name:
                steam_result = detect_steam_moves(ref_date, hippo_name)
                for c in steam_result.get("comparisons", []):
                    agf_delta_by_no[c["at_no"]] = c["delta_pp"]
        except Exception:
            pass

        # Foreign form bridge (cross-market UK reference)
        foreign_form_by_no = {}
        if os.environ.get("TJK_FOREIGN_FORM", "1") == "1":
            try:
                from forecast.foreign_form_bridge import (
                    bridge_lookup, score_cross_market_value,
                )
                for h in leg:
                    no = (h.get("horse_no") or h.get("horse_number"))
                    nm = h.get("horse_name") or h.get("name") or ""
                    agf = h.get("agf_value") or 0
                    if not nm:
                        continue
                    fb = bridge_lookup(nm, ref_date)
                    if fb.get("has_foreign_form"):
                        cv = score_cross_market_value(
                            agf, fb.get("form_score", 0))
                        foreign_form_by_no[no] = {
                            "form_score": fb.get("form_score", 0),
                            "tag": fb.get("tag", ""),
                            "cross_value": cv,
                            "form_string": fb.get("form_string", ""),
                        }
            except Exception as exc:
                logger.debug(f"foreign form bridge fail: {exc}")

        # ALFA 1 — Big Sire Detection
        big_sire_by_no = {}
        if os.environ.get("TJK_BIG_SIRE", "1") == "1":
            try:
                from forecast.pedigree_intel import check_big_sire
                distance = (leg[0].get("distance") if leg else None)
                track_type = (leg[0].get("track_type") if leg else "")
                for h in leg:
                    no = (h.get("horse_no") or h.get("horse_number"))
                    sire = (h.get("sire") or h.get("sire_name")
                            or h.get("orijin", "").split("/")[0].strip())
                    result = check_big_sire(sire, distance, track_type)
                    if result.get("is_big_sire"):
                        big_sire_by_no[no] = result
            except Exception as exc:
                logger.debug(f"big sire fail: {exc}")

        # ALFA 2 — UK Champion Trainer/Jockey
        uk_champion_by_no = {}
        if os.environ.get("TJK_UK_CHAMPION", "1") == "1":
            try:
                from forecast.uk_champions import check_uk_champion
                for h in leg:
                    no = (h.get("horse_no") or h.get("horse_number"))
                    jockey = (h.get("jockey_name") or h.get("jockey")
                              or "")
                    trainer = (h.get("trainer_name") or h.get("trainer")
                               or "")
                    result = check_uk_champion(jockey, trainer)
                    if result.get("score", 0) > 0:
                        uk_champion_by_no[no] = result
            except Exception as exc:
                logger.debug(f"uk champion fail: {exc}")

        # ALFA 3 — UK Live Odds Steam
        uk_steam_by_no = {}
        if os.environ.get("TJK_UK_STEAM", "1") == "1":
            try:
                from forecast.uk_live_odds import get_uk_steam_signal
                for h in leg:
                    no = (h.get("horse_no") or h.get("horse_number"))
                    nm = h.get("horse_name") or h.get("name") or ""
                    if not nm or not ref_date:
                        continue
                    result = get_uk_steam_signal(nm, ref_date)
                    if result.get("has_steam"):
                        uk_steam_by_no[no] = result
            except Exception as exc:
                logger.debug(f"uk steam fail: {exc}")

        # 5) Composite winner — tüm alfa katmanlarıyla
        composite = _composite_winner(v8_preds, mc, tempo_sims,
                                       per_horse_pace, v7_prob_by_no,
                                       agf_delta_by_no,
                                       foreign_form_by_no,
                                       big_sire_by_no=big_sire_by_no,
                                       uk_champion_by_no=uk_champion_by_no,
                                       uk_steam_by_no=uk_steam_by_no)

        # 6) 3 farklı TOP-5 listesi (Berkay direktif: top-5)
        name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
        v8_top5 = [{"no": p.get("horse_no"), "name": p.get("horse_name"),
                    "p_top4": p.get("p_top4")} for p in v8_preds[:5]]
        mc_top1_sorted = sorted(mc["top1_count"].items(),
                                 key=lambda x: -x[1])[:5]
        mc_top5 = [{"no": no, "name": name_by_no.get(no),
                    "mc_p1": 100 * cnt / n_mc}
                   for no, cnt in mc_top1_sorted]
        composite_top5 = [
            {"no": r["no"], "name": r["name"], "score": r["score"],
             "pace": r["pace"], "mc_p1": r["mc_p1"], "v8_p4": r["v8_p4"]}
            for r in composite["ranking"][:5]
        ]
        # Geri-uyumluluk: top-4 isimleri de korunur (mevcut tüketiciler)
        v8_top4 = v8_top5[:4]
        mc_top4 = mc_top5[:4]
        composite_top4 = composite_top5[:4]
        overlap = _top4_overlap(
            {x["no"] for x in v8_top4},
            {x["no"] for x in mc_top4},
            {x["no"] for x in composite_top4},
        )
        # Top-5 örtüşmesi de hesapla (daha geniş güven)
        overlap5 = len({x["no"] for x in v8_top5}
                       & {x["no"] for x in mc_top5}
                       & {x["no"] for x in composite_top5})

        # 7) Race tempo verdict (pace dağılımı)
        n_front = sum(1 for p in per_horse_pace.values() if p == "front")
        n_closer = sum(1 for p in per_horse_pace.values() if p == "closer")
        tempo_verdict = _race_tempo(n_front)

        return {
            "winner": composite["winner"],
            "v8_top4": v8_top4,
            "mc_top4": mc_top4,
            "composite_top4": composite_top4,
            "v8_top5": v8_top5,
            "mc_top5": mc_top5,
            "composite_top5": composite_top5,
            "top4_overlap": overlap,
            "top5_overlap": overlap5,
            "race_tempo_verdict": tempo_verdict,
            "n_front": n_front,
            "n_closer": n_closer,
            "per_horse_pace": per_horse_pace,
            "mc": mc,
            "tempo_sims": tempo_sims,
            "composite_ranking": composite["ranking"],
            "v8_preds": v8_preds,
            "n_horses": len(leg),
            "composite_weights": COMPOSITE_WEIGHTS,  # (α, β, γ) kalibre
        }
    except Exception as exc:
        logger.warning(f"analyze_race fail: {exc}")
        return {}


# ─── Telegram-friendly özetleyici ──────────────────────────────────────────
PACE_TR = {"front": "öne çıkan", "stalker": "takipçi",
           "closer": "finiş hücumcusu", "mid": "orta tempolu",
           "unknown": "tanımsız"}


def confidence_tag(overlap: int) -> str:
    """3 top-4 listesinin örtüşmesi → tek kelimelik güven etiketi."""
    return {4: "ÇOK YÜKSEK", 3: "YÜKSEK",
            2: "ORTA", 1: "DÜŞÜK", 0: "ÇOK DÜŞÜK"}.get(overlap, "—")


def race_summary_lines(analysis: dict, race_no, hippo: str = "") -> list[str]:
    """Tek koşu için Telegram digest satırları."""
    if not analysis or not analysis.get("winner"):
        return []
    w = analysis["winner"]
    tempo = analysis.get("race_tempo_verdict", "—")
    overlap = analysis.get("top4_overlap", 0)
    tag = confidence_tag(overlap)
    lines = []
    lines.append(f"<b>{race_no}. KOŞU</b>  ·  tempo: {tempo}  ·  "
                 f"güven: {tag} ({overlap}/4)")
    lines.append(f"  🏆 <b>#{w['no']} {w['name']}</b>  "
                 f"(MC %{w.get('mc_p1', 0):.1f} · ilk-4 %{w.get('v8_p4', 0):.1f} "
                 f"· {PACE_TR.get(w.get('pace', 'mid'), '—')})")
    # 3 top-4 listesi
    comp4 = analysis.get("composite_top4") or []
    if comp4:
        names = " · ".join(f"#{x['no']} {x['name']}" for x in comp4[:4])
        lines.append(f"  🎯 <b>TOP-4 (birleşik):</b> {names}")
    return lines
