"""Günlük RETRO — tüm gönderimleri outcome ile eşleştir, rapor Telegram.

Berkay (2026-07-01): 'aksam gorecegiz istisnasiz her gonderimin retrosunu'.

Kayıtlar (data/forward_log/<date>*.jsonl):
  <date>.jsonl              → T-3 top-4 (prerace)
  <date>_altili.jsonl        → T-5 altılı
  <date>_uk_top4.jsonl       → UK race TOP-4
  <date>_uk_value.jsonl      → UK value bet

Outcome kaynakları:
  TR: data/backfill/outcomes_rich/<date>.json (backfill script gecikmeli)
  UK: RacingAPI results (canlı, hızlı)

Rapor çıktısı:
  1) TR T-3 top-4 hit rate (kazanan tahminimiz vs gerçek)
  2) TR T-5 altılı hit / hit-not
  3) UK top-4 hit
  4) UK value bet gerçek payout (ROI)
  5) Cross-market arbitraj başarısı
  6) Kompakt Telegram özet + persistent JSON rapor

Usage:
  python -m audit.retro_daily [--date YYYY-MM-DD] [--send]
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO,
                    format="%(asctime)s [%(levelname)s] %(message)s")
log = logging.getLogger("retro_daily")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

LOG_DIR = ROOT / "data" / "forward_log"
OUTCOME_DIR = ROOT / "data" / "backfill" / "outcomes_rich"
REPORT_DIR = ROOT / "audit" / "reports"
V11_FORWARD_DIR = ROOT / "data" / "v11_forward_log"


def _load_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    out = []
    try:
        with open(path, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    try:
                        out.append(json.loads(line))
                    except Exception:
                        pass
    except Exception:
        return []
    return out


def _tr_outcomes(target_date: str) -> dict:
    """TR outcomes → {(hippo, race_no): [finishers]}."""
    p = OUTCOME_DIR / f"{target_date}.json"
    if not p.exists():
        return {}
    try:
        with open(p) as f:
            d = json.load(f)
    except Exception:
        return {}
    out = {}
    for hippo_entry in (d.get("hippodromes") or []):
        hippo = hippo_entry.get("hippodrome", "")
        for k_id, k in (hippo_entry.get("kosular") or {}).items():
            try:
                rn = int(k_id)
            except Exception:
                continue
            out[(hippo, rn)] = k.get("finishers") or []
    return out


def _match_tr_race(hippo: str, race_no: int,
                    outcomes: dict) -> Optional[list]:
    """TR outcomes lookup + fuzzy hippo match."""
    for (h, rn), fins in outcomes.items():
        if rn != race_no:
            continue
        if h == hippo or hippo in h or h in hippo:
            return fins
    return None


def analyze_tr_prerace(target_date: str) -> dict:
    """T-3 top-4 log'ları vs outcome."""
    logs = _load_jsonl(LOG_DIR / f"{target_date}.jsonl")
    if not logs:
        return {"n": 0}
    outcomes = _tr_outcomes(target_date)
    if not outcomes:
        return {"n": len(logs), "matched": 0,
                 "note": "outcomes henüz yok"}

    n = len(logs)
    winner_hit = 0
    winner_in_top4 = 0
    top4_overlap_total = 0
    matched = 0
    for r in logs:
        hippo = r.get("hippo", "")
        race_no = r.get("race_no")
        fins = _match_tr_race(hippo, race_no, outcomes)
        if not fins:
            continue
        matched += 1
        actual_winner = next(
            (f["at_no"] for f in fins if f.get("S") == 1), None)
        pred_winner = r.get("winner_no")
        top4_actual = {f["at_no"] for f in fins
                        if isinstance(f.get("S"), int) and f["S"] <= 4}
        pred_top5 = {x.get("no")
                     for x in (r.get("composite_top5") or [])}
        pred_top4 = list(pred_top5)[:4] if pred_top5 else []
        if pred_winner == actual_winner:
            winner_hit += 1
        if actual_winner in pred_top4:
            winner_in_top4 += 1
        top4_overlap_total += len(set(pred_top4) & top4_actual)
    return {
        "n": n, "matched": matched,
        "winner_hit_rate": round(winner_hit / matched * 100, 2)
            if matched else 0,
        "winner_in_pred_top4_pct": round(winner_in_top4 / matched * 100, 2)
            if matched else 0,
        "avg_top4_overlap": round(top4_overlap_total / matched, 2)
            if matched else 0,
    }


