"""SİB TOP4 picks — forward log + retro attach.

SİB picks (DIAMOND / ALTIN / PREMIUM / FIRSAT tier'lerinden gelen
"BUNU OYNA" pick'leri) için ayrı bir log hattı. Berkay'ın talebi:
"SİB için retro göremiyorum olmuş mu olmamış mı."

Log path:
  data/forward_logs/sib_top4/YYYY-MM-DD.jsonl

Event types:
  - sib_pick      : each pick row, written when collect_today_picks runs
  - sib_result    : each pick attached to its actual top4 placement
  - sib_summary   : daily aggregate, written by rebuild_summary

NEVER raises. Disabled when TJK_TOP4_FORWARD_LOG != 1
(reuses the existing flag — no new env var needed).
"""
from __future__ import annotations

import json
import logging
import os
import threading
from collections import Counter
from datetime import datetime, timezone
from typing import Iterable, Mapping, Optional

logger = logging.getLogger(__name__)

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOG_DIR = os.path.join(REPO_ROOT, "data", "forward_logs", "sib_top4")

_WRITE_LOCK = threading.Lock()


def _is_forward_log_enabled() -> bool:
    return os.environ.get("TJK_TOP4_FORWARD_LOG", "0") == "1"


def _today_str() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d")


def _path_for(date_str: Optional[str] = None) -> str:
    return os.path.join(LOG_DIR, f"{(date_str or _today_str())}.jsonl")


def _summary_path_for(date_str: Optional[str] = None) -> str:
    return os.path.join(LOG_DIR, f"{(date_str or _today_str())}.summary.json")


def _pick_key(pick: Mapping) -> str:
    """Stable identity for a SiB pick: hippo + race_no + horse_no."""
    h = (pick.get("hippo_base") or pick.get("pool") or "").strip()
    rn = pick.get("race_no") or pick.get("leg") or "?"
    no = pick.get("horse_no") or "?"
    return f"{h}|{rn}|{no}"


def log_sib_picks(payload: Mapping, *,
                  telegram_sent: bool = False,
                  force: bool = False) -> Optional[str]:
    """Persist SiB picks. Idempotent on (date, pick_key).

    `payload` is the `collect_today_picks()` return value:
      {date, diamond, altin, premium, firsat, totals}

    Returns the file path written, or None when disabled / nothing to log.
    """
    if not force and not _is_forward_log_enabled():
        return None
    try:
        os.makedirs(LOG_DIR, exist_ok=True)
        date_str = str(payload.get("date") or _today_str())
        existing_keys = {p["pick_key"] for p in read_picks(date_str)}
        path = _path_for(date_str)
        rows_to_write: list[dict] = []
        for tier in ("diamond", "altin", "premium", "firsat"):
            for pick in (payload.get(tier) or []):
                k = _pick_key(pick)
                if k in existing_keys:
                    continue
                rows_to_write.append({
                    "event_type": "sib_pick",
                    "logged_at": datetime.now(timezone.utc).isoformat(),
                    "date": date_str,
                    "tier": tier.upper(),
                    "pick_key": k,
                    "hippo": pick.get("hippo_base") or pick.get("pool", ""),
                    "race_no": pick.get("race_no"),
                    "race_time": pick.get("race_time") or pick.get("first_time"),
                    "horse_no": pick.get("horse_no"),
                    "horse_name": pick.get("name"),
                    "agf": pick.get("agf"),
                    "mp": pick.get("mp"),
                    "mult": pick.get("mult"),
                    "field_size": pick.get("field_size"),
                    "tier_label": pick.get("tier"),
                    "jockey_name": pick.get("jockey_name") or "",
                    "jockey_cond_top4": pick.get("jockey_cond_top4"),
                    "telegram_sent": telegram_sent,
                })
                existing_keys.add(k)
        if not rows_to_write:
            return None
        with _WRITE_LOCK, open(path, "a", encoding="utf-8") as fh:
            for r in rows_to_write:
                fh.write(json.dumps(r, default=str, ensure_ascii=False)
                         + "\n")
        return path
    except Exception as exc:
        logger.warning("log_sib_picks failed: %s", exc)
        return None


