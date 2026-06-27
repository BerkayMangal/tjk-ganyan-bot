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


def _composite_winner(v8_preds: list, mc: dict, tempo_sims: dict,
                      pace_by_no: dict) -> dict:
    """Composite skor = 0.50 × MC(1.) + 0.30 × V8(p_top4) + 0.20 × tempo robust."""
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
    scores = []
    for p in v8_preds:
        no = p.get("horse_no")
        mc1n = (mc_p1.get(no, 0) / max_mc1) if max_mc1 else 0
        p4n = ((p.get("p_top4") or 0) / max_p4) if max_p4 else 0
        rb = robust.get(no, 0) / 3.0
        scores.append({
            "no": no, "name": p.get("horse_name"),
            "score": 0.50 * mc1n + 0.30 * p4n + 0.20 * rb,
            "mc_p1": mc_p1.get(no, 0),
            "v8_p4": (p.get("p_top4") or 0) * 100,
            "v8_p1": (p.get("p_top1") or 0) * 100,
            "tempo_top3_count": robust.get(no, 0),
            "pace": pace_by_no.get(no, "mid"),
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
    n_mc: int = 10000,
    n_tempo: int = 5000,
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

        # 5) Composite winner
        composite = _composite_winner(v8_preds, mc, tempo_sims,
                                       per_horse_pace)

        # 6) 3 farklı TOP-4 listesi
        name_by_no = {p.get("horse_no"): p.get("horse_name") for p in v8_preds}
        v8_top4 = [{"no": p.get("horse_no"), "name": p.get("horse_name"),
                    "p_top4": p.get("p_top4")} for p in v8_preds[:4]]
        mc_top1_sorted = sorted(mc["top1_count"].items(),
                                 key=lambda x: -x[1])[:4]
        mc_top4 = [{"no": no, "name": name_by_no.get(no),
                    "mc_p1": 100 * cnt / n_mc}
                   for no, cnt in mc_top1_sorted]
        composite_top4 = [
            {"no": r["no"], "name": r["name"], "score": r["score"],
             "pace": r["pace"], "mc_p1": r["mc_p1"], "v8_p4": r["v8_p4"]}
            for r in composite["ranking"][:4]
        ]
        overlap = _top4_overlap(
            {x["no"] for x in v8_top4},
            {x["no"] for x in mc_top4},
            {x["no"] for x in composite_top4},
        )

        # 7) Race tempo verdict (pace dağılımı)
        n_front = sum(1 for p in per_horse_pace.values() if p == "front")
        n_closer = sum(1 for p in per_horse_pace.values() if p == "closer")
        tempo_verdict = _race_tempo(n_front)

        return {
            "winner": composite["winner"],
            "v8_top4": v8_top4,
            "mc_top4": mc_top4,
            "composite_top4": composite_top4,
            "top4_overlap": overlap,
            "race_tempo_verdict": tempo_verdict,
            "n_front": n_front,
            "n_closer": n_closer,
            "per_horse_pace": per_horse_pace,
            "mc": mc,
            "tempo_sims": tempo_sims,
            "composite_ranking": composite["ranking"],
            "v8_preds": v8_preds,
            "n_horses": len(leg),
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
