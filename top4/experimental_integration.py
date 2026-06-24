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
from .experimental_telegram import safe_render

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

    Accepted shapes (best-effort, all fields tried in priority order):
      - results_dict['hippodromes'] -> list of dicts with one of:
        * `legs_summary` (REAL yerli_engine shape — each leg has
          `all_horses_with_mp` with keys {number, name, agf_pct,
          model_prob})
        * `altili` / `legs` / `races` with `horses` / `at_list`
      - results_dict['races'] -> direct race list

    Horse field aliases tried in priority:
      horse_no   ← horse_no | no | horse_number | number
      horse_name ← horse_name | name
      mp         ← mp | model_prob (and rescaled from 0..100 if needed)
      agf        ← agf | agf_now | agf_value | agf_pct | pct

    Always returns a list (possibly empty). Never raises.
    """
    out: list[dict] = []
    try:
        hippos = results_dict.get("hippodromes") or []
        for hp in hippos:
            hippo_name = (hp.get("hippodrome") or hp.get("name")
                          or hp.get("track") or "")
            altili_no = hp.get("altili_no") or 1
            # 1) yerli_engine REAL shape: legs_summary
            # 2) fallback: altili / legs / races
            altililer = (hp.get("legs_summary") or hp.get("altili")
                         or hp.get("legs") or hp.get("races") or [])
            for race in altililer:
                horses = (race.get("all_horses_with_mp")
                          or race.get("horses")
                          or race.get("at_list") or [])
                if not horses:
                    continue
                normalized = []
                # detect whether model_prob is already 0..1 or 0..100
                _mp_vals = [h.get("model_prob") for h in horses
                            if h.get("model_prob") is not None]
                _mp_max = max(_mp_vals) if _mp_vals else 0
                _mp_scale = 0.01 if _mp_max > 1.5 else 1.0
                for h in horses:
                    mp_raw = (h.get("mp")
                              if h.get("mp") is not None
                              else h.get("model_prob"))
                    if mp_raw is not None:
                        try:
                            mp_v = float(mp_raw) * _mp_scale
                        except (TypeError, ValueError):
                            mp_v = 0.0
                    else:
                        mp_v = 0.0
                    normalized.append({
                        "horse_no": (h.get("horse_no") or h.get("no")
                                     or h.get("horse_number")
                                     or h.get("number")),
                        "horse_name": (h.get("horse_name") or h.get("name")
                                       or "?"),
                        "mp": mp_v,
                        "agf": (h.get("agf") if h.get("agf") is not None
                                else h.get("agf_now") if h.get("agf_now") is not None
                                else h.get("agf_value") if h.get("agf_value") is not None
                                else h.get("agf_pct") if h.get("agf_pct") is not None
                                else h.get("pct")),
                        "agf_open": h.get("agf_open") or h.get("agf_morning"),
                        "tier": (h.get("tier") or h.get("tier_mark") or ""),
                        "breed": h.get("breed") or race.get("breed") or "",
                    })
                race_no = (race.get("race_number") or race.get("race_no")
                           or race.get("ayak"))
                out.append({
                    "race_label": (race.get("race_label")
                                   or f"{hippo_name} {race_no}. koşu"),
                    "race_id": (str(race.get("race_id"))
                                if race.get("race_id") is not None
                                else f"{hippo_name}_{race_no}"),
                    "race_time": (race.get("time") or race.get("race_time")
                                  or race.get("first_time")
                                  or race.get("start_time") or ""),
                    "hippodrome": hippo_name,
                    "altili_no": altili_no,
                    "race_class": (race.get("race_class")
                                   or race.get("group_name") or ""),
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
    log_with_send_status: Optional[bool] = None,
) -> dict[str, list[dict]]:
    """Build shadow coupons grouped by hippodrome. Returns
    `{hippo_name: [coupon, ...], ...}`. Honors `TJK_TOP4_BERKAY_SHADOW`.

    `log_with_send_status`:
      - None  -> if forward log enabled, write with telegram_sent=None
                  (status unknown — caller may not send Telegram).
      - True/False -> write with that telegram_sent value.

    For the hardened scheduler path, the caller passes None here and
    later writes log rows AFTER send via `log_predictions_for_chunk`.
    To preserve backwards behavior, the default still writes a row
    with telegram_sent=None when the forward log flag is on.
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
                    # Write row even if status unknown — preserves the
                    # "generated coupon implies log row" guarantee.
                    log_prediction(coupon, telegram_sent=log_with_send_status)
            if coupons:
                out[hippo] = coupons
        except Exception as exc:
            logger.warning("shadow pool build failed for %s: %s",
                           pool.get("hippo"), exc)
            continue
    return out


