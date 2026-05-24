"""Phase 5.8.1 — 4 varyant paired backtest (PROD-path enr=None, canlı ile aynı).
V5.1 / v9_A40(current) / v9_A50(sıkı) / v9_hybrid. n=122, walk-forward (test son 10g), Cohen's d.
⚠ payout=PROXY (dividend≈bf/Π winner-share) → hit-rate+cost daha güvenilir; ROIproxy heavy-tail.
Run: PYTHONPATH=.:dashboard python -m simulation.v9.backtest_v9_variants
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
from simulation.snapshot_builder import build_snapshots                  # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy            # noqa: E402
from simulation.v9.pipeline import build_v9_race, run_pipeline           # noqa: E402
from simulation.alpha_hunt.data import bootstrap_ci, cohen_d             # noqa: E402
BF = 1.25


def _dividend(snap, act):
    shares = []
    for i, ls in enumerate(snap["result"]["legs_summary"]):
        m = {h["number"]: (h.get("agf_pct") or 0) / 100.0 for h in ls.get("all_horses_with_mp", [])}
        shares.append(max(0.01, m.get(act[i], 0.02)))
    prod = 1.0
    for s in shares:
        prod *= s
    return BF / prod if prod > 0 else 0.0


def _tickets(snap, variant):
    if variant == "V5.1":
        k = v5_1_strategy(snap["result"])
        return [{"legs": k["legs_selected"], "cost": k["cost"]}]
    out = run_pipeline(build_v9_race(dict(snap["result"]), None))["kupon"]
    return [{"legs": t["legs_selected"], "cost": t["cost"]} for t in (out.get("tickets") or [])]


def _score(snap, variant):
    act = snap["actual_results"]
    tks = _tickets(snap, variant)
    hit = any(all(i < len(t["legs"]) and act[i] in (t["legs"][i] or []) for i in range(6)) for t in tks) if tks else False
    partial = max((sum(1 for i in range(6) if i < len(t["legs"]) and act[i] in (t["legs"][i] or [])) for t in tks), default=0)
    cost = sum(t["cost"] for t in tks)
    payout = _dividend(snap, act) if hit else 0.0
    return {"hit": int(hit), "p5": int(partial >= 5), "partial": partial, "cost": cost,
            "pnl": payout - cost, "payout": payout}


def _env(threshold, mode):
    os.environ["TJK_V9_FAV_AGF_THRESHOLD"] = str(threshold)
    os.environ["TJK_V9_FAVYIKMA_MODE"] = mode


def _agg(rows):
    n = len(rows); tc = sum(r["cost"] for r in rows); tp = sum(r["payout"] for r in rows)
    return {"n": n, "hit6%": round(sum(r["hit"] for r in rows) / n * 100, 1),
            "hit5+%": round(sum(r["p5"] for r in rows) / n * 100, 1),
            "avg_partial": round(sum(r["partial"] for r in rows) / n, 2),
            "avg_cost": round(tc / n, 0),
            "ROIproxy%": round((tp - tc) / tc * 100, 0) if tc else 0,
            "pnl_ci": bootstrap_ci([r["pnl"] for r in rows])}


def main():
    snaps = build_snapshots("raw")
    dates = sorted({s["result"]["date"] for s in snaps})
    test = set(dates[-10:])
    variants = [("V5.1", None, None), ("v9_A40(current)", 40.0, "pure"),
                ("v9_A50", 50.0, "pure"), ("v9_hybrid", 40.0, "hybrid")]
    print("PRE-REG: 4 varyant aynı 122 altılı, PROD-path. Karar=hit6%+cost+ROIproxy-CI (proxy uyarısı). "
          "H0: hibrit/A50 v9_A40'tan iyi.\n")
    print(f"{'variant':18} {'hit6%':>6} {'hit5+%':>7} {'avg_cost':>9} {'ROIproxy%':>10} {'pnl_CI':>20} | {'OOS hit6%':>9} {'d_vs_V5.1':>9}")
    base_pnl = None
    rows_by = {}
    for name, thr, mode in variants:
        if name != "V5.1":
            _env(thr, mode)
        rows = [_score(s, name if name == "V5.1" else "v9") for s in snaps]
        oos = [_score(s, name if name == "V5.1" else "v9") for s in snaps if s["result"]["date"] in test]
        rows_by[name] = [r["pnl"] for r in rows]
        if name == "V5.1":
            base_pnl = rows_by[name]
        d = cohen_d(rows_by[name], base_pnl) if base_pnl else 0.0
        ag = _agg(rows); og = _agg(oos)
        print(f"{name:18} {ag['hit6%']:>6} {ag['hit5+%']:>7} {ag['avg_cost']:>9} {ag['ROIproxy%']:>10} "
              f"[{ag['pnl_ci'][0]:>7.0f},{ag['pnl_ci'][1]:>8.0f}] | {og['hit6%']:>9} {d:>9.3f}")
    os.environ.pop("TJK_V9_FAV_AGF_THRESHOLD", None)
    os.environ.pop("TJK_V9_FAVYIKMA_MODE", None)


if __name__ == "__main__":
    main()
