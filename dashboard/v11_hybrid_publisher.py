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

import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

log = logging.getLogger("v11_hybrid_publisher")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

FORWARD_LOG_DIR = ROOT / "data" / "v11_forward_log"


def _write_forward_log(date_str: str, hippo: str,
                        hippo_races_scored: list) -> None:
    """Her koşu için TOP-4 predictions → JSONL append.

    File: data/v11_forward_log/{date}.jsonl (append idempotent)
    Row schema:
      date, hippo, kosu_no, distance, start_time,
      rank (1..4), at_no, name, v11_p_top4, agf_pct,
      agf_delta_pp, hybrid_score, tier, is_steam, is_drift,
      value_edge, snapshot_ts
    """
    FORWARD_LOG_DIR.mkdir(parents=True, exist_ok=True)
    fp = FORWARD_LOG_DIR / f"{date_str}.jsonl"
    ts = datetime.utcnow().isoformat()
    rows = []
    for race in hippo_races_scored:
        kosu = race.get("kosu_no")
        dist = race.get("distance")
        start = race.get("start_time")
        for rank, s in enumerate(race.get("scored", [])[:4], 1):
            rows.append({
                "date": date_str, "hippo": hippo,
                "kosu_no": kosu, "distance": dist,
                "start_time": start,
                "rank": rank,
                "at_no": s.get("at_no"),
                "name": s.get("name"),
                "v11_p_top4": s.get("v11_p_top4"),
                "agf_pct": s.get("agf_pct"),
                "agf_delta_pp": s.get("agf_delta_pp"),
                "hybrid_score": s.get("hybrid_score"),
                "value_edge": s.get("value_edge"),
                "tier": s.get("tier"),
                "is_steam": s.get("is_steam"),
                "is_drift": s.get("is_drift"),
                "snapshot_ts": ts,
            })
    with open(fp, "a", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def _extract_v11_p4(horse: dict) -> float:
    """V11 model prob 0..1.

    PROD ÖNCELİK: yerli_engine model_prob (at bazlı gerçek değer).
    V11 direct predict prod'da history_map boş (backfill data yok) →
    uniform değer veriyor. yerli_engine V6/V7 shadow model_prob gerçek.
    """
    v = horse.get("model_prob")
    if v is not None:
        try:
            return float(v) / 100.0
        except Exception:
            pass
    for k in ("v11_p_top4", "p_top4", "raw_p_top4", "model_p_top4"):
        val = horse.get(k)
        if val is not None:
            try:
                return float(val)
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
    # Prod (Railway): cwd=dashboard, sys.path=dashboard/ → 'yerli_engine'
    # Lokal (-m dashboard.v11_hybrid_publisher): sys.path=root → 'dashboard.yerli_engine'
    try:
        from yerli_engine import run_yerli_pipeline
    except ImportError:
        from dashboard.yerli_engine import run_yerli_pipeline
    from forecast.v11_hybrid_scorer import (
        score_race, format_race_top4, format_hippo_altili,
        format_altili_v11)
    from forecast.agf_intraday import (
        snapshot_agf, detect_steam_moves,
    )
    from forecast.jockey_recent_form import (
        build_jockey_form_map, get_hot_tag)
    from model.v9.inference_v9 import predict_race_v9
    from model.v8.train_real import _build_history_map, _load_all_outcomes

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

    # Jockey recent form (son 30 gün)
    jockey_form = {}
    try:
        jockey_form = build_jockey_form_map(
            days_back=30, end_date=target_date.isoformat())
    except Exception as exc:
        log.warning(f"[v11-hybrid] jockey form fail: {exc}")

    # V11 direct inference için history map (cache once)
    v11_history_map = {}
    try:
        _records = _load_all_outcomes()
        v11_history_map = _build_history_map(_records)
        log.info(f"[v11-hybrid] history_map: {len(v11_history_map)} at")
    except Exception as exc:
        log.warning(f"[v11-hybrid] history_map fail: {exc}")

    def _v11_lookup(name):
        return v11_history_map.get(name, [])

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
            # V11 direct predict — env flag ile aç (prod'da history_map boş
            # olduğu için uniform değer veriyor; yerli_engine model_prob
            # kullanılıyor default).
            v11_by_at = {}
            if os.environ.get("TJK_V11_DIRECT_PREDICT", "0") == "1":
                try:
                    v11_input = []
                    for h in horses:
                        v11_input.append({
                            "horse_no": h.get("number") or h.get("at_no"),
                            "horse_name": (h.get("name")
                                            or h.get("horse_name")),
                            "age": h.get("age"),
                            "weight": h.get("weight"),
                            "jockey_name": (h.get("jockey_name")
                                             or h.get("jockey")),
                            "sire": h.get("sire"),
                            "distance": distance, "track_type": "Çim",
                            "hippodrome": hippo_name,
                        })
                    preds = predict_race_v9(
                        v11_input, history_lookup=_v11_lookup,
                        ref_date=date_str)
                    if preds:
                        for p in preds:
                            v11_by_at[p.get("horse_no")] = p
                except Exception as _e_v11:
                    log.debug(f"[v11-hybrid] v11 direct fail K{kosu_no}: "
                               f"{_e_v11}")

            scored_inputs = []
            for h in horses:
                at_no = h.get("number") or h.get("at_no")
                # V11 direct p_top4 > model_prob (top-1) > 0
                v11_direct = v11_by_at.get(at_no) or {}
                v11_p4 = v11_direct.get("p_top4")
                if v11_p4 is None:
                    v11_p4 = _extract_v11_p4(h)
                agf = _extract_agf(h)
                delta_pp = 0.0
                key_try = f"{ayak}_{at_no}"
                comp = steam_by_key.get(key_try)
                if comp:
                    delta_pp = comp.get("delta_pp", 0.0)
                jockey_name = (h.get("jockey_name") or h.get("jockey")
                                or "")
                jockey_tag = get_hot_tag(jockey_name, jockey_form)
                scored_inputs.append({
                    "at_no": at_no,
                    "name": h.get("name") or h.get("horse_name"),
                    "v11_p_top4": v11_p4,
                    "agf_pct": agf,
                    "agf_delta_pp": delta_pp,
                    "jockey_name": jockey_name,
                    "jockey_tag": jockey_tag,
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
            # ALTILI format default (koşu tipine göre adaptive at seçimi
            # + kombo hesap). Top-4 format env flag ile.
            if os.environ.get("TJK_V11_FORMAT", "altili") == "top4":
                text = format_hippo_altili(
                    hippo_name, hippo_races_scored, k=4)
            else:
                text = format_altili_v11(hippo_name, hippo_races_scored)
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
            # Forward log — her koşu × top-4 at → JSONL
            try:
                _write_forward_log(date_str, hippo_name, hippo_races_scored)
            except Exception as exc:
                log.warning(f"[v11-hybrid] forward log fail: {exc}")

    return {
        "status": "ok",
        "date": date_str,
        "n_messages": len(messages),
        "counts": counts,
        "messages": messages,
    }


def publish(target_date, do_send: bool = False) -> dict:
    """Rapor + Telegram gönder (opsiyonel)."""
    try:
        from smart_coupon_service import send_telegram
    except ImportError:
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
