"""Integration glue for the BERKAY BİLİMSEL DENEME TOP4 layer.

This module is the **safe call site**. Callers in production should
import functions from here and never reach into the per-module
internals — that lets us evolve the engine without touching prod paths.

Public API:
  - `extract_race_snapshots(results_dict)` — turn a yerli_engine
    `results_dict` into a list of normalized race snapshots.
  - `build_shadow_coupons(results_dict, cutoff='latest')` — wraps the
    builder; honors `TJK_TOP4_BERKAY_SHADOW`; logs if forward-log flag.
  - `maybe_append_telegram(existing_messages, results_dict, cutoff='latest')`
    — never raises; returns the existing list unchanged when flags are
    off or anything fails.
  - `record_results_for_date(date_str, race_results)` — called from
    retro flow to write result rows + rebuild summary.

Everything here is defensive: a thrown exception is caught and a
console warning is printed. Production behavior is unchanged when
flags are off.
"""
from __future__ import annotations

import logging
import os
from typing import Iterable, Mapping, Optional

from .experimental_coupon import (
    build_berkay_scientific_top4_coupon,
    is_forward_log_enabled,
    is_shadow_enabled,
    is_telegram_enabled,
)
from .experimental_logger import log_prediction, log_result, rebuild_summary
from .experimental_telegram import safe_render, safe_render_chunked

logger = logging.getLogger(__name__)


def _safe_horse_no(val) -> int:
    try:
        return int(val)
    except (TypeError, ValueError):
        return 0


def _build_agf_snapshots(horses: list[dict],
                         open_ts: Optional[str] = None,
                         now_ts: Optional[str] = None) -> Optional[dict]:
    """Construct AGF snapshots from per-horse inline fields.

    Returns None when no timestamps are known — the builder then falls
    back to the inline path which does NOT mark AGF as stale. Pass real
    `open_ts` / `now_ts` only when the caller actually has them (e.g.
    from agf_live_scanner). For the prod integration in
    `maybe_append_telegram` we have horses but not timestamps, so we
    return None and the builder uses inline fallback.
    """
    if open_ts is None and now_ts is None:
        return None
    open_map: dict[int, float] = {}
    now_map: dict[int, float] = {}
    for h in horses:
        hn = _safe_horse_no(h.get("horse_no"))
        if hn <= 0:
            continue
        o = h.get("agf_open") or h.get("agf_morning")
        n = h.get("agf") or h.get("agf_now") or h.get("agf_value")
        try:
            if o is not None:
                open_map[hn] = float(o)
        except (TypeError, ValueError):
            pass
        try:
            if n is not None:
                now_map[hn] = float(n)
        except (TypeError, ValueError):
            pass
    return {
        "open": {"ts": open_ts, "horses": open_map} if open_map else None,
        "now": {"ts": now_ts, "horses": now_map} if now_map else None,
    }


def extract_race_snapshots(results_dict: Mapping) -> list[dict]:
    """Normalize whatever shape the yerli_engine results carry into a
    list of race snapshots compatible with the experimental builder.

    Accepted shapes (best-effort):
      - results_dict['hippodromes'] -> list of dicts with 'tracks' or
        'altili' or 'legs' or direct 'horses'
      - results_dict['races'] -> direct race list

    Always returns a list (possibly empty). Never raises.
    """
    out: list[dict] = []
    try:
        hippos = results_dict.get("hippodromes") or []
        for hp in hippos:
            hippo_name = (hp.get("hippodrome") or hp.get("name")
                          or hp.get("track") or "")
            altililer = (hp.get("altili") or hp.get("legs")
                         or hp.get("races") or [])
            for race in altililer:
                horses = (race.get("horses") or race.get("at_list") or [])
                if not horses:
                    continue
                normalized = []
                for h in horses:
                    normalized.append({
                        "horse_no": h.get("horse_no") or h.get("no")
                                    or h.get("horse_number"),
                        "horse_name": h.get("horse_name") or h.get("name") or "?",
                        "mp": h.get("mp") or h.get("model_prob") or 0.0,
                        "agf": h.get("agf") or h.get("agf_now") or h.get("pct"),
                        "agf_open": h.get("agf_open") or h.get("agf_morning"),
                        "tier": h.get("tier") or "",
                        "breed": h.get("breed") or race.get("breed") or "",
                    })
                out.append({
                    "race_label": (race.get("race_label")
                                   or f"{hippo_name} {race.get('race_no')}"),
                    "race_id": (str(race.get("race_id"))
                                if race.get("race_id") is not None
                                else f"{hippo_name}_{race.get('race_no')}"),
                    "race_time": (race.get("time") or race.get("race_time")
                                  or race.get("first_time") or ""),
                    "hippodrome": hippo_name,
                    "race_class": race.get("race_class") or "",
                    "horses": normalized,
                })
        # Fallback to flat 'races'
        if not out and results_dict.get("races"):
            for race in results_dict["races"]:
                if race.get("horses"):
                    out.append(race)
    except Exception as exc:
        logger.debug("extract_race_snapshots: %s", exc)
    return out