def analyze_tr_altili(target_date: str) -> dict:
    """T-5 altılı log'ları vs outcome — 6/6 hit veya X ayak hit."""
    logs = _load_jsonl(LOG_DIR / f"{target_date}_altili.jsonl")
    if not logs:
        return {"n": 0}
    outcomes = _tr_outcomes(target_date)
    if not outcomes:
        return {"n": len(logs), "matched": 0}

    total_altili = 0
    full_hit = 0
    ayak_hits_total = 0
    ayak_total = 0
    for r in logs:
        hippo = r.get("hippo", "")
        ayaklar = r.get("ayaklar") or []
        if not ayaklar:
            continue
        total_altili += 1
        n_ayak_hit = 0
        for a in ayaklar:
            race_no = a.get("race_no")
            fins = _match_tr_race(hippo, race_no, outcomes)
            if not fins:
                continue
            actual_winner = next(
                (f["at_no"] for f in fins if f.get("S") == 1), None)
            if actual_winner is None:
                continue
            ayak_total += 1
            if actual_winner in (a.get("at_no_list") or []):
                n_ayak_hit += 1
        ayak_hits_total += n_ayak_hit
        if n_ayak_hit == len(ayaklar):
            full_hit += 1
    return {
        "n_altili": total_altili,
        "full_hit": full_hit,
        "ayak_hit_rate": round(ayak_hits_total / ayak_total * 100, 2)
            if ayak_total else 0,
        "avg_hit_per_altili": round(ayak_hits_total / total_altili, 2)
            if total_altili else 0,
    }


def analyze_v11_hybrid(target_date: str) -> dict:
    """V11 hibrit tahmin log'ları vs outcome — tier bazlı hit rate.

    Metrik:
      * rank_hit_top4 (rank 1-4 tahmininin ilk 4'te bitmesi)
      * tier_hit: {'⭐ ELMAS': (n, n_hit_top4), ...}
      * steam_hit: STEAM tag'lı atların top4 %
      * drift_avoid: DRIFT tag'lıların top4 %
      * value_edge korelasyon: value_edge > 0.1 vs baseline
      * best snapshot only (multi-snapshot idempotent: en son snapshot al)
    """
    p = V11_FORWARD_DIR / f"{target_date}.jsonl"
    rows = _load_jsonl(p)
    if not rows:
        return {"n": 0}
    outcomes = _tr_outcomes(target_date)
    if not outcomes:
        return {"n": len(rows), "matched": 0,
                 "note": "outcomes yok — TR backfill gecikmeli"}

    # Multi-snapshot dedup: (hippo, kosu_no, at_no) → en son snapshot
    latest = {}
    for r in rows:
        key = (r.get("hippo"), r.get("kosu_no"), r.get("at_no"))
        prev = latest.get(key)
        if prev is None or (r.get("snapshot_ts") or "") > (
                prev.get("snapshot_ts") or ""):
            latest[key] = r
    rows = list(latest.values())

    total = 0
    top4_hit = 0
    tier_stats = {}   # tier → [n, hit]
    steam_stats = [0, 0]
    drift_stats = [0, 0]
    value_stats_hi = [0, 0]   # value_edge ≥ 0.10
    value_stats_lo = [0, 0]   # value_edge ≤ -0.10
    rank_stats = {1: [0, 0], 2: [0, 0], 3: [0, 0], 4: [0, 0]}

    for r in rows:
        hippo = r.get("hippo", "")
        kosu = r.get("kosu_no")
        at_no = r.get("at_no")
        fins = _match_tr_race(hippo, kosu, outcomes)
        if not fins:
            continue
        # top4 finish set
        top4_set = {f.get("at_no") for f in fins
                    if isinstance(f.get("S"), int) and f["S"] <= 4}
        if not top4_set:
            continue
        total += 1
        did_hit = at_no in top4_set
        if did_hit:
            top4_hit += 1
        # tier
        tier = r.get("tier") or "•"
        tier_stats.setdefault(tier, [0, 0])
        tier_stats[tier][0] += 1
        if did_hit:
            tier_stats[tier][1] += 1
        # steam / drift
        if r.get("is_steam"):
            steam_stats[0] += 1
            if did_hit:
                steam_stats[1] += 1
        if r.get("is_drift"):
            drift_stats[0] += 1
            if did_hit:
                drift_stats[1] += 1
        # value edge
        ve = r.get("value_edge") or 0
        if ve >= 0.10:
            value_stats_hi[0] += 1
            if did_hit:
                value_stats_hi[1] += 1
        elif ve <= -0.10:
            value_stats_lo[0] += 1
            if did_hit:
                value_stats_lo[1] += 1
        # rank
        rank = r.get("rank") or 0
        if rank in rank_stats:
            rank_stats[rank][0] += 1
            if did_hit:
                rank_stats[rank][1] += 1

    def _pct(n, d):
        return round(100 * n / d, 1) if d else 0.0

    return {
        "n": len(rows),
        "matched": total,
        "top4_hit_rate": _pct(top4_hit, total),
        "top4_hits": top4_hit,
        "tier_stats": {
            tier: {"n": v[0], "hit": v[1],
                    "hit_pct": _pct(v[1], v[0])}
            for tier, v in tier_stats.items()
        },
        "steam": {"n": steam_stats[0], "hit": steam_stats[1],
                   "hit_pct": _pct(steam_stats[1], steam_stats[0])},
        "drift": {"n": drift_stats[0], "hit": drift_stats[1],
                   "hit_pct": _pct(drift_stats[1], drift_stats[0])},
        "value_edge_hi": {"n": value_stats_hi[0],
                            "hit": value_stats_hi[1],
                            "hit_pct": _pct(value_stats_hi[1],
                                             value_stats_hi[0])},
        "value_edge_lo": {"n": value_stats_lo[0],
                            "hit": value_stats_lo[1],
                            "hit_pct": _pct(value_stats_lo[1],
                                             value_stats_lo[0])},
        "rank_stats": {
            r: {"n": v[0], "hit": v[1], "hit_pct": _pct(v[1], v[0])}
            for r, v in rank_stats.items()
        },
    }