def read_picks(date_str: Optional[str] = None) -> list[dict]:
    """Read all sib_pick rows for a date. Latest occurrence per
    pick_key wins."""
    path = _path_for(date_str)
    if not os.path.exists(path):
        return []
    by_key: dict[str, dict] = {}
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event_type") != "sib_pick":
                    continue
                k = row.get("pick_key")
                if k:
                    by_key[k] = row
    except OSError:
        return []
    return list(by_key.values())


def read_results(date_str: Optional[str] = None) -> list[dict]:
    """Read all sib_result rows for a date."""
    path = _path_for(date_str)
    if not os.path.exists(path):
        return []
    out: list[dict] = []
    try:
        with open(path, encoding="utf-8") as fh:
            for line in fh:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("event_type") == "sib_result":
                    out.append(row)
    except OSError:
        return []
    # dedupe by pick_key (latest wins)
    seen: dict[str, dict] = {}
    for r in out:
        k = r.get("pick_key")
        if k:
            seen[k] = r
    return list(seen.values())


def _normalize_hippo(name: str) -> str:
    """Lowercase + Turkish-fold for matching."""
    if not name:
        return ""
    s = str(name).lower().strip()
    # Light TR-fold (mirrors yerli_engine pattern)
    tr_map = {"ı": "i", "İ": "i", "ş": "s", "ğ": "g",
              "ü": "u", "ö": "o", "ç": "c"}
    for src, dst in tr_map.items():
        s = s.replace(src, dst)
    # Strip "hipodromu" suffix variants
    for suf in (" hipodromu", " hipodrom"):
        if s.endswith(suf):
            s = s[: -len(suf)]
    return s.strip()


def attach_sib_results(date_str: str,
                       raw_results: Iterable[Mapping],
                       *, force: bool = False) -> dict:
    """Walk picks for `date_str`; for each, look up the corresponding
    race's finish_order from raw_results and write a sib_result row.

    `raw_results` is the engine.retro shape:
      [{hippodrome, altili_no, winners: [{race_number, horse_number,
         ...}]}, ...]

    NEVER raises. Returns a status dict.
    """
    status = {"attached": 0, "picks": 0, "errors": [], "skipped": False}
    if not force and not _is_forward_log_enabled():
        status["skipped"] = True
        status["reason"] = "TJK_TOP4_FORWARD_LOG != 1"
        return status
    try:
        picks = read_picks(date_str)
        if not picks:
            status["skipped"] = True
            status["reason"] = "no picks for date"
            return status

        # Build winner lookup: (hippo_norm, race_no) -> horse_number
        winner_map: dict[tuple[str, int], int] = {}
        for r in raw_results or []:
            hp = _normalize_hippo(r.get("hippodrome") or "")
            for w in (r.get("winners") or []):
                rn = w.get("race_number")
                hno = w.get("horse_number")
                if rn is not None and hno is not None:
                    try:
                        winner_map[(hp, int(rn))] = int(hno)
                    except (TypeError, ValueError):
                        continue
        if not winner_map:
            status["skipped"] = True
            status["reason"] = "no winners parsed"
            return status

        # Note: engine.retro `winners` contains ONLY the actual top-1
        # (winner) per leg in current shape, not full top-4. We mark
        # a pick "won" if it matches the winner; "in_top4=None" when
        # we cannot tell (the data simply doesn't carry top-4 order
        # in this path). When richer data arrives, this hook upgrades.

        os.makedirs(LOG_DIR, exist_ok=True)
        existing_keys = {r["pick_key"] for r in read_results(date_str)}
        result_rows: list[dict] = []
        for p in picks:
            status["picks"] += 1
            k = p.get("pick_key")
            if not k or k in existing_keys:
                continue
            hp_norm = _normalize_hippo(p.get("hippo") or "")
            try:
                rn = int(p.get("race_no") or 0)
                hno = int(p.get("horse_no") or 0)
            except (TypeError, ValueError):
                continue
            if rn <= 0 or hno <= 0:
                continue
            winner = winner_map.get((hp_norm, rn))
            if winner is None:
                # try fuzzy: any hp containing/contained
                for (hp2, rn2), w2 in winner_map.items():
                    if rn2 != rn:
                        continue
                    if hp_norm in hp2 or hp2 in hp_norm:
                        winner = w2
                        break
            if winner is None:
                continue  # race not in results yet
            won = bool(winner == hno)
            result_rows.append({
                "event_type": "sib_result",
                "logged_at": datetime.now(timezone.utc).isoformat(),
                "date": date_str,
                "pick_key": k,
                "tier": p.get("tier"),
                "hippo": p.get("hippo"),
                "race_no": rn,
                "horse_no": hno,
                "horse_name": p.get("horse_name"),
                "winner_horse_no": winner,
                "won": won,
                # in_top4 is unknown from current retro shape (winner-only)
                "in_top4": None,
                "agf": p.get("agf"),
                "mp": p.get("mp"),
            })
            existing_keys.add(k)
            status["attached"] += 1

        if result_rows:
            with _WRITE_LOCK, open(_path_for(date_str), "a",
                                   encoding="utf-8") as fh:
                for r in result_rows:
                    fh.write(json.dumps(r, default=str,
                                        ensure_ascii=False) + "\n")
        rebuild_summary(date_str)
    except Exception as exc:
        status["errors"].append(repr(exc)[:160])
        logger.warning("attach_sib_results: %s", exc)
    return status