VIEW_DIGEST = "digest"
VIEW_FULL = "full"
ENV_VIEW = "TJK_TOP4_BERKAY_VIEW"


def _view_mode() -> str:
    val = (os.environ.get(ENV_VIEW) or VIEW_DIGEST).strip().lower()
    if val not in {VIEW_DIGEST, VIEW_FULL}:
        return VIEW_DIGEST
    return val


def render_pool_shadow_messages(pools: Iterable[Mapping],
                                cutoff: str = "latest",
                                max_chars: int = 3500) -> list[str]:
    """Telegram-safe messages. By default uses the compact daily DIGEST
    renderer (one message per hippodrome, grouped picks, no clutter).
    Override with `TJK_TOP4_BERKAY_VIEW=full` for the legacy per-race
    chunked format.

    NEVER raises. Empty list if shadow flag is off or nothing renders.
    """
    if _view_mode() == VIEW_FULL:
        return [text for text, _coupons in
                render_pool_shadow_messages_with_coupons(pools, cutoff,
                                                        max_chars)]
    try:
        from .digest_renderer import render_digest_messages
        coupons_by_hippo = build_shadow_coupons_from_pools(pools,
                                                           cutoff=cutoff)
        return render_digest_messages(coupons_by_hippo)
    except Exception as exc:
        logger.warning("render_pool_shadow_messages(digest) failed: %s", exc)
        return []


def render_pool_shadow_messages_with_coupons(
    pools: Iterable[Mapping],
    cutoff: str = "latest",
    max_chars: int = 3500,
    force_view: Optional[str] = None,
) -> list[tuple[str, list[dict]]]:
    """Like `render_pool_shadow_messages`, but also returns the list
    of coupon dicts that each rendered message contains. This is the
    HARDENED path used by the scheduler to attach `telegram_sent`
    status to the prediction log row of each coupon in the chunk.

    Returns list of `(text, [coupon, ...])` tuples. NEVER raises.
    """
    try:
        # Build (without writing log here — logging happens at send-time)
        from .experimental_telegram import (
            render_experimental_messages_chunked,
            _render_race,
            HEADER,
        )
        from .experimental_coupon import DISCLAIMER
        if not is_shadow_enabled():
            return []
        view = force_view or _view_mode()
        out: list[tuple[str, list[dict]]] = []
        if view == VIEW_DIGEST:
            from .digest_renderer import render_hippo_digest
            for pool in pools:
                snaps = extract_race_snapshots_from_pool(pool)
                if not snaps:
                    continue
                hippo = pool.get("hippo") or pool.get("hippodrome") or "?"
                coupons: list[dict] = []
                for snap in snaps:
                    agf = _build_agf_snapshots(snap.get("horses") or [])
                    coupons.append(
                        build_berkay_scientific_top4_coupon(
                            snap, agf_snapshot=agf, cutoff=cutoff,
                        )
                    )
                if not coupons:
                    continue
                text = render_hippo_digest(hippo, coupons)
                if text:
                    out.append((text, coupons))
            return out
        for pool in pools:
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
            if not coupons:
                continue
            # Chunk: we need to track which coupons are in each chunk
            sep_len = len("\n\n" + ("─" * 24) + "\n\n")
            header_len = len(HEADER) + 2
            footer_len = len("\n\n<i>" + DISCLAIMER + "</i>")
            budget = max(800, max_chars - header_len - footer_len)
            chunks_coupons: list[list[dict]] = []
            current: list[dict] = []
            current_len = 0
            for coupon in coupons:
                race_text = _render_race(coupon)
                add_len = len(race_text) + (sep_len if current else 0)
                if current and current_len + add_len > budget:
                    chunks_coupons.append(current)
                    current = [coupon]
                    current_len = len(race_text)
                else:
                    current.append(coupon)
                    current_len += add_len
            if current:
                chunks_coupons.append(current)

            for chunk in chunks_coupons:
                texts = render_experimental_messages_chunked(
                    chunk, max_chars=max_chars,
                )
                # in practice render_experimental_messages_chunked
                # for our chunk of coupons returns exactly 1 message;
                # if it returns more (shouldn't), we associate ALL
                # coupons with the first message and write empties.
                for i, text in enumerate(texts):
                    if i == 0:
                        out.append((text, chunk))
                    else:
                        out.append((text, []))
        return out
    except Exception as exc:
        logger.warning("render_pool_shadow_messages_with_coupons failed: %s",
                       exc)
        return []


