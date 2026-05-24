"""Phase 5.6 PART 8 — backtest V5.1 vs V9 (router+3 strateji) paired + ablation + walk-forward.

⚠ payout = PROXY (dividend ≈ BF/Π(winner_agf_share); gerçek TJK dividend YOK). model_prob=AGF-
fallback. n=122 (strateji alt-örnekleri daha küçük). Walk-forward: eşikler full-fit (circularity
caveat). Run: PYTHONPATH=.:dashboard python -m simulation.v9.backtest_v9
"""
from __future__ import annotations

import os
import random
import sys
import warnings
from collections import defaultdict

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from simulation.snapshot_builder import build_snapshots                 # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy           # noqa: E402
from simulation.v9.pipeline import build_v9_race, enriched_lookup, run_pipeline  # noqa: E402
from simulation.v9.layer_aggregator import aggregate_race               # noqa: E402

BF = 1.25


def _winner_shares(snap, actual):
    sh = []
    for i, ls in enumerate(snap.get("legs_summary", [])):
        w = actual[i]
        m = {h["number"]: (h.get("agf_pct") or 0) / 100.0 for h in ls.get("all_horses_with_mp", [])}
        sh.append(max(0.01, m.get(w, 0.02)))
    return sh


def _dividend(shares):
    p = 1.0
    for s in shares:
        p *= s
    return BF / p if p > 0 else 0.0


def _score(tickets, actual, snap):
    hit = any(all(i < len(t["legs_selected"]) and actual[i] in t["legs_selected"][i]
                  for i in range(len(actual))) for t in tickets) if tickets else False
    cost = sum(t["cost"] for t in tickets)
    payout = _dividend(_winner_shares(snap, actual)) if hit else 0.0
    return hit, cost, payout


def _agg(rows):
    n = len(rows)
    if not n:
        return {"n": 0}
    tc = sum(r[1] for r in rows); tp = sum(r[2] for r in rows); hits = sum(1 for r in rows if r[0])
    return {"n": n, "hit": hits, "hit_rate": round(hits / n, 4),
            "avg_cost": round(tc / n, 1),
            "roi_proxy_pct": round((tp - tc) / tc * 100, 1) if tc else 0.0,
            "ci": _ci(rows)}


def _ci(rows, nb=1000, seed=7):
    rng = random.Random(seed); m = len(rows); out = []
    for _ in range(nb):
        s = [rows[rng.randrange(m)] for _ in range(m)]
        c = sum(x[1] for x in s); p = sum(x[2] for x in s)
        out.append((p - c) / c * 100 if c else 0)
    out.sort()
    return [round(out[25], 0), round(out[975], 0)]


def main():
    enr = enriched_lookup()
    snaps = build_snapshots("raw")
    dates = sorted({s["result"]["date"] for s in snaps})
    test_dates = set(dates[-10:])

    v51_rows, v9_rows = [], []
    by_strat = defaultdict(list)
    v9_test = []
    freq = defaultdict(int)
    for s in snaps:
        res = s["result"]; act = s["actual_results"]
        # V5.1 (single ticket)
        k51 = v5_1_strategy(res)
        t51 = [{"legs_selected": k51["legs_selected"], "cost": k51["cost"]}]
        v51_rows.append(_score(t51, act, res))
        # V9 (multi-ticket, routed)
        race = build_v9_race(res, enr)
        out = run_pipeline(race)
        strat = out["routing"]["strategy"]; freq[strat] += 1
        tk = out["kupon"].get("tickets") or []
        r9 = _score(tk, act, res) if tk else (False, 0.0, 0.0)
        v9_rows.append(r9)
        by_strat[strat].append(r9)
        if res["date"] in test_dates:
            v9_test.append(r9)

    print(f"N={len(snaps)}  (walk-forward test son {len(test_dates)} gün)\n")
    print("=== ANA KARŞILAŞTIRMA (payout=PROXY) ===")
    print("V5.1 :", _agg(v51_rows))
    print("V9   :", _agg([r for r in v9_rows if r[1] > 0]), "(Pas hariç)")
    print("V9(+Pas dahil tüm):", _agg(v9_rows))

    print("\n=== STRATEJİ BAZLI (V9) ===")
    for st in ("tam_sistem", "favori_yikma", "kangal", "pas"):
        rows = by_strat.get(st) or []
        if rows:
            print(f"  {st:13} freq={freq[st]:3} {_agg(rows)}")

    print("\n=== ABLATION (coverage top-3/ayak, 6/6 hit) ===")
    layer_sets = [("raw(∅)", set()), ("L4", {"L4"}), ("L4+L5", {"L4", "L5"}),
                  ("L4+L5+L6(full)", {"L4", "L5", "L6"})]
    for name, lset in layer_sets:
        hits = tot = 0; combos = []
        for s in snaps:
            race = build_v9_race(s["result"], enr)
            agg = aggregate_race(race, layers=lset)
            ok = True; combo = 1
            for i, leg in enumerate(agg["legs"]):
                top3 = [p["number"] for p in leg["profiles"][:3]]
                combo *= max(1, len(top3))
                if s["actual_results"][i] not in top3:
                    ok = False
            hits += int(ok); tot += 1; combos.append(combo)
        print(f"  {name:16} 6/6 hit={hits}/{tot} ({hits/tot*100:.1f}%) avg_combo={sum(combos)/len(combos):.0f}")

    print("\n=== WALK-FORWARD (son 10 gün OOS; ⚠ eşikler full-fit → tam temiz değil) ===")
    print("  V9 OOS:", _agg([r for r in v9_test if r[1] > 0]))

    print("\n=== STRATEJİ FREKANS (30 gün) ===", dict(freq))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