def build_shadow_coupons(
    results_dict: Mapping,
    cutoff: str = "latest",
) -> list[dict]:
    """Build all experimental coupons for a results_dict. Honors
    `TJK_TOP4_BERKAY_SHADOW`. Returns [] when the flag is off.

    Also writes JSONL forward rows if `TJK_TOP4_FORWARD_LOG=1`.
    """
    if not is_shadow_enabled():
        return []
    snapshots = extract_race_snapshots(results_dict)
    out: list[dict] = []
    for snap in snapshots:
        try:
            agf = _build_agf_snapshots(snap.get("horses") or [])
            coupon = build_berkay_scientific_top4_coupon(
                snap, agf_snapshot=agf, cutoff=cutoff,
            )
            out.append(coupon)
            if is_forward_log_enabled():
                log_prediction(coupon)
        except Exception as exc:
            logger.warning("shadow coupon build failed for %s: %s",
                           snap.get("race_label"), exc)
            continue
    return out


def extract_race_snapshots_from_pool(pool: Mapping) -> list[dict]:
    """Adapter for the smart_coupon_service pool shape used by
    coupon_scheduler.morning_job. Each pool carries `race_legs` — a
    list of legs, each leg a list of horse dicts (`horse_number`,
    `horse_name`, `agf_value`, `model_prob` in 0..1, `tier_mark`,
    `breed`, `race_number`, `start_time`).
    """
    out: list[dict] = []
    try:
        hippo = pool.get("hippo") or pool.get("hippodrome") or "?"
        legs = pool.get("race_legs") or []
        for leg in legs:
            if not leg:
                continue
            head = leg[0] or {}
            race_no = head.get("race_number")
            race_time = str(head.get("start_time") or "")[:5]
            horses = []
            for h in leg:
                horses.append({
                    "horse_no": h.get("horse_number") or h.get("number"),
                    "horse_name": h.get("horse_name") or h.get("name") or "?",
                    "mp": h.get("model_prob") or 0.0,
                    "agf": h.get("agf_value"),
                    "tier": h.get("tier_mark") or "",
                    "breed": h.get("breed") or "",
                })
            out.append({
                "race_label": f"{hippo} {race_no}. koşu",
                "race_id": f"{hippo}_{race_no}",
                "race_time": race_time,
                "hippodrome": hippo,
                "horses": horses,
            })
    except Exception as exc:
        logger.debug("extract_race_snapshots_from_pool: %s", exc)
    return out


def build_shadow_coupons_from_pools(
    pools: Iterable[Mapping], cutoff: str = "latest",
) -> dict[str, list[dict]]:
    """Build shadow coupons grouped by hippodrome. Returns
    `{hippo_name: [coupon, ...], ...}`. Honors `TJK_TOP4_BERKAY_SHADOW`.
    """
    if not is_shadow_enabled():
        return {}
    out: dict[str, list[dict]] = {}
    for pool in pools:
        try:
            snaps = extract_race_snapshots_from_pool(pool)
            if not snaps:
                continue
            hippo = pool.get("hippo") or pool.get("hippodrome") or "?"
            coupons: list[dict] = []
            for snap in snaps:
                agf = _build_agf_snapshots(snap.get("horses") or [])
                coupon = build_berkay_scientific_top4_coupon(
                    snap, agf_snapshot=agf, cutoff=cutoff,
                )
                coupons.append(coupon)
                if is_forward_log_enabled():
                    log_prediction(coupon)
            if coupons:
                out[hippo] = coupons
        except Exception as exc:
            logger.warning("shadow pool build failed for %s: %s",
                           pool.get("hippo"), exc)
            continue
    return out


def render_pool_shadow_messages(pools: Iterable[Mapping],
                                cutoff: str = "latest",
                                max_chars: int = 3500) -> list[str]:
    """Telegram-safe messages, chunked. Returns one or more strings per
    hippodrome (each under `max_chars`). Empty list if shadow flag is
    off or nothing renders.
    """
    try:
        coupons_by_hippo = build_shadow_coupons_from_pools(pools, cutoff=cutoff)
        out: list[str] = []
        for hippo, coupons in coupons_by_hippo.items():
            chunks = safe_render_chunked(coupons, max_chars=max_chars)
            for c in chunks:
                if c:
                    out.append(c)
        return out
    except Exception as exc:
        logger.warning("render_pool_shadow_messages failed: %s", exc)
        return []


def maybe_append_telegram(
    existing_messages: list[str],
    results_dict: Mapping,
    cutoff: str = "latest",
) -> list[str]:
    """Return `existing_messages` plus an experimental block if flags
    are on AND the rendered block is non-empty. NEVER raises and NEVER
    mutates `existing_messages`.

    Safe to call unconditionally from production paths.
    """
    if not is_telegram_enabled() or not is_shadow_enabled():
        return list(existing_messages)
    try:
        coupons = build_shadow_coupons(results_dict, cutoff=cutoff)
        if not coupons:
            return list(existing_messages)
        block = safe_render(coupons)
        if not block:
            return list(existing_messages)
        return list(existing_messages) + [block]
    except Exception as exc:
        logger.warning("maybe_append_telegram failed: %s", exc)
        return list(existing_messages)


def record_results_for_date(
    date_str: str, race_results: Iterable[Mapping],
) -> Optional[str]:
    """Walk a list of race results and write retro rows. Each race
    result must include `race_id` and `finish_order`. Returns the
    summary path on success.
    """
    if not is_forward_log_enabled():
        return None
    try:
        for r in race_results:
            log_result(
                race_id=str(r.get("race_id") or ""),
                race_label=r.get("race_label"),
                finish_order=r.get("finish_order") or [],
                payouts=r.get("payouts") or {},
                notes=r.get("notes") or [],
                force=True,
            )
        return rebuild_summary(date_str)
    except Exception as exc:
        logger.warning("record_results_for_date failed: %s", exc)
        return None