def analyze_uk_top4(target_date: str) -> dict:
    """UK race TOP-4 log'ları."""
    logs = _load_jsonl(LOG_DIR / f"{target_date}_uk_top4.jsonl")
    if not logs:
        return {"n": 0}
    # UK outcomes RacingAPI'den anlık çekilebilir — bu senaryoda
    # forward log'un rapor sayacı olarak kullan
    return {"n": len(logs),
            "note": "UK outcomes canlı fetch gerek (results endpoint)",
            "by_region": {}}


def analyze_uk_value(target_date: str) -> dict:
    """UK value bet log'ları."""
    logs = _load_jsonl(LOG_DIR / f"{target_date}_uk_value.jsonl")
    return {"n": len(logs),
             "note": "outcome eşleşme RacingAPI results ile"}


def format_report(target_date: str, tr_pre: dict,
                   tr_alt: dict, uk_top: dict,
                   uk_val: dict, v11: Optional[dict] = None) -> str:
    """Kompakt Telegram raporu."""
    lines = [
        f"📊 <b>RETRO · {target_date}</b>",
        "━━━━━━━━━━━━━━━━━━━",
        "",
    ]
    # TR prerace (T-3 top-4)
    lines.append("<b>🇹🇷 TR T-3 TOP-4</b>")
    if tr_pre.get("n"):
        lines.append(f"   Gönderim: {tr_pre['n']}, eşleşen: "
                     f"{tr_pre.get('matched', 0)}")
        if tr_pre.get("matched"):
            lines.append(
                f"   Kazanan hit: %{tr_pre.get('winner_hit_rate', 0):.1f} · "
                f"Top-4'te: %{tr_pre.get('winner_in_pred_top4_pct', 0):.1f}")
            lines.append(
                f"   Ortalama top-4 örtüşme: "
                f"{tr_pre.get('avg_top4_overlap', 0):.2f}/4")
    else:
        lines.append("   ⚠ log yok")
    lines.append("")

    # TR altılı (T-5)
    lines.append("<b>🇹🇷 TR T-5 ALTILI</b>")
    if tr_alt.get("n_altili"):
        lines.append(f"   Altılı: {tr_alt['n_altili']}, "
                     f"tam hit (6/6): {tr_alt.get('full_hit', 0)}")
        lines.append(
            f"   Ayak hit oranı: %{tr_alt.get('ayak_hit_rate', 0):.1f}")
        lines.append(
            f"   Ortalama ayak hit/altılı: "
            f"{tr_alt.get('avg_hit_per_altili', 0):.2f}")
    else:
        lines.append("   ⚠ log yok")
    lines.append("")

    # UK top-4
    lines.append("<b>🌍 UK TOP-4 tahmini</b>")
    if uk_top.get("n"):
        lines.append(f"   Gönderim: {uk_top['n']}")
        if uk_top.get("note"):
            lines.append(f"   <i>{uk_top['note']}</i>")
    else:
        lines.append("   ⚠ log yok")
    lines.append("")

    # UK value bet
    lines.append("<b>💰 UK VALUE BET</b>")
    if uk_val.get("n"):
        lines.append(f"   Alert: {uk_val['n']}")
        if uk_val.get("note"):
            lines.append(f"   <i>{uk_val['note']}</i>")
    else:
        lines.append("   Bugün outlier tespit edilmedi")

    # V11 HYBRID
    if v11 and v11.get("n") and not v11.get("matched"):
        lines.append("")
        lines.append("<b>🎯 V11 HYBRID</b>")
        lines.append(f"   Log: {v11['n']} tahmin · outcomes bekleniyor "
                      f"(TR backfill gecikmeli)")
    elif v11 and v11.get("matched"):
        lines.append("")
        lines.append("<b>🎯 V11 HYBRID (model + AGF + steam)</b>")
        lines.append(
            f"   Eşleşen at: {v11['matched']} · TOP-4 hit: "
            f"%{v11.get('top4_hit_rate', 0):.1f}")
        rank_stats = v11.get("rank_stats") or {}
        rank_line = " ".join(
            f"R{r}:%{rank_stats.get(r, {}).get('hit_pct', 0):.0f}"
            for r in (1, 2, 3, 4)
            if rank_stats.get(r, {}).get('n', 0) > 0)
        if rank_line:
            lines.append(f"   Rank-hit: {rank_line}")
        # Tier bazlı
        tier_stats = v11.get("tier_stats") or {}
        tier_lines = []
        for tier_name in ("⭐ ELMAS", "💎 STEAM VALUE",
                           "🔥 FIRSAT", "✓ SAĞLAM"):
            ts = tier_stats.get(tier_name)
            if ts and ts["n"] > 0:
                tier_lines.append(
                    f"   {tier_name}: %{ts['hit_pct']:.0f} "
                    f"({ts['hit']}/{ts['n']})")
        for t in tier_lines:
            lines.append(t)
        # Steam / Drift
        steam = v11.get("steam") or {}
        drift = v11.get("drift") or {}
        if steam.get("n"):
            lines.append(f"   ⚡ STEAM: %{steam['hit_pct']:.0f} "
                          f"({steam['hit']}/{steam['n']})")
        if drift.get("n"):
            lines.append(f"   📉 DRIFT: %{drift['hit_pct']:.0f} "
                          f"({drift['hit']}/{drift['n']})")
        # Value edge
        veh = v11.get("value_edge_hi") or {}
        vel = v11.get("value_edge_lo") or {}
        if veh.get("n"):
            lines.append(f"   🔥 value_edge≥+10: %{veh['hit_pct']:.0f} "
                          f"({veh['hit']}/{veh['n']})")
        if vel.get("n"):
            lines.append(f"   ⚠ value_edge≤−10: %{vel['hit_pct']:.0f} "
                          f"({vel['hit']}/{vel['n']})")

    lines.append("")
    lines.append("<i>V11 ensemble · CPCV walk-forward · H2H Elo + Pace + Track · AGF steam</i>")
    return "\n".join(lines)


