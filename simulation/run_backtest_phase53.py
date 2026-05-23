"""Phase 5.3 PART B — full backtest (3 strateji × 2 prob + baseline'lar).

122 altılı (reconstructed snapshot). Metrikler:
- hit_rate / cost = GERÇEK (kazanan + combo·bf)
- proxy_payout / ROI = PROXY (pari-mutuel ters-olasılık; gerçek TJK ödeme tablosu YOK)
- 95% CI = bootstrap (1000 resample), n=122 küçük → geniş CI beklenir

Run: PYTHONPATH=. :dashboard python simulation/run_backtest_phase53.py
"""
from __future__ import annotations

import json
import os
import random
import sys
import warnings

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from simulation.altili_simulator import simulate_altili            # noqa: E402
from simulation.snapshot_builder import build_snapshots            # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy      # noqa: E402
from simulation.strategies.v7_strategy import v7_strategy          # noqa: E402
from simulation.strategies.smart_genis_strategy import smart_genis_strategy  # noqa: E402

BF = 1.25  # baseline birim fiyat (büyük hipodrom varsayımı)


def _baseline_topn(n):
    def fn(result):
        legs_selected = []
        for ls in result.get("legs_summary", []) or []:
            hs = sorted(ls.get("all_horses_with_mp", []) or [],
                        key=lambda h: -(h.get("agf_pct") or 0))
            legs_selected.append([h.get("number") for h in hs[:n]])
        combo = 1
        for s in legs_selected:
            combo *= max(1, len(s))
        return {"name": f"fav_top{n}", "legs_selected": legs_selected,
                "combo": combo, "cost": round(combo * BF, 2)}
    fn.__name__ = f"fav_top{n}"
    return fn


def _baseline_random(n, seed=42):
    rng = random.Random(seed)

    def fn(result):
        legs_selected = []
        for ls in result.get("legs_summary", []) or []:
            nums = [h.get("number") for h in (ls.get("all_horses_with_mp") or [])]
            k = min(n, len(nums))
            legs_selected.append(rng.sample(nums, k) if nums else [])
        combo = 1
        for s in legs_selected:
            combo *= max(1, len(s))
        return {"name": f"random{n}", "legs_selected": legs_selected,
                "combo": combo, "cost": round(combo * BF, 2)}
    fn.__name__ = f"random{n}"
    return fn


def _bootstrap_ci(per_altili, n_boot=1000, seed=7):
    """per_altili: [(cost, payout)] → ROI bootstrap %95 CI."""
    rng = random.Random(seed)
    m = len(per_altili)
    if m == 0:
        return (0.0, 0.0)
    rois = []
    for _ in range(n_boot):
        sample = [per_altili[rng.randrange(m)] for _ in range(m)]
        c = sum(x[0] for x in sample)
        p = sum(x[1] for x in sample)
        rois.append(((p - c) / c) if c > 0 else 0.0)
    rois.sort()
    lo = rois[int(0.025 * n_boot)]
    hi = rois[int(0.975 * n_boot)]
    return (round(lo * 100, 1), round(hi * 100, 1))


def _run_one(snaps, fn, prob_field="model_prob"):
    per = []          # (cost, payout)
    hits = 0
    partials = []
    costs = []
    cum = 0.0
    peak = 0.0
    max_dd = 0.0
    for s in snaps:
        o = simulate_altili(s["result"], s["actual_results"], fn, unit_price=BF,
                            prob_field=prob_field)
        cost = o["cost"]
        payout = o["payout"]
        per.append((cost, payout))
        costs.append(cost)
        partials.append(o["partial_hits"])
        if o["hit"]:
            hits += 1
        cum += (payout - cost)
        peak = max(peak, cum)
        max_dd = max(max_dd, peak - cum)
    n = len(snaps)
    tot_cost = sum(costs)
    tot_pay = sum(p for _, p in per)
    roi = ((tot_pay - tot_cost) / tot_cost * 100) if tot_cost > 0 else 0.0
    ci = _bootstrap_ci(per)
    return {
        "n": n, "n_hit": hits, "hit_rate": round(hits / n, 4) if n else 0,
        "avg_partial": round(sum(partials) / n, 2) if n else 0,
        "total_cost": round(tot_cost, 1), "avg_cost": round(tot_cost / n, 1) if n else 0,
        "total_payout_proxy": round(tot_pay, 1),
        "roi_proxy_pct": round(roi, 1), "roi_ci95": ci,
        "max_drawdown_proxy": round(max_dd, 1),
    }


def main():
    snaps_raw = build_snapshots("raw")
    snaps_cal = build_snapshots("calibrated")
    print(f"N altılı: raw={len(snaps_raw)} calibrated={len(snaps_cal)}\n")

    strategies = [("V5.1_dar", v5_1_strategy), ("V7", v7_strategy),
                  ("smart_genis", smart_genis_strategy)]
    out = {"n": len(snaps_raw), "strategies": {}, "baselines": {}}

    for label, fn in strategies:
        out["strategies"][f"{label}|raw"] = _run_one(snaps_raw, fn, "model_prob")
        out["strategies"][f"{label}|calibrated"] = _run_one(snaps_cal, fn, "calibrated_prob")

    for label, fn in [("fav_top1", _baseline_topn(1)), ("fav_top2", _baseline_topn(2)),
                      ("random2", _baseline_random(2))]:
        out["baselines"][label] = _run_one(snaps_raw, fn)

    print(json.dumps(out, ensure_ascii=False, indent=1))
    with open(os.path.join(_REPO, "data", "backfill", "phase_5_3_backtest_results.json"),
              "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