def rebuild_summary(date_str: Optional[str] = None) -> Optional[str]:
    """Aggregate sib_pick + sib_result into a daily summary file."""
    try:
        date_str = date_str or _today_str()
        picks = read_picks(date_str)
        results = read_results(date_str)
        if not picks and not results:
            return None
        os.makedirs(LOG_DIR, exist_ok=True)
        res_by_key = {r.get("pick_key"): r for r in results
                      if r.get("pick_key")}
        by_tier: dict[str, Counter] = {
            "DIAMOND": Counter(), "ALTIN": Counter(),
            "PREMIUM": Counter(), "FIRSAT": Counter(),
        }
        by_hippo: Counter = Counter()
        won_by_tier: Counter = Counter()
        attached_by_tier: Counter = Counter()
        for p in picks:
            tier = (p.get("tier") or "").upper()
            if tier in by_tier:
                by_tier[tier]["total"] += 1
            by_hippo[p.get("hippo") or "?"] += 1
            res = res_by_key.get(p.get("pick_key"))
            if res:
                attached_by_tier[tier] += 1
                if res.get("won"):
                    won_by_tier[tier] += 1

        summary = {
            "date": date_str,
            "label": "SIB_TOP4",
            "picks_total": len(picks),
            "results_total": len(results),
            "picks_pending": max(0, len(picks) - len(results)),
            "by_tier_total": {t: c.get("total", 0)
                              for t, c in by_tier.items()},
            "by_tier_attached": dict(attached_by_tier),
            "by_tier_won": dict(won_by_tier),
            "by_hippo_total": dict(by_hippo),
            "win_rate_by_tier": {
                t: (won_by_tier[t] / attached_by_tier[t])
                if attached_by_tier[t] else None
                for t in ("DIAMOND", "ALTIN", "PREMIUM", "FIRSAT")
            },
            "notes": [
                "won = SİB pick horse == race winner (top-1).",
                "in_top4 not tracked yet — retro winners array is top-1 only.",
            ],
        }
        sp = _summary_path_for(date_str)
        with open(sp, "w", encoding="utf-8") as fh:
            json.dump(summary, fh, indent=2, ensure_ascii=False)
        return sp
    except Exception:
        return None


def load_summary(date_str: Optional[str] = None) -> Optional[dict]:
    sp = _summary_path_for(date_str)
    if not os.path.exists(sp):
        return None
    try:
        with open(sp, encoding="utf-8") as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return None
