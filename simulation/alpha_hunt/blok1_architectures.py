"""BLOK 1 — kupon mimari alternatifleri (A-F). 122 altılı, walk-forward (train 20g/test 10g).
⚠ payout=PROXY (dividend≈bf/Π(winner_agf_share)). hit-rate=GERÇEK. coverage-union scoring.
Run: PYTHONPATH=.:dashboard python -m simulation.alpha_hunt.blok1_architectures
"""
from __future__ import annotations
import os, sys, warnings, math
warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from simulation.snapshot_builder import build_snapshots                  # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy            # noqa: E402
from simulation.v9.pipeline import build_v9_race, run_pipeline           # noqa: E402
from simulation.alpha_hunt.data import flb_mult, bootstrap_ci            # noqa: E402
BF = 1.25


def _entropy(agfs):
    vals = [a for a in agfs if a > 0]
    if len(vals) < 2:
        return 0.0
    s = sum(vals); p = [v / s for v in vals]
    return -sum(pi * math.log(pi) for pi in p if pi > 0) / math.log(len(p))


def _legs(snap):
    return [[(h["number"], h.get("agf_pct", 0)) for h in ls.get("all_horses_with_mp", [])]
            for ls in snap["result"]["legs_summary"]]


def _topn(horses, n, key):
    return [h[0] for h in sorted(horses, key=key, reverse=True)[:max(1, n)]]


def _sel(snap, arch):
    legs = _legs(snap)
    if arch == "A_v5.1":
        return v5_1_strategy(snap["result"])["legs_selected"]
    if arch == "B_v9":
        return run_pipeline(build_v9_race(dict(snap["result"]), None))["kupon"].get("legs_selected") or []
    out = []
    for hs in legs:
        if arch == "C_FLB":          # kalibre = agf*flb, top-3
            out.append(_topn(hs, 3, key=lambda h: h[1] * flb_mult(h[1])))
        elif arch.startswith("D_top"):
            n = int(arch[-1]); out.append(_topn(hs, n, key=lambda h: h[1]))
        elif arch == "E_riskparity":  # entropy yüksek → daha geniş (2..5)
            e = _entropy([h[1] for h in hs]); n = 2 + int(round(e * 3))
            out.append(_topn(hs, n, key=lambda h: h[1]))
        elif arch == "F_antipublic":  # ters-agf top-3 (contrarian)
            out.append(_topn(hs, 3, key=lambda h: -h[1]))
    return out


def _score(snap, sel):
    act = snap["actual_results"]
    hit = all(i < len(sel) and act[i] in (sel[i] or []) for i in range(6))
    partial = sum(1 for i in range(6) if i < len(sel) and act[i] in (sel[i] or []))
    combo = 1
    for s in sel:
        combo *= max(1, len(s))
    cost = combo * BF
    # proxy dividend
    payout = 0.0
    if hit:
        shares = []
        for i, ls in enumerate(snap["result"]["legs_summary"]):
            m = {h["number"]: (h.get("agf_pct") or 0) / 100.0 for h in ls.get("all_horses_with_mp", [])}
            shares.append(max(0.01, m.get(act[i], 0.02)))
        prod = 1.0
        for s in shares:
            prod *= s
        payout = BF / prod if prod > 0 else 0
    return hit, partial, cost, payout


def _agg(rows):
    n = len(rows); hits = sum(1 for r in rows if r[0])
    tc = sum(r[2] for r in rows); tp = sum(r[3] for r in rows)
    rois = [(r[3] - r[2]) for r in rows]
    return {"n": n, "hit%": round(hits / n * 100, 1), "avg_partial": round(sum(r[1] for r in rows) / n, 2),
            "avg_cost": round(tc / n, 0), "ROIproxy%": round((tp - tc) / tc * 100, 0) if tc else 0,
            "pnl_ci": bootstrap_ci(rois)}


def main():
    snaps = build_snapshots("raw")
    dates = sorted({s["result"]["date"] for s in snaps})
    test = set(dates[-10:])
    archs = ["A_v5.1", "B_v9", "C_FLB", "D_top2", "D_top3", "D_top4", "D_top5", "E_riskparity", "F_antipublic"]
    print("PRE-REG: 6 mimari ailesi (A-F), metrik=hit%/cost/ROIproxy, walk-forward test=son10g. H0: A/B en iyi.\n")
    print(f"{'arch':14} {'ALL n':>6} {'hit%':>6} {'cost':>7} {'ROIproxy%':>10} | {'OOS hit%':>8} {'OOS ROI%':>9}")
    results = {}
    for a in archs:
        allrows = [_score(s, _sel(s, a)) for s in snaps]
        oos = [_score(s, _sel(s, a)) for s in snaps if s["result"]["date"] in test]
        ag = _agg(allrows); og = _agg(oos); results[a] = (ag, og)
        print(f"{a:14} {ag['n']:>6} {ag['hit%']:>6} {ag['avg_cost']:>7} {ag['ROIproxy%']:>10} | "
              f"{og['hit%']:>8} {og['ROIproxy%']:>9}")
    return results


if __name__ == "__main__":
    main()
