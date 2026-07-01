"""V11 pace scenario — koşu içi tempo, POINT-IN-TIME (leakage-free).

Berkay (2026-07-01): 'pace-heavy koşularda finisher edge çıkar'.

Style inference (at_no × finish proxy):
  early_leader   → at_no ≤ ceil(n/3) AND finish ≤ ceil(n/3)
  late_finisher  → at_no ≥ n-ceil(n/3)+1 AND finish ≤ ceil(n/3)
  mid_stalker    → at_no ortada, finish top-half

Data leakage fix: kronolojik pass, her row için snapshot AT_time-of-race.
Test sample'ın kendisi istatistiğe girmez → dürüst OOS.

Feature'lar (bir at için):
  pace_style_leader_pct    — tarihsel early leader %
  pace_style_finisher_pct  — tarihsel late finisher %
  pace_style_stalker_pct   — mid stalker
  field_n_leaders          — sahada erken lider sayısı
  field_n_finishers        — sahada finisher sayısı
  pace_advantage           — atın stili sahaya uygun mu (heuristic −1..1)
"""
from __future__ import annotations

from collections import defaultdict
from math import ceil


def _classify_style(at_no, finish, n_horses) -> str:
    if not isinstance(at_no, int) or not isinstance(finish, int):
        return "unknown"
    if n_horses < 3:
        return "unknown"
    inner_cut = max(1, ceil(n_horses / 3))
    outer_cut = n_horses - inner_cut + 1
    front_cut = max(1, ceil(n_horses / 3))
    is_inner = at_no <= inner_cut
    is_outer = at_no >= outer_cut
    is_front = finish <= front_cut
    if is_inner and is_front:
        return "early_leader"
    if is_outer and is_front:
        return "late_finisher"
    if is_front:
        return "mid_stalker"
    return "back"


def build_pace_timeline(records: list[dict]) -> dict:
    """Kronolojik snapshot: her at için (date, stats_before_this_race).

    stats_before_this_race = sadece date-öncesi koşulardan biriken sayaç.
    """
    ordered = sorted(records, key=lambda r: r.get("date") or "")
    running: dict[str, dict[str, int]] = defaultdict(
        lambda: {"early_leader": 0, "late_finisher": 0,
                  "mid_stalker": 0, "back": 0, "_total": 0})
    snapshots: dict[str, list] = defaultdict(list)
    for r in ordered:
        nm = r.get("name")
        if not nm:
            continue
        date = r.get("date") or ""
        # SNAPSHOT before applying this race
        snapshots[nm].append((date, dict(running[nm])))
        # APPLY this race to running counter
        style = _classify_style(r.get("at_no"), r.get("finish"),
                                 r.get("n_horses") or 10)
        if style != "unknown":
            running[nm][style] += 1
            running[nm]["_total"] += 1
    return dict(snapshots)


def horse_style_pct_at(pace_timeline: dict, name: str,
                        ref_date: str) -> dict:
    """Point-in-time: at'ın ref_date'ten önceki style dağılımı."""
    events = pace_timeline.get(name) or []
    snap = None
    for d, s in events:
        if d < ref_date:
            snap = s
        else:
            break
    if not snap:
        return {"leader_pct": 0.10, "finisher_pct": 0.10,
                "stalker_pct": 0.15, "sample_n": 0}
    total = snap.get("_total", 0)
    if total < 3:
        return {"leader_pct": 0.10, "finisher_pct": 0.10,
                "stalker_pct": 0.15, "sample_n": total}
    return {
        "leader_pct": round(snap.get("early_leader", 0) / total, 3),
        "finisher_pct": round(snap.get("late_finisher", 0) / total, 3),
        "stalker_pct": round(snap.get("mid_stalker", 0) / total, 3),
        "sample_n": total,
    }


def build_pace_features(name: str, ref_date: str,
                         field_names: list[str],
                         pace_timeline: dict) -> dict:
    """Bir at için 6 pace feature — POINT-IN-TIME."""
    me = horse_style_pct_at(pace_timeline, name, ref_date)
    field_stats = [horse_style_pct_at(pace_timeline, n, ref_date)
                    for n in field_names if n]
    n_leaders = sum(1 for s in field_stats
                    if s["leader_pct"] >= 0.25 and s["sample_n"] >= 3)
    n_finishers = sum(1 for s in field_stats
                       if s["finisher_pct"] >= 0.25 and s["sample_n"] >= 3)
    advantage = 0.0
    if n_leaders >= 3:
        advantage = me["finisher_pct"] - me["leader_pct"]
    elif n_leaders <= 1:
        advantage = me["leader_pct"] - me["finisher_pct"]
    return {
        "pace_style_leader_pct": me["leader_pct"],
        "pace_style_finisher_pct": me["finisher_pct"],
        "pace_style_stalker_pct": me["stalker_pct"],
        "field_n_leaders": n_leaders,
        "field_n_finishers": n_finishers,
        "pace_advantage": round(advantage, 3),
    }


V11_PACE_FEATURE_KEYS = list(build_pace_features(
    "_probe", "2026-01-01", ["_p1"], {}).keys())
