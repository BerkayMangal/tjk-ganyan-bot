"""V8 daily batch — günün TÜM yarışları için forward forecast.

Berkay (2026-06-27): "modelimiz artik bu oluyor gazi halic takilma her kosu icin
olayimiz artik bu". V8 her gün her koşuya uygulanır, sonuç:
  1) JSON snapshot → data/v8_daily/<date>.json
  2) Telegram digest (top picks per race, p_top4 sorted)

History source önceliği:
  Taydex DB → TJK derece + finish_estimator (forecast_api._fetch_history zaten bunu yapıyor)

V7 production akışı DEĞİŞMEZ — bu shadow/yan çıktı. Berkay karar verir.

Usage:
    python -m dashboard.v8_daily            # bugün
    python -m dashboard.v8_daily 2026-06-28 # belirli tarih
    python -m dashboard.v8_daily --send     # bugün + Telegram'a gönder
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date as _date_type, date
from pathlib import Path
from typing import Optional

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "dashboard"))

logger = logging.getLogger(__name__)
OUT_DIR = ROOT / "data" / "v8_daily"


def _coerce_date(d) -> _date_type:
    if isinstance(d, _date_type):
        return d
    if isinstance(d, str):
        return _date_type.fromisoformat(d)
    return _date_type.today()


def _load_history(horse_name: str) -> list:
    """Aynı priority chain'i kullan (Taydex → derece+estimator)."""
    try:
        from dashboard.forecast_api import _fetch_history
        return _fetch_history(horse_name)
    except Exception:
        try:
            from forecast.sources.taydex_form import (
                fetch_horse_form, is_available,
            )
            if is_available():
                return fetch_horse_form(horse_name) or []
        except Exception:
            pass
        return []


def _load_glicko_ledger():
    try:
        from forecast.glicko import GlickoLedger
        path = ROOT / "model" / "v8" / "glicko_ledger.json"
        if path.exists():
            with open(path) as f:
                return GlickoLedger.from_json(json.load(f))
        return GlickoLedger()
    except Exception as exc:
        logger.debug(f"glicko ledger load: {exc}")
        return None


def _predict_race(race_horses: list, ref_date: str, ledger) -> list:
    """V8 inference → at başına {horse_no, horse_name, p_top1..4, ...}."""
    try:
        from model.v8.inference import predict_race
        return predict_race(
            horses=race_horses,
            history_lookup=_load_history,
            glicko_ledger=ledger,
            ref_date=ref_date,
        )
    except Exception as exc:
        logger.warning(f"v8 predict_race fail: {exc}")
        return []


def run_daily(target: _date_type) -> dict:
    """Günün tüm hipodromlarını V8'den geçir."""
    target = _coerce_date(target)
    try:
        from dashboard.smart_coupon_service import build_all_hippos
    except Exception:
        from smart_coupon_service import build_all_hippos

    pools = build_all_hippos(target) or []
    ledger = _load_glicko_ledger()
    out = {
        "date": str(target),
        "generated_at": __import__("datetime").datetime.now().isoformat(),
        "pools": [],
    }
    n_horses_total = 0
    n_races_total = 0
    for pool in pools:
        if pool.get("status") != "ok":
            continue
        hippo = pool.get("hippo", "?")
        legs = pool.get("race_legs") or []
        races_out = []
        for leg in legs:
            if not leg:
                continue
            race_no = leg[0].get("race_number") or 0
            preds = _predict_race(leg, str(target), ledger)
            if not preds:
                continue
            # sort by p_top4 desc
            preds.sort(key=lambda p: -(p.get("p_top4") or 0))
            races_out.append({
                "race_no": race_no,
                "n_horses": len(preds),
                "predictions": preds,
            })
            n_horses_total += len(preds)
            n_races_total += 1
        if races_out:
            out["pools"].append({"hippo": hippo, "races": races_out})

    out["summary"] = {
        "n_pools": len(out["pools"]),
        "n_races": n_races_total,
        "n_horses": n_horses_total,
    }
    return out


def _format_horse_pick(p: dict, idx: int) -> str:
    """At satırı format."""
    no = p.get("horse_no") or "?"
    name = p.get("horse_name") or "?"
    p4 = p.get("p_top4")
    p1 = p.get("p_top1")
    p4_str = f"{p4 * 100:.1f}%" if isinstance(p4, (int, float)) else "—"
    p1_str = f"{p1 * 100:.1f}%" if isinstance(p1, (int, float)) else "—"
    return f"  {idx}) #{no} {name}  T4 {p4_str}  T1 {p1_str}"


def format_telegram_digest(result: dict, top_n: int = 4) -> str:
    """Günün V8 digest mesajı (Telegram).

    Her yarış için top-N tahmin, p_top4 sorted.
    """
    lines = []
    date_str = result.get("date")
    summ = result.get("summary") or {}
    lines.append(f"🤖 <b>V8 GÜNLÜK FORECAST · {date_str}</b>")
    lines.append(
        f"   {summ.get('n_pools', 0)} hipodrom · "
        f"{summ.get('n_races', 0)} yarış · "
        f"{summ.get('n_horses', 0)} at"
    )
    lines.append("")
    for pool in result.get("pools") or []:
        hippo = pool.get("hippo", "?")
        lines.append(f"━━━ <b>{hippo}</b> ━━━")
        for race in pool.get("races") or []:
            rn = race.get("race_no")
            preds = race.get("predictions") or []
            if not preds:
                continue
            lines.append(f"<b>{rn}. KOŞU</b>  ({len(preds)} at)")
            for idx, p in enumerate(preds[:top_n], 1):
                lines.append(_format_horse_pick(p, idx))
            lines.append("")
    lines.append("⚠ Karar destek aracı — V7 production AYNEN devam ediyor.")
    return "\n".join(lines)


def persist(result: dict) -> Path:
    """JSON snapshot kaydet."""
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    date_str = result.get("date")
    path = OUT_DIR / f"{date_str}.json"
    with open(path, "w") as f:
        json.dump(result, f, ensure_ascii=False, indent=2, default=str)
    return path


def send_to_telegram(text: str, dry_run: bool = False) -> dict:
    try:
        from dashboard.smart_coupon_service import send_telegram
    except Exception:
        from smart_coupon_service import send_telegram
    return send_telegram(text, dry_run=dry_run)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("date", nargs="?", default=None)
    parser.add_argument("--send", action="store_true",
                        help="Telegram'a gönder")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--top", type=int, default=4)
    parser.add_argument("--no-persist", action="store_true")
    args = parser.parse_args()

    target = _coerce_date(args.date) if args.date else _date_type.today()
    print(f"V8 daily run: {target}", flush=True)
    result = run_daily(target)
    summ = result["summary"]
    print(f"  pools: {summ['n_pools']} · races: {summ['n_races']}"
          f" · horses: {summ['n_horses']}")

    if not args.no_persist:
        path = persist(result)
        print(f"  → {path}")

    digest = format_telegram_digest(result, top_n=args.top)
    print(f"  digest len: {len(digest)} char")

    if args.send:
        res = send_to_telegram(digest, dry_run=args.dry_run)
        print(f"  Telegram: {res}")
    else:
        print("\n=== DIGEST PREVIEW ===")
        print(digest[:2500])


if __name__ == "__main__":
    main()
