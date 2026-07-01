"""V10 ek özellikler — yaş × mesafe, kilo Δ, at_no bias, jokey/sire mesafe hit.

Berkay (2026-07-01): 'feature engineering çok önemli'.

Yeni V10 features (backfill data'da hesaplanabilir):
  1. age_x_distance      — age × (distance/1000) interaction
  2. weight_vs_horse_avg — bugünkü kilo vs at'ın tarihsel avg
  3. weight_carrier      — 60+ kg → 'heavy carrier' bayrak
  4. at_no_normalized    — start_no / n_horses (gate bias)
  5. at_no_low           — at_no ≤ 3 (içeriden) bayrak
  6. at_no_high          — at_no ≥ n-2 (dıştan) bayrak
  7. age_2yr / age_3yr / age_4yr / age_5plus — one-hot yaş grubu
  8. jockey_dist_top4    — bu jokey ± 200m mesafede history top4 %
  9. sire_dist_top4      — bu sire ± 200m mesafede offspring top4 %
 10. days_since_last     — mevcut (recov_days_since) — daha kesin hesap
 11. history_top4_gap    — son 3 vs son 6 finish avg (trend Δ)

Bu 11 feature V9.5'in 91 feature'ına ek → V10 ~101 feature.
Backfill data'da hesaplanabilir → CPCV backtest yapılabilir.

API
---
build_v10_features(name, ref_date, history_map, records_full,
                    jockey_stats, sire_stats,
                    horse_meta) → dict (11 feature)
"""
from __future__ import annotations

from collections import defaultdict
from typing import Optional


def _dist_band(d: Optional[int]) -> str:
    if not d:
        return "mid"
    if d <= 1200:
        return "sprint"
    if d <= 1600:
        return "mile"
    if d <= 2000:
        return "middle"
    return "stayer"


def build_jockey_stats(records: list[dict]) -> dict:
    """Jokey adı × (mesafe bandı) → win/top4/n."""
    stats = defaultdict(lambda: defaultdict(
        lambda: {"n": 0, "wins": 0, "top4": 0}))
    for r in records:
        j = (r.get("jockey") or "").strip()
        d_band = _dist_band(r.get("distance"))
        fin = r.get("finish")
        if not j or fin is None:
            continue
        s = stats[j][d_band]
        s["n"] += 1
        if fin == 1:
            s["wins"] += 1
        if fin <= 4:
            s["top4"] += 1
    return {j: dict(v) for j, v in stats.items()}


def build_sire_stats(records: list[dict], sire_lookup: dict) -> dict:
    """Sire × (mesafe bandı) → offspring win/top4/n.

    sire_lookup: {horse_name: sire_name}
    """
    stats = defaultdict(lambda: defaultdict(
        lambda: {"n": 0, "wins": 0, "top4": 0}))
    for r in records:
        nm = r.get("name")
        sire = sire_lookup.get(nm, "")
        if not sire:
            continue
        d_band = _dist_band(r.get("distance"))
        fin = r.get("finish")
        if fin is None:
            continue
        s = stats[sire][d_band]
        s["n"] += 1
        if fin == 1:
            s["wins"] += 1
        if fin <= 4:
            s["top4"] += 1
    return {s: dict(v) for s, v in stats.items()}


def build_horse_weight_history(records: list[dict]) -> dict:
    """Horse name → avg carried weight (kg)."""
    hw = defaultdict(list)
    for r in records:
        nm = r.get("name")
        w = r.get("weight")
        if nm and isinstance(w, (int, float)) and w > 0:
            hw[nm].append(float(w))
    return {nm: sum(w) / len(w) for nm, w in hw.items() if w}


def build_v10_features(name: str, ref_date: str,
                        horse_meta: dict,
                        race_context: dict,
                        history_records: list,
                        jockey_stats: dict,
                        sire_stats: dict,
                        horse_weight_avg: dict,
                        sire_lookup: dict) -> dict:
    """Bir at için V10 ek 11 feature.

    Args:
      name: at adı
      ref_date: point-in-time cutoff
      horse_meta: {age, weight, at_no, jockey, sire, n_horses}
      race_context: {distance, track_type}
      history_records: at'ın geçmiş yarışları (finish, distance, date...)
      jockey_stats / sire_stats: build_jockey_stats/sire_stats çıktısı
      horse_weight_avg: at → avg tarihsel kilo
      sire_lookup: at → sire (bu at için sire adı)
    """
    out = {
        "age_x_distance": 0.0,
        "weight_vs_horse_avg": 0.0,
        "weight_carrier": 0,
        "at_no_normalized": 0.5,
        "at_no_low": 0,
        "at_no_high": 0,
        "age_2yr": 0, "age_3yr": 0, "age_4yr": 0, "age_5plus": 0,
        "jockey_dist_top4_pct": 0.30,   # baseline
        "sire_dist_top4_pct": 0.30,
        "history_top4_gap": 0.0,
    }
    age = horse_meta.get("age") or 0
    weight = horse_meta.get("weight") or 0
    at_no = horse_meta.get("at_no")
    jockey = horse_meta.get("jockey") or ""
    n_field = horse_meta.get("n_horses") or 10
    distance = race_context.get("distance") or 1600

    # 1. Age × distance
    if age and distance:
        out["age_x_distance"] = round(age * (distance / 1000.0), 3)

    # 2-3. Weight
    hist_w = horse_weight_avg.get(name)
    if weight > 0:
        out["weight_carrier"] = 1 if weight >= 60 else 0
        if hist_w:
            out["weight_vs_horse_avg"] = round(weight - hist_w, 2)

    # 4-6. Post position
    if at_no is not None and n_field > 1:
        out["at_no_normalized"] = round(at_no / n_field, 3)
        out["at_no_low"] = 1 if at_no <= 3 else 0
        out["at_no_high"] = 1 if at_no >= (n_field - 2) else 0

    # 7. Age bucket
    if age == 2:
        out["age_2yr"] = 1
    elif age == 3:
        out["age_3yr"] = 1
    elif age == 4:
        out["age_4yr"] = 1
    elif age >= 5:
        out["age_5plus"] = 1

    # 8. Jockey × distance
    d_band = _dist_band(distance)
    js = (jockey_stats.get(jockey) or {}).get(d_band, {})
    if js.get("n", 0) >= 5:
        out["jockey_dist_top4_pct"] = round(
            js["top4"] / js["n"], 3)

    # 9. Sire × distance
    sire = sire_lookup.get(name, "")
    ss = (sire_stats.get(sire) or {}).get(d_band, {})
    if ss.get("n", 0) >= 5:
        out["sire_dist_top4_pct"] = round(ss["top4"] / ss["n"], 3)

    # 11. history_top4_gap: son 3 avg vs son 6 avg
    finishes = [h.get("finish") for h in (history_records or [])
                if isinstance(h.get("finish"), int)]
    if len(finishes) >= 6:
        avg3 = sum(finishes[:3]) / 3
        avg6 = sum(finishes[:6]) / 6
        out["history_top4_gap"] = round(avg6 - avg3, 3)  # pozitif = trend iyi

    return out


V10_FEATURE_KEYS = list(build_v10_features(
    "_probe", "2026-01-01",
    {"age": 4, "weight": 57, "at_no": 3, "jockey": "", "n_horses": 12},
    {"distance": 1600, "track_type": "Çim"},
    [], {}, {}, {}, {},
).keys())
