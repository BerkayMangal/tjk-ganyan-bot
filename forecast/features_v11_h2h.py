"""V11 head-to-head Elo — rakip kalite, POINT-IN-TIME (leakage-free).

Berkay (2026-07-01): 'rakip kalite yok, ihtimalleri arttıralım'.

Kronolojik Elo update + snapshot before each race.
h2h_wins timeline (winner, loser, date) — ref_date'e kadar sayılır.

Feature'lar (her at için ref_date'te):
  h2h_elo             — atın Elo skoru (snapshot at ref_date)
  h2h_elo_z           — sahaya göre z-score
  h2h_elo_rank        — sahadaki Elo sırası
  h2h_field_avg_elo   — koşudaki tüm atların Elo ortalaması
  h2h_field_var_elo   — Elo std (rekabet yoğunluğu)
  h2h_wins_vs_field   — bu rakiplere karşı tarihsel galibiyet %
  h2h_n_encounters    — tarihsel encounter sayısı
"""
from __future__ import annotations

from collections import defaultdict
from itertools import combinations

INIT_ELO = 1500.0
K_BASE = 24.0


def build_elo_timeline(records: list[dict]) -> dict:
    """Kronolojik Elo + point-in-time snapshots + tarihli h2h pairs.

    Returns:
      timeline[name]  = [(date, elo_before_this_race), ...]
      h2h_dates[pair] = [dates...] (winner beat loser at each of these dates)
      final_elo[name] = latest Elo
    """
    date_race_groups = defaultdict(list)
    for r in records:
        if r.get("finish") is None or not r.get("name"):
            continue
        date_race_groups[(r["date"], r["hippo"], r["kosu_no"])].append(r)

    elo: dict[str, float] = defaultdict(lambda: INIT_ELO)
    timeline: dict[str, list] = defaultdict(list)
    # h2h_dates[(winner, loser)] = sorted list of dates
    h2h_dates: dict[tuple, list] = defaultdict(list)

    ordered_races = sorted(date_race_groups.items(),
                            key=lambda kv: kv[0][0])

    for (_date, _hippo, _kosu), runners in ordered_races:
        finished = [r for r in runners if isinstance(r.get("finish"), int)]
        if len(finished) < 2:
            continue
        for r in finished:
            timeline[r["name"]].append((_date, elo[r["name"]]))
        for a, b in combinations(finished, 2):
            fa, fb = a["finish"], b["finish"]
            if fa == fb:
                continue
            winner = a if fa < fb else b
            loser = b if fa < fb else a
            wn, ln = winner["name"], loser["name"]
            ew = 1.0 / (1.0 + 10 ** ((elo[ln] - elo[wn]) / 400.0))
            k = K_BASE
            elo[wn] = elo[wn] + k * (1.0 - ew)
            elo[ln] = elo[ln] - k * (1.0 - ew)
            h2h_dates[(wn, ln)].append(_date)

    return {
        "final_elo": dict(elo),
        "timeline": dict(timeline),
        # sort each pair's date list for bisect
        "h2h_dates": {k: sorted(v) for k, v in h2h_dates.items()},
    }


def elo_at_date(timeline: dict, name: str, ref_date: str) -> float:
    events = timeline.get(name) or []
    if not events:
        return INIT_ELO
    last = INIT_ELO
    for d, e in events:
        if d < ref_date:
            last = e
        else:
            break
    return last


def _count_before(dates: list, ref_date: str) -> int:
    """Bisect: how many dates < ref_date."""
    # sorted ascending
    lo, hi = 0, len(dates)
    while lo < hi:
        mid = (lo + hi) // 2
        if dates[mid] < ref_date:
            lo = mid + 1
        else:
            hi = mid
    return lo


def h2h_wins_vs_field(h2h_dates: dict, name: str,
                       field: list[str], ref_date: str) -> tuple[int, int]:
    """Point-in-time (wins, encounters) — sadece ref_date öncesi."""
    wins = 0
    n = 0
    for opp in field:
        if opp == name:
            continue
        w = _count_before(h2h_dates.get((name, opp), []), ref_date)
        l = _count_before(h2h_dates.get((opp, name), []), ref_date)
        wins += w
        n += w + l
    return wins, n


def build_h2h_features(name: str, ref_date: str,
                        field_names: list[str],
                        elo_data: dict) -> dict:
    timeline = elo_data.get("timeline", {})
    h2h_dates = elo_data.get("h2h_dates", {})

    my_elo = elo_at_date(timeline, name, ref_date)
    field_elos = [elo_at_date(timeline, n, ref_date)
                  for n in field_names if n]
    if len(field_elos) < 2:
        return {
            "h2h_elo": round(my_elo, 1),
            "h2h_elo_z": 0.0,
            "h2h_elo_rank": 1,
            "h2h_field_avg_elo": round(my_elo, 1),
            "h2h_field_var_elo": 0.0,
            "h2h_wins_vs_field": 0.5,
            "h2h_n_encounters": 0,
        }
    avg = sum(field_elos) / len(field_elos)
    var = sum((e - avg) ** 2 for e in field_elos) / len(field_elos)
    std = var ** 0.5 or 1.0
    z = (my_elo - avg) / std
    rank = 1 + sum(1 for e in field_elos if e > my_elo)
    wins, n_enc = h2h_wins_vs_field(h2h_dates, name, field_names, ref_date)
    win_pct = (wins / n_enc) if n_enc > 0 else 0.5
    return {
        "h2h_elo": round(my_elo, 1),
        "h2h_elo_z": round(z, 3),
        "h2h_elo_rank": rank,
        "h2h_field_avg_elo": round(avg, 1),
        "h2h_field_var_elo": round(std, 1),
        "h2h_wins_vs_field": round(win_pct, 3),
        "h2h_n_encounters": n_enc,
    }


V11_H2H_FEATURE_KEYS = list(build_h2h_features(
    "_probe", "2026-01-01", ["_p1", "_p2", "_p3"],
    {"timeline": {}, "h2h_dates": {}}).keys())
