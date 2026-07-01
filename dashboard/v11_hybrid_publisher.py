"""V11 hibrit publisher — model (V11) + AGF public + AGF steam.

Berkay (2026-07-01): 'v11 tahminleri bugün gelmeli agfli hibrit,
agf değişimlerinin etkisini de koyarak'.

Pipeline:
  1. yerli_engine → günün tüm hipodrom + koşulari (V11 chain'de p_top4)
  2. AGF snapshot mevcut mu — yoksa şimdi bir snapshot al (steam için gerek)
  3. Her at için hibrit skor (V11 p_top4 + AGF% + AGF Δ)
  4. Koşu bazında TOP-4 mesaj → Telegram

Manuel tetik:
    python -m dashboard.v11_hybrid_publisher 2026-07-01 --send

Scheduler otomatik: coupon_scheduler _maybe_send_v11_hybrid_daily hook.
"""
from __future__ import annotations

import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("v11_hybrid_publisher")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))


def _extract_v11_p4(horse: dict) -> float:
    """V11 model prob 0..1. yerli_engine 'model_prob' % scale."""
    for k in ("v11_p_top4", "p_top4", "raw_p_top4", "model_p_top4"):
        v = horse.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    # yerli_engine model_prob = % (0..100)
    v = horse.get("model_prob")
    if v is not None:
        try:
            return float(v) / 100.0
        except Exception:
            pass
    return 0.0


def _extract_agf(horse: dict) -> float:
    """AGF % (0..100)."""
    for k in ("agf_pct", "agf", "agf_public", "agf_percentage"):
        v = horse.get(k)
        if v is not None:
            try:
                return float(v)
            except Exception:
                pass
    return 0.0


def build_hybrid_report(target_date, ensure_snapshot: bool = True) -> dict:
    """Günün tüm koşuları → hibrit rapor + Telegram mesajları listesi."""
    from dashboard.yerli_engine import run_yerli_pipeline
    from forecast.v11_hybrid_scorer import (
        score_race, format_race_top4, format_hippo_altili)
    from forecast.agf_intraday import (
        snapshot_agf, detect_steam_moves,
    )

    if isinstance(target_date, str):
        target_date = date.fromisoformat(target_date)

    log.info(f"[v11-hybrid] pipeline run {target_date}...")
    payload = run_yerli_pipeline(target_date) or {}
    hipodromes = payload.get("hippodromes") or []
    if not hipodromes:
        return {"status": "no_data", "date": target_date.isoformat()}

    # AGF snapshot — şu an bir tane al ki Δ hesabı olabilsin
    snap_meta = {}
    if ensure_snapshot:
        try:
            snap_meta = snapshot_agf(datetime.now())
            log.info(f"[v11-hybrid] agf snapshot: {snap_meta.get('hhmm')} "
                     f"n_hippos={snap_meta.get('n_hippos')}")
        except Exception as exc:
            log.warning(f"[v11-hybrid] snapshot fail: {exc}")

    date_str = target_date.isoformat()
    messages = []
    counts = {"races": 0, "steam": 0, "drift": 0, "elmas": 0,
              "firsat": 0, "steam_value": 0}

    for hip in hipodromes:
        hippo_name = hip.get("hippodrome") or ""
        hippo_races_scored = []
        # Steam moves for this hippo
        try:
            steam_data = detect_steam_moves(date_str, hippo_name)
            steam_by_key = {c["key"]: c
                             for c in (steam_data.get("comparisons") or [])}
        except Exception:
            steam_by_key = {}

        legs = hip.get("legs_summary") or []

        for leg in legs:
            kosu_no = leg.get("race_number") or leg.get("ayak")
            ayak = leg.get("ayak") or kosu_no
            distance = leg.get("distance") or ""
            start = leg.get("race_time") or ""
            horses = leg.get("all_horses_with_mp") or []
            if not horses:
                continue
            scored_inputs = []
            for h in horses:
                at_no = h.get("number") or h.get("at_no")
                v11_p4 = _extract_v11_p4(h)
                agf = _extract_agf(h)
                # Steam Δ lookup via ayak_no + at_no
                delta_pp = 0.0
                key_try = f"{ayak}_{at_no}"
                comp = steam_by_key.get(key_try)
                if comp:
                    delta_pp = comp.get("delta_pp", 0.0)
                scored_inputs.append({
                    "at_no": at_no,
                    "name": h.get("name") or h.get("horse_name"),
                    "v11_p_top4": v11_p4,
                    "agf_pct": agf,
                    "agf_delta_pp": delta_pp,
                })
            scored = score_race(scored_inputs, field_size=len(horses))
            counts["races"] += 1
            for s in scored:
                if s.get("is_steam"):
                    counts["steam"] += 1
                if s.get("is_drift"):
                    counts["drift"] += 1
                if s.get("tier", "").startswith("⭐"):
                    counts["elmas"] += 1
                elif s.get("tier", "").startswith("🔥"):
                    counts["firsat"] += 1
                elif s.get("tier", "").startswith("💎"):
                    counts["steam_value"] += 1

            hippo_races_scored.append({
                "kosu_no": kosu_no, "distance": distance,
                "start_time": start, "scored": scored,
                "n_horses": len(horses),
            })

        # Bir hippodrome bittiğinde: TEK mesaj (6 koşu birleşik)
        if hippo_races_scored:
            text = format_hippo_altili(hippo_name, hippo_races_scored, k=4)
            first_start = min(
                (r.get("start_time") or "99:99"
                 for r in hippo_races_scored),
                default="99:99")
            messages.append({
                "hippo": hippo_name,
                "kosu_no": "ALL",
                "start": first_start,
                "text": text,
                "n_races": len(hippo_races_scored),
                "races": hippo_races_scored,
            })

    return {
        "status": "ok",
        "date": date_str,
        "n_messages": len(messages),
        "counts": counts,
        "messages": messages,
    }


def publish(target_date, do_send: bool = False) -> dict:
    """Rapor + Telegram gönder (opsiyonel)."""
    from dashboard.smart_coupon_service import send_telegram

    report = build_hybrid_report(target_date)
    if report.get("status") != "ok":
        return report

    sent = []
    if do_send:
        # Sırala: start_time ascending
        msgs = sorted(report["messages"],
                       key=lambda m: (m.get("start") or "99:99"))
        for m in msgs:
            r = send_telegram(m["text"])
            sent.append({"hippo": m["hippo"], "kosu": m["kosu_no"],
                          "result": r})
    report["sent"] = sent
    return report


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO,
                        format="%(asctime)s [%(levelname)s] %(message)s")
    target = (date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1
              and not sys.argv[1].startswith("--")
              else date.today())
    do_send = "--send" in sys.argv
    print(f"V11 HYBRID PUBLISHER  {target}  send={do_send}", flush=True)
    r = publish(target, do_send=do_send)
    print(f"status: {r.get('status')}")
    print(f"messages: {r.get('n_messages')}")
    print(f"counts: {r.get('counts')}")
    if r.get("messages"):
        print("\n=== SAMPLE MESSAGE ===")
        print(r["messages"][0]["text"])
        print("=" * 40)
    if do_send:
        print(f"\nsent: {len(r.get('sent') or [])}")
        for s in (r.get("sent") or [])[:5]:
            print(f"  {s['hippo']} K{s['kosu']}: {s['result']}")