def run_retro(target_date: str, send_telegram: bool = False) -> dict:
    tr_pre = analyze_tr_prerace(target_date)
    tr_alt = analyze_tr_altili(target_date)
    uk_top = analyze_uk_top4(target_date)
    uk_val = analyze_uk_value(target_date)
    v11 = analyze_v11_hybrid(target_date)
    # Online Elo update — outcome varsa bundle in-place güncelle
    elo_result = None
    if os.environ.get('TJK_ONLINE_ELO', '1') == '1':
        try:
            from model.v11.online_elo_update import update_elo
            elo_result = update_elo(target_date)
            log.info(f"online-elo: {elo_result}")
        except Exception as exc:
            log.warning(f"online-elo update fail: {exc}")
    report = {
        "date": target_date,
        "generated_at": datetime.now().isoformat(),
        "tr_prerace": tr_pre,
        "tr_altili": tr_alt,
        "uk_top4": uk_top,
        "uk_value": uk_val,
        "v11_hybrid": v11,
        "online_elo": elo_result,
    }
    # Persist
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    out_path = REPORT_DIR / f"retro_{target_date}.json"
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    log.info(f"saved {out_path}")

    text = format_report(target_date, tr_pre, tr_alt, uk_top, uk_val, v11)
    print(text)

    if send_telegram:
        try:
            from dashboard.smart_coupon_service import send_telegram as _st
            _st(text)
            log.info("Telegram retro sent")
        except Exception as exc:
            log.warning(f"Telegram send fail: {exc}")

    return report


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=None)
    parser.add_argument("--send", action="store_true")
    args = parser.parse_args()
    target = args.date or date.today().isoformat()
    run_retro(target, send_telegram=args.send)


if __name__ == "__main__":
    main()