def log_predictions_for_chunk(coupons: Iterable[Mapping],
                              telegram_sent: bool,
                              telegram_send_error: Optional[str] = None,
                              ) -> int:
    """Write a log_prediction row for every coupon in a chunk, with the
    same telegram_sent / error status. Returns count of rows written.
    NEVER raises.
    """
    try:
        from .experimental_logger import log_prediction
    except Exception:
        return 0
    written = 0
    for c in coupons:
        try:
            r = log_prediction(
                c,
                telegram_sent=telegram_sent,
                telegram_send_error=telegram_send_error,
            )
            if r:
                written += 1
        except Exception as exc:
            logger.warning("log_predictions_for_chunk: %s", exc)
    return written


def maybe_append_telegram(
    existing_messages: list[str],
    results_dict: Mapping,
    cutoff: str = "latest",
) -> list[str]:
    """Return `existing_messages` plus an experimental block if flags
    are on AND the rendered block is non-empty. NEVER raises and NEVER
    mutates `existing_messages`.

    Safe to call unconditionally from production paths.

    Note on logging: when this path emits a Telegram block, we do not
    yet know if Telegram delivered it (the actual send happens in the
    caller). build_shadow_coupons writes log rows with
    telegram_sent=None to preserve the "coupon implies log row"
    guarantee. The send_telegram_simple wrapper records true delivery
    status via a separate hook in production (`log_after_send_simple`).
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
    """Walk a list of race results and write retro rows.

    Accepts TWO shapes:

      (a) Direct shadow shape — each item:
          `{race_id, race_label?, finish_order, payouts?, notes?}`

      (b) engine.retro shape — each item:
          `{hippodrome, altili_no, winners: [{race_number, horse_number, ...}]}`
          For this shape we build race_id candidates as
          `f"{hippo}_{race_number}"` and `f"{hippo} {race_number}. koşu"`
          and call `log_result` with `finish_order=[horse_number]`.

    Returns the summary path on success.
    """
    if not is_forward_log_enabled():
        return None
    try:
        from .experimental_logger import read_predictions
        race_results = list(race_results)
        # Detect shape: presence of `winners` array → engine.retro shape
        is_retro_shape = any("winners" in (r or {}) for r in race_results)
        if is_retro_shape:
            preds = read_predictions(date_str)
            pred_by_id = {p.get("race_id"): p for p in preds
                          if p.get("race_id")}
            for r in race_results:
                hippo = (r.get("hippodrome") or "").strip()
                for w in (r.get("winners") or []):
                    rn = w.get("race_number")
                    horse_no = w.get("horse_number")
                    if rn is None or horse_no is None:
                        continue
                    cands = [f"{hippo}_{rn}", f"{hippo} {rn}. koşu"]
                    race_id = next((c for c in cands if c in pred_by_id), None)
                    if not race_id:
                        for k in pred_by_id:
                            if (k.startswith(hippo)
                                    and (k.endswith(f"_{rn}")
                                         or k.endswith(f" {rn}. koşu"))):
                                race_id = k
                                break
                    if not race_id:
                        continue
                    pid = pred_by_id[race_id].get("prediction_id")
                    log_result(
                        race_id=race_id,
                        race_label=pred_by_id[race_id].get("race_label"),
                        prediction_id=pid,
                        finish_order=[int(horse_no)],
                        payouts={},
                        notes=["auto_attached_from_retro"],
                        force=True,
                        rebuild=False,  # batch — single rebuild at end
                    )
        else:
            for r in race_results:
                log_result(
                    race_id=str(r.get("race_id") or ""),
                    race_label=r.get("race_label"),
                    finish_order=r.get("finish_order") or [],
                    payouts=r.get("payouts") or {},
                    notes=r.get("notes") or [],
                    force=True,
                    rebuild=False,  # batch — single rebuild at end
                )
        # Single summary rebuild for the whole batch.
        return rebuild_summary(date_str)
    except Exception as exc:
        logger.warning("record_results_for_date failed: %s", exc)
        return None
