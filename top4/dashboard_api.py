"""Dashboard view-model builder for BERKAY DENEME.

Aggregates shadow coupons + SİB picks + retro state into a single
JSON-safe payload that the HTML page can render. Pure read; no
side effects. NEVER raises.

Exports:
  - build_today_view(date_str=None) -> dict
  - build_history_view(days=14) -> dict
  - refresh_sib_today(date_str=None) -> dict
"""
from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from typing import Optional

from . import sib_log
from .experimental_logger import (
    read_predictions, read_results, _summary_path_for as _shadow_sum_path,
)

logger = logging.getLogger(__name__)

# Cache for "live" SiB fetch — picks are expensive (~30s).
_SIB_LIVE_CACHE: dict = {}  # date_str -> (timestamp, payload)
_SIB_CACHE_TTL = 600  # 10 minutes
_SIB_CACHE_LOCK = threading.Lock()


def refresh_sib_today(date_str: Optional[str] = None,
                      force: bool = False) -> dict:
    """Live-fetch today's SiB picks (DIAMOND/ALTIN/PREMIUM/FIRSAT) and
    persist them via sib_log. Useful when scheduler hasn't run yet
    today or when env was added after morning emit (picks lost).

    Cached for 10 minutes per date. Returns counts + status.

    NEVER raises.
    """
    date_str = date_str or _today_str()
    try:
        with _SIB_CACHE_LOCK:
            cached = _SIB_LIVE_CACHE.get(date_str)
        if cached and not force and (time.time() - cached[0]) < _SIB_CACHE_TTL:
            return {
                "status": "cached", "date": date_str,
                "totals": cached[1].get("totals") or {},
            }
        # Live fetch from sib_top4_service. This is the SAME source the
        # morning scheduler uses; we just call it on-demand.
        try:
            from datetime import date as _date
            try:
                target = _date.fromisoformat(date_str)
            except ValueError:
                target = _date.today()
            try:
                from dashboard.sib_top4_service import collect_today_picks
            except ImportError:
                from sib_top4_service import collect_today_picks  # type: ignore
            payload = collect_today_picks(target)
            if not payload:
                return {"status": "empty", "date": date_str, "totals": {}}
            # Persist to log (idempotent).
            try:
                sib_log.log_sib_picks(payload, telegram_sent=False, force=True)
            except Exception as exc:
                logger.warning("refresh_sib_today log: %s", exc)
            with _SIB_CACHE_LOCK:
                _SIB_LIVE_CACHE[date_str] = (time.time(), payload)
            return {
                "status": "fresh",
                "date": date_str,
                "totals": payload.get("totals") or {},
                "diamond": len(payload.get("diamond") or []),
                "altin": len(payload.get("altin") or []),
                "premium": len(payload.get("premium") or []),
                "firsat": len(payload.get("firsat") or []),
            }
        except Exception as exc:
            logger.warning("refresh_sib_today fetch: %s", exc)
            return {"status": "error", "date": date_str,
                    "reason": repr(exc)[:200]}
    except Exception as exc:
        return {"status": "error", "date": date_str,
                "reason": repr(exc)[:200]}


