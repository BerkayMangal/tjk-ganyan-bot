"""V11 track conditional — hipodrom × mesafe, POINT-IN-TIME (leakage-free).

Berkay (2026-07-01): 'kısa mesafe İstanbul-kum ≠ uzun Ankara-çim'.

V10'da jokey×mesafe var, at×hipodrom ve at×mesafe_bandı YOK.
Bu dosya at-bazlı track istatistiklerini kronolojik snapshot ile tutar.

Feature'lar (bir at için):
  horse_hippo_top4_pct     — bu hipodromda tarihsel top4 %
  horse_hippo_n            — bu hipodromdaki koşu sayısı
  horse_dist_band_top4     — mesafe bandında top4 %
  horse_dist_band_n        — mesafe bandındaki koşu sayısı
  horse_hippo_dist_top4    — hipodrom × mesafe_bandı cross
  horse_hippo_first_time   — bu hipodroma ilk kez mi geliyor bayrağı
"""
from __future__ import annotations

from collections import defaultdict


def _dist_band(d):
    if not d:
        return "mid"
    if d <= 1200:
        return "sprint"
    if d <= 1600:
        return "mile"
    if d <= 2000:
        return "middle"
    return "stayer"


def _blank_counters():
    return {"hippo": defaultdict(lambda: {"n": 0, "top4": 0}),
            "dist_band": defaultdict(lambda: {"n": 0, "top4": 0}),
            "hippo_dist": defaultdict(lambda: {"n": 0, "top4": 0})}


def build_track_timeline(records: list[dict]) -> dict:
    """Kronolojik snapshot: her at için (date, counters_before_this_race).

    Point-in-time: at'ın kendi geçmişini kullanır, test dahil değil.
    """
    ordered = sorted(records, key=lambda r: r.get("date") or "")
    running: dict[str, dict] = defaultdict(_blank_counters)
    snapshots: dict[str, list] = defaultdict(list)

    def _clone(c):
        return {
            "hippo": {k: dict(v) for k, v in c["hippo"].items()},
            "dist_band": {k: dict(v) for k, v in c["dist_band"].items()},
            "hippo_dist": {str(k): dict(v)
                           for k, v in c["hippo_dist"].items()},
        }

    for r in ordered:
        nm = r.get("name")
        fin = r.get("finish")
        if not nm:
            continue
        date = r.get("date") or ""
        # SNAPSHOT before applying
        snapshots[nm].append((date, _clone(running[nm])))
        if fin is None:
            continue
        hippo = r.get("hippo") or ""
        band = _dist_band(r.get("distance"))
        cell = (hippo, band)
        running[nm]["hippo"][hippo]["n"] += 1
        running[nm]["dist_band"][band]["n"] += 1
        running[nm]["hippo_dist"][cell]["n"] += 1
        if fin <= 4:
            running[nm]["hippo"][hippo]["top4"] += 1
            running[nm]["dist_band"][band]["top4"] += 1
            running[nm]["hippo_dist"][cell]["top4"] += 1
    return dict(snapshots)


def _snap_at(snapshots: dict, name: str, ref_date: str) -> dict:
    events = snapshots.get(name) or []
    last = None
    for d, s in events:
        if d < ref_date:
            last = s
        else:
            break
    return last or {"hippo": {}, "dist_band": {}, "hippo_dist": {}}


def build_track_features(name: str, ref_date: str,
                          race_context: dict,
                          track_timeline: dict) -> dict:
    """Bir at için 6 track feature — POINT-IN-TIME."""
    hippo = race_context.get("hippo") or ""
    distance = race_context.get("distance") or 1600
    band = _dist_band(distance)
    cell_key = str((hippo, band))
    snap = _snap_at(track_timeline, name, ref_date)

    h_stat = snap["hippo"].get(hippo)
    d_stat = snap["dist_band"].get(band)
    hd_stat = snap["hippo_dist"].get(cell_key)

    def _pct(s):
        if not s or s.get("n", 0) < 2:
            return 0.30
        return round(s["top4"] / s["n"], 3)

    return {
        "horse_hippo_top4_pct": _pct(h_stat),
        "horse_hippo_n": h_stat.get("n", 0) if h_stat else 0,
        "horse_dist_band_top4": _pct(d_stat),
        "horse_dist_band_n": d_stat.get("n", 0) if d_stat else 0,
        "horse_hippo_dist_top4": _pct(hd_stat),
        "horse_hippo_first_time": (1 if not h_stat
                                    or h_stat.get("n", 0) == 0 else 0),
    }


V11_TRACK_FEATURE_KEYS = list(build_track_features(
    "_probe", "2026-01-01",
    {"hippo": "X", "distance": 1600}, {}).keys())