def telegram_messages_for_today() -> list[dict]:
    """Return the Telegram message dump for today (from yerli kupon
    cache + smart_coupon all). Each entry: {category, title, text}.

    'Berkay's Telegram'da ne varsa is te' request: dashboard shows
    everything that gets sent to Telegram so detail-seekers don't
    need to scroll Telegram.
    """
    out: list[dict] = []
    # 1) V5.1 yerli kupon mesajları (cache'ten)
    try:
        try:
            from dashboard.app import _yerli_cache, _yerli_lock
        except Exception:
            return out
        with _yerli_lock:
            data = (_yerli_cache.get("data") or {}) if _yerli_cache else {}
        if data:
            for hp in (data.get("hippodromes") or []):
                # Each hippodrome has its own Telegram message under
                # 'telegram_msg' or similar key. The smart_coupon
                # service stores it as 'text'. We fall back gracefully.
                txt = (hp.get("telegram_msg") or hp.get("text")
                       or hp.get("kupon_text") or "")
                if not txt:
                    continue
                out.append({
                    "category": "V5.1 KUPON",
                    "title": (hp.get("hippodrome") or "?")
                             + (" · " + str(hp.get("altili_no")) + ". altılı"
                                if hp.get("altili_no") else ""),
                    "text": txt,
                })
            # Top-level daily digest if present
            if data.get("telegram_msg"):
                out.append({
                    "category": "GÜNLÜK",
                    "title": "Günlük TJK özeti",
                    "text": data["telegram_msg"],
                })
    except Exception as exc:
        logger.debug("telegram messages: %s", exc)
    return out


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _load_json(path: str) -> Optional[dict]:
    if not os.path.exists(path):
        return None
    try:
        import json
        with open(path, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None


def _shadow_pick_outcome(pred: dict,
                         res_by_pid: dict,
                         res_by_race: dict) -> dict:
    """For one shadow prediction row, compute simple outcome flags."""
    pid = pred.get("prediction_id")
    rid = pred.get("race_id")
    res = res_by_pid.get(pid) if pid else None
    if not res and rid:
        res = res_by_race.get(rid)
    if not res:
        return {"status": "pending"}
    top4 = set(res.get("top4_actual") or [])
    bankers = set(pred.get("bankers") or [])
    candidate = set(pred.get("candidate_set") or [])
    return {
        "status": "graded",
        "winner": (res.get("finish_order") or [None])[0],
        "top4_actual": list(top4),
        "banker_survived": bool(bankers and bankers.issubset(top4)),
        "candidate_hit": bool(candidate) and top4.issubset(candidate),
        "small_hit": bool(res.get("small_ticket_hit")),
        "balanced_hit": bool(res.get("balanced_ticket_hit")),
        "wide_hit": bool(res.get("wide_ticket_hit")),
    }


def _safe_int(v, default=0):
    try:
        return int(v)
    except (TypeError, ValueError):
        return default


def _extract_unified_picks(shadow_rows: list, sib_rows: list) -> list[dict]:
    """Flatten shadow + SiB picks into ONE actionable list.

    Each pick: {kind, hippo, race_no, race_time, horse_no, horse_name,
    agf, mp, reason, outcome, source}.

    kind ordering:
      banker  (⭐ shadow BANKER or SiB DIAMOND)
      value   (💎 shadow DEĞER-tagged or SiB ALTIN/PREMIUM)
      chaos   (🎲 shadow CHAOS or SiB FIRSAT)
      avoid   (⚠ shadow AVOID — public trap)
      no_bet  (🛑 entire race skipped)
    """
    picks: list[dict] = []
    # --- shadow rows -------------------------------------------------------
    for r in shadow_rows or []:
        hippo = r.get("hippodrome") or "?"
        race_label = r.get("race_label") or ""
        # extract race number from label "X 3. koşu" or race_id "X_3"
        race_no = None
        rid = (r.get("race_id") or "")
        for token in (rid.split("_") + race_label.split()):
            if token.isdigit():
                race_no = int(token)
                break
        race_time = r.get("race_time") or ""
        outcome = r.get("outcome") or {}
        mode = (r.get("recommended_mode") or "").upper()
        confidence = r.get("confidence") or ""

        # If race is NO_BET, single "skip" row
        if mode == "NO_BET":
            picks.append({
                "kind": "no_bet",
                "hippo": hippo, "race_no": race_no, "race_time": race_time,
                "horse_no": None, "horse_name": None,
                "agf": None, "mp": None,
                "reason": "Yarış pas — " + (confidence.lower() or "kaotik"),
                "outcome": {"status": "pending"},
                "source": "shadow",
            })
            continue

        # Walk horse-level role tags
        for h in (r.get("horses") or []):
            role = (h.get("role") or "").upper()
            value_tag = h.get("value_tag")
            value_gap = h.get("value_gap_pct")
            agf = h.get("agf_now")
            mp = h.get("mp")
            hno = h.get("horse_no")
            hname = h.get("horse_name") or "?"
            # outcome marker per horse (best-effort from race-level outcome)
            won = None
            if outcome.get("status") == "graded":
                top4 = set(outcome.get("top4_actual") or [])
                won = hno in top4 if top4 else None

            base = {
                "hippo": hippo, "race_no": race_no, "race_time": race_time,
                "horse_no": hno, "horse_name": hname,
                "agf": agf, "mp": mp,
                "outcome": {"status": "graded" if won is not None else "pending",
                            "won": won,
                            "winner_horse_no": outcome.get("winner")},
                "source": "shadow",
            }
            if role == "BANKER":
                base["kind"] = "banker"
                base["reason"] = "Model+halk uyumlu (pTop4 {:.2f})".format(
                    h.get("p_top4_cal") or 0)
                picks.append(base)
            elif value_tag == "DEĞER":
                base["kind"] = "value"
                base["reason"] = (f"Model halktan güçlü "
                                  f"(+{value_gap:.0f}pp)" if value_gap
                                  else "Model halktan güçlü")
                picks.append(base)
            elif role == "AVOID":
                base["kind"] = "avoid"
                base["reason"] = f"AGF yüksek (%{agf:.0f}) ama model zayıf" \
                                 if agf is not None else "Halk tuzağı"
                picks.append(base)
            elif role == "CHAOS":
                base["kind"] = "chaos"
                base["reason"] = "Longshot — model sinyali var"
                picks.append(base)

    # --- SiB rows ----------------------------------------------------------
    for r in sib_rows or []:
        tier = (r.get("tier") or "").upper()
        kind = ("banker" if tier == "DIAMOND"
                else "value" if tier in ("ALTIN", "PREMIUM")
                else "chaos" if tier == "FIRSAT" else "value")
        outcome = r.get("outcome") or {}
        won = outcome.get("won")
        picks.append({
            "kind": kind,
            "tier": tier,
            "hippo": r.get("hippo") or "?",
            "race_no": _safe_int(r.get("race_no")),
            "race_time": r.get("race_time") or "",
            "horse_no": _safe_int(r.get("horse_no")),
            "horse_name": r.get("horse_name") or "?",
            "agf": r.get("agf"),
            "mp": r.get("mp"),
            "reason": (f"SİB {tier}" if tier else "SİB pick")
                      + (f" · jokey {r.get('jockey_name')}"
                         if r.get("jockey_name") else ""),
            "outcome": {
                "status": "graded" if won is not None else "pending",
                "won": won,
                "winner_horse_no": outcome.get("winner_horse_no"),
            },
            "source": "sib",
        })

    # Sort: kind priority, then time, then hippo
    kind_pri = {"banker": 0, "value": 1, "chaos": 2, "avoid": 3, "no_bet": 4}
    picks.sort(key=lambda p: (
        kind_pri.get(p.get("kind"), 9),
        str(p.get("race_time") or ""),
        str(p.get("hippo") or ""),
        p.get("race_no") or 99,
    ))
    return picks


def _build_races_view(shadow_rows: list, sib_rows: list) -> list[dict]:
    """YARIŞ-BAZLI görünüm — her yarış için 1 satır.

    Berkay: "ayni ati birkac defa yazmis, hala anlamiyorum bunlar
    ilk4 mu". Çözüm: yarış-bazlı, ne oynayacağı net.

    Her satır:
      {hippo, race_no, race_time, field_size, mode, confidence,
       headline (kısa öneri),
       main_picks (1-3 banker/değer at),
       other_picks (avoid/chaos),
       outcome (winner + bizden kim girdi)}
    """
    # SiB picks'i (hippo, race_no) anahtarıyla grupla
    sib_by_race: dict[tuple, list] = {}
    for s in sib_rows or []:
        key = (s.get("hippo") or "?", _safe_int(s.get("race_no")))
        sib_by_race.setdefault(key, []).append(s)

    out: list[dict] = []
    for r in shadow_rows or []:
        hippo = r.get("hippodrome") or "?"
        race_label = r.get("race_label") or ""
        race_id = r.get("race_id") or ""
        race_no = None
        for token in (race_id.split("_") + race_label.split()):
            if token.isdigit():
                race_no = int(token)
                break
        race_time = r.get("race_time") or ""
        field_size = r.get("field_size") or 0
        mode = (r.get("recommended_mode") or "").upper()
        confidence = r.get("confidence") or ""
        outcome = r.get("outcome") or {}
        top4 = set(outcome.get("top4_actual") or [])
        winner = outcome.get("winner")
        status = outcome.get("status") or "pending"

        # Horse-level roller
        main_picks: list[dict] = []
        other_picks: list[dict] = []
        for h in (r.get("horses") or []):
            role = (h.get("role") or "").upper()
            value_tag = h.get("value_tag")
            value_gap = h.get("value_gap_pct")
            hno = h.get("horse_no")
            hname = h.get("horse_name") or "?"
            agf = h.get("agf_now")
            mp = h.get("mp")
            won = (hno in top4) if (status == "graded" and top4) else None

            item = {
                "horse_no": hno, "horse_name": hname,
                "agf": agf, "mp": mp,
                "won": won, "is_winner": (hno == winner),
            }
            if role == "BANKER":
                item["kind"] = "banker"
                item["label"] = "⭐ Ana At"
                item["detail"] = f"pTop4 {h.get('p_top4_cal'):.2f}" \
                                 if h.get('p_top4_cal') else ""
                main_picks.append(item)
            elif value_tag == "DEĞER":
                item["kind"] = "value"
                item["label"] = "💎 Değer"
                item["detail"] = f"+{value_gap:.0f}pp" if value_gap else ""
                main_picks.append(item)
            elif role == "AVOID":
                item["kind"] = "avoid"
                item["label"] = "⚠ Tuzak"
                item["detail"] = "halk yüksek model düşük"
                other_picks.append(item)
            elif role == "CHAOS":
                item["kind"] = "chaos"
                item["label"] = "🎲 Longshot"
                item["detail"] = ""
                other_picks.append(item)

        # SiB picks for this race
        sib_picks_here = sib_by_race.pop((hippo, race_no), [])
        for s in sib_picks_here:
            tier = (s.get("tier") or "").upper()
            kind = ("banker" if tier == "DIAMOND" else "value")
            item = {
                "horse_no": s.get("horse_no"),
                "horse_name": s.get("horse_name") or "?",
                "agf": s.get("agf"),
                "mp": s.get("mp"),
                "kind": kind,
                "tier": tier,
                "label": f"SİB {tier}",
                "detail": s.get("jockey_name") or "",
                "won": (s.get("outcome") or {}).get("won"),
                "is_winner": s.get("horse_no") == winner,
            }
            # SiB always to main (high signal)
            main_picks.append(item)

        # Headline — net açıklama
        if mode == "NO_BET":
            headline = "🛑 PAS — " + (confidence.lower() or "kaotik")
            our_winners: list[int] = []
        else:
            our_winners = [p["horse_no"] for p in main_picks
                           if p.get("won") is True]
            n_b = sum(1 for p in main_picks if p.get("kind") == "banker")
            n_v = sum(1 for p in main_picks if p.get("kind") == "value")
            parts = []
            if n_b:
                parts.append(f"⭐ {n_b} ana")
            if n_v:
                parts.append(f"💎 {n_v} değer")
            if not parts:
                parts.append("genel öneri")
            headline = " · ".join(parts)
            if confidence:
                headline += f" ({confidence.lower()} güven)"

        out.append({
            "hippo": hippo,
            "race_no": race_no,
            "race_time": race_time,
            "field_size": field_size,
            "mode": mode,
            "confidence": confidence,
            "headline": headline,
            "main_picks": main_picks[:6],   # too long otherwise
            "other_picks": other_picks[:4],
            "outcome": {
                "status": status,
                "winner_horse_no": winner,
                "top4_actual": list(top4),
                "our_winners": our_winners,
            },
        })

    # Orphan SiB races (we have SiB picks but no shadow row for that race)
    for (hippo, race_no), sib_picks in sib_by_race.items():
        if not sib_picks:
            continue
        time_v = (sib_picks[0].get("race_time") or "")
        main = []
        for s in sib_picks:
            tier = (s.get("tier") or "").upper()
            kind = "banker" if tier == "DIAMOND" else "value"
            main.append({
                "horse_no": s.get("horse_no"),
                "horse_name": s.get("horse_name") or "?",
                "agf": s.get("agf"), "mp": s.get("mp"),
                "kind": kind, "tier": tier,
                "label": f"SİB {tier}",
                "detail": s.get("jockey_name") or "",
                "won": (s.get("outcome") or {}).get("won"),
            })
        out.append({
            "hippo": hippo, "race_no": race_no, "race_time": time_v,
            "field_size": 0, "mode": "SIB_ONLY", "confidence": "",
            "headline": f"SİB {len(main)} pick",
            "main_picks": main, "other_picks": [],
            "outcome": {"status": "pending"},
        })

    # Sort by hippo then race_no
    out.sort(key=lambda r: (r.get("hippo") or "",
                            r.get("race_no") or 99))
    return out


def _build_top_picks(races: list, k: int = 5) -> list[dict]:
    """Bugünün EN GÜÇLÜ K önerisi (banker + değer).

    Berkay: "BUGÜN EN GÜÇLÜ 5" tarzı sade liste — tablo yok.
    Skor: banker hep önde, sonra değer (gap pp), tie-break = AGF.
    """
    cands: list[dict] = []
    for race in races or []:
        for p in (race.get("main_picks") or []):
            kind = p.get("kind")
            if kind not in ("banker", "value"):
                continue
            # Skor: banker bonus + p_top4/gap
            score = 0.0
            if kind == "banker":
                score = 1000.0
                # Higher mp = stronger banker
                score += float(p.get("mp") or 0) * 100
            elif kind == "value":
                score = 500.0
                # Parse gap from detail (e.g. "+22pp")
                detail = str(p.get("detail") or "")
                if "pp" in detail:
                    try:
                        n = float("".join(c for c in detail
                                          if c.isdigit() or c == "."))
                        score += n
                    except ValueError:
                        pass
            # AGF for tie-break
            score += float(p.get("agf") or 0) * 0.1

            cands.append({
                "kind": kind,
                "horse_no": p.get("horse_no"),
                "horse_name": p.get("horse_name"),
                "hippo": race.get("hippo"),
                "race_no": race.get("race_no"),
                "race_time": race.get("race_time"),
                "field_size": race.get("field_size"),
                "agf": p.get("agf"),
                "mp": p.get("mp"),
                "label": p.get("label"),
                "detail": p.get("detail"),
                "won": p.get("won"),
                "tier": p.get("tier"),
                "score": score,
            })
    cands.sort(key=lambda c: c["score"], reverse=True)
    # FIX (2026-06-26): dedupe by (horse_no, race_time, hippo-prefix).
    # Same horse appears multiple times when hippodrome has multiple
    # altili pools (e.g. "Kocaeli · 1. Altılı" and "Kocaeli · 2. Altılı"
    # both contain the same race). Keep first occurrence (highest score).
    seen: set[tuple] = set()
    deduped: list[dict] = []
    for c in cands:
        hippo_prefix = (str(c.get("hippo") or "").split("·")[0].strip())
        key = (c.get("horse_no"), c.get("race_time"), hippo_prefix)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(c)
    out = deduped[:k]
    for i, c in enumerate(out, start=1):
        c["rank"] = i
    return out


def _build_top_traps(races: list, k: int = 3) -> list[dict]:
    """KAÇINILAN K tuzak — halk yüksek tutmuş ama model zayıf."""
    cands: list[dict] = []
    for race in races or []:
        for p in (race.get("other_picks") or []):
            if p.get("kind") != "avoid":
                continue
            cands.append({
                "horse_no": p.get("horse_no"),
                "horse_name": p.get("horse_name"),
                "hippo": race.get("hippo"),
                "race_no": race.get("race_no"),
                "race_time": race.get("race_time"),
                "agf": p.get("agf"),
                "mp": p.get("mp"),
                "won": p.get("won"),
                "agf_score": float(p.get("agf") or 0),
            })
    # En yüksek AGF + en düşük model = ilk önce
    cands.sort(key=lambda c: c["agf_score"], reverse=True)
    out = cands[:k]
    for i, c in enumerate(out, start=1):
        c["rank"] = i
    return out


def _build_daily_stats(shadow_rows: list, sib_rows: list,
                      unified: list) -> dict:
    """4 big numbers for the header."""
    n_races = len(shadow_rows or [])
    n_picks = sum(1 for p in unified if p.get("kind") != "no_bet")
    n_results = sum(1 for r in shadow_rows or []
                    if (r.get("outcome") or {}).get("status") == "graded")
    n_no_bet = sum(1 for p in unified if p.get("kind") == "no_bet")
    n_banker = sum(1 for p in unified if p.get("kind") == "banker")
    n_value = sum(1 for p in unified if p.get("kind") == "value")
    n_chaos = sum(1 for p in unified if p.get("kind") == "chaos")
    n_avoid = sum(1 for p in unified if p.get("kind") == "avoid")
    n_sib = sum(1 for p in unified if p.get("source") == "sib")

    # Today's hit/loss tally
    won = sum(1 for p in unified
              if (p.get("outcome") or {}).get("won") is True)
    lost = sum(1 for p in unified
               if (p.get("outcome") or {}).get("won") is False)
    pending = sum(1 for p in unified
                  if (p.get("outcome") or {}).get("status") != "graded"
                  and p.get("kind") != "no_bet")

    return {
        "races": n_races,
        "picks": n_picks,
        "results_graded": n_results,
        "no_bet": n_no_bet,
        "banker_count": n_banker,
        "value_count": n_value,
        "chaos_count": n_chaos,
        "avoid_count": n_avoid,
        "sib_count": n_sib,
        "won": won,
        "lost": lost,
        "pending": pending,
    }


def build_today_view(date_str: Optional[str] = None) -> dict:
    """One-page view-model for `/api/berkay_deneme/today`."""
    date_str = date_str or _today_str()
    try:
        preds = read_predictions(date_str)
    except Exception as exc:
        logger.debug("read_predictions: %s", exc)
        preds = []
    try:
        results = read_results(date_str)
    except Exception as exc:
        logger.debug("read_results: %s", exc)
        results = []
    res_by_pid = {r.get("prediction_id"): r for r in results
                  if r.get("prediction_id")}
    res_by_race = {r.get("race_id"): r for r in results
                   if r.get("race_id")}

    shadow_rows: list[dict] = []
    for p in preds:
        outcome = _shadow_pick_outcome(p, res_by_pid, res_by_race)
        shadow_rows.append({
            "race_id": p.get("race_id"),
            "race_label": p.get("race_label"),
            "race_time": p.get("race_time"),
            "hippodrome": p.get("hippodrome"),
            "field_size": p.get("field_size"),
            "confidence": p.get("confidence"),
            "recommended_mode": p.get("recommended_mode"),
            "bankers": p.get("bankers") or [],
            "candidate_set": p.get("candidate_set") or [],
            "engine_status": p.get("engine_status"),
            "telegram_sent": p.get("telegram_sent"),
            "outcome": outcome,
            # rich horse list — keep just the role-tagged horses + names
            "horses": [
                {
                    "horse_no": h.get("horse_no"),
                    "horse_name": h.get("horse_name"),
                    "role": h.get("role"),
                    "p_top4_cal": h.get("p_top4_cal"),
                    "mp": h.get("mp"),
                    "agf_now": h.get("agf_now"),
                    "value_tag": h.get("value_tag"),
                    "value_gap_pct": h.get("value_gap_pct"),
                }
                for h in (p.get("horses") or [])
            ],
        })

    # SİB picks + results
    try:
        sib_picks = sib_log.read_picks(date_str)
        sib_results = sib_log.read_results(date_str)
    except Exception as exc:
        logger.debug("sib_log read: %s", exc)
        sib_picks, sib_results = [], []

    # NOTE (2026-06-24): live SiB fallback was removed from the
    # default GET path — it took 30+ seconds per render and locked
    # the page on "Yükleniyor…". User must now press the "↻ SİB
    # picks'i yeniden çek" button which calls /refresh_sib explicitly.
    sib_res_by_key = {r.get("pick_key"): r for r in sib_results
                      if r.get("pick_key")}
    sib_rows: list[dict] = []
    for p in sib_picks:
        res = sib_res_by_key.get(p.get("pick_key"))
        sib_rows.append({
            "tier": p.get("tier"),
            "hippo": p.get("hippo"),
            "race_no": p.get("race_no"),
            "race_time": p.get("race_time"),
            "horse_no": p.get("horse_no"),
            "horse_name": p.get("horse_name"),
            "agf": p.get("agf"),
            "mp": p.get("mp"),
            "mult": p.get("mult"),
            "field_size": p.get("field_size"),
            "jockey_name": p.get("jockey_name"),
            "outcome": {
                "status": "graded" if res else "pending",
                "won": (res.get("won") if res else None),
                "winner_horse_no": (res.get("winner_horse_no")
                                    if res else None),
                "in_top4": (res.get("in_top4") if res else None),
            },
        })
    # Sort SiB rows by tier priority then time
    _tier_pri = {"DIAMOND": 0, "ALTIN": 1, "PREMIUM": 2, "FIRSAT": 3}
    sib_rows.sort(key=lambda r: (
        _tier_pri.get((r.get("tier") or "").upper(), 9),
        str(r.get("race_time") or ""),
    ))

    # Daily summary (shadow)
    shadow_summary = _load_json(_shadow_sum_path(date_str)) or {}
    sib_summary = sib_log.load_summary(date_str) or {}

    # Telegram messages dump (for today only — uses live cache)
    tg_msgs: list[dict] = []
    if date_str == _today_str():
        try:
            tg_msgs = telegram_messages_for_today()
        except Exception as exc:
            logger.debug("telegram messages: %s", exc)

    # Unified picks (banker + value + chaos + avoid + no_bet) ONE list
    unified = _extract_unified_picks(shadow_rows, sib_rows)
    daily = _build_daily_stats(shadow_rows, sib_rows, unified)
    # Race-by-race view — 1 row per race (Berkay-native)
    races = _build_races_view(shadow_rows, sib_rows)
    # Top 5 + Top 3 traps — Berkay's "BUGÜN EN GÜÇLÜ 5" preference
    top_picks = _build_top_picks(races, k=5)
    top_traps = _build_top_traps(races, k=3)

    return {
        "date": date_str,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "stats": daily,
        "top_picks": top_picks,
        "top_traps": top_traps,
        "races": races,
        "picks": unified,
        "shadow": {
            "rows": shadow_rows,
            "count": len(shadow_rows),
            "summary": shadow_summary,
        },
        "sib": {
            "rows": sib_rows,
            "count": len(sib_rows),
            "summary": sib_summary,
        },
        "telegram_messages": tg_msgs,
        "disclaimer": (
            "Deneme / shadow kuponudur. Resmi bot kuponu değildir. "
            "Otomatik bahis değildir."
        ),
    }


def build_history_view(days: int = 14) -> dict:
    """Last N days of summary stats. Used by the history table."""
    days = max(1, min(int(days or 14), 60))
    today = datetime.now(timezone.utc).date()
    rows: list[dict] = []
    for i in range(days):
        d = (today - timedelta(days=i)).strftime("%Y-%m-%d")
        sh = _load_json(_shadow_sum_path(d)) or {}
        si = sib_log.load_summary(d) or {}
        if not sh and not si:
            continue
        rows.append({
            "date": d,
            "shadow": {
                "predictions": sh.get("predictions", 0),
                "results": sh.get("results", 0),
                "banker_survived": sh.get("banker_survived_count", 0),
                "candidate_hit": sh.get("candidate_set_full_top4_capture", 0),
                "small_hit": sh.get("small_ticket_hit_count", 0),
                "balanced_hit": sh.get("balanced_ticket_hit_count", 0),
                "wide_hit": sh.get("wide_ticket_hit_count", 0),
                "no_bet": sh.get("no_bet_count", 0),
            },
            "sib": {
                "picks": si.get("picks_total", 0),
                "results": si.get("results_total", 0),
                "win_rate_by_tier": si.get("win_rate_by_tier") or {},
                "by_tier_total": si.get("by_tier_total") or {},
                "by_tier_won": si.get("by_tier_won") or {},
            },
        })
    rows.sort(key=lambda r: r["date"], reverse=True)
    return {
        "days_requested": days,
        "days_present": len(rows),
        "rows": rows,
    }
