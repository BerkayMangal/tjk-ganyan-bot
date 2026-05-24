"""Phase 5.5 PART D — backtest V5.1 raw vs FLB-compensated (paired, n=122).

⚠ payout = PROXY (gerçek TJK dividend yok) → ROI/pnl mutlak anlamsız, RELATIVE karşılaştırma.
⚠ fallback rejimi (score≈agf) → comp_score = calibre-winrate. Prod (score=model_prob) farklı.
Run: PYTHONPATH=.:dashboard python simulation/backtest_flb_phase55.py
"""
from __future__ import annotations

import os
import random
import sys
import warnings

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import numpy as np                                                  # noqa: E402
from scipy import stats                                            # noqa: E402
from simulation.altili_simulator import simulate_altili            # noqa: E402
from simulation.snapshot_builder import build_snapshots            # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy      # noqa: E402

BF = 1.25


def _run(snaps, active):
    os.environ["TJK_FLB_ACTIVE"] = "1" if active else "0"
    rows = []
    for s in snaps:
        o = simulate_altili(s["result"], s["actual_results"], v5_1_strategy, unit_price=BF)
        rows.append({"cost": o["cost"], "payout": o["payout"], "hit": int(o["hit"]),
                     "pnl": o["payout"] - o["cost"], "partial": o["partial_hits"]})
    os.environ["TJK_FLB_ACTIVE"] = "0"
    return rows


def _agg(rows):
    n = len(rows)
    tc = sum(r["cost"] for r in rows)
    tp = sum(r["payout"] for r in rows)
    hits = sum(r["hit"] for r in rows)
    return {"n": n, "hit": hits, "hit_rate": round(hits / n, 4),
            "avg_cost": round(tc / n, 1), "roi_proxy_pct": round((tp - tc) / tc * 100, 1) if tc else 0,
            "cost_per_hit": round(tc / hits, 0) if hits else None}


def _bootstrap_ci(rows, n_boot=1000, seed=7):
    rng = random.Random(seed)
    m = len(rows)
    rois = []
    for _ in range(n_boot):
        samp = [rows[rng.randrange(m)] for _ in range(m)]
        c = sum(x["cost"] for x in samp); p = sum(x["payout"] for x in samp)
        rois.append((p - c) / c * 100 if c else 0)
    rois.sort()
    return (round(rois[25], 1), round(rois[975], 1))


def main():
    snaps = build_snapshots("raw")
    raw = _run(snaps, False)
    comp = _run(snaps, True)
    print(f"N={len(snaps)}\n")
    print("RAW :", _agg(raw), "CI", _bootstrap_ci(raw))
    print("COMP:", _agg(comp), "CI", _bootstrap_ci(comp))

    # Paired (proxy pnl)
    d_raw = np.array([r["pnl"] for r in raw])
    d_comp = np.array([r["pnl"] for r in comp])
    diff = d_comp - d_raw
    t_t, t_p = stats.ttest_rel(d_comp, d_raw)
    nz = diff[diff != 0]
    if len(nz) > 0:
        w_s, w_p = stats.wilcoxon(nz)
    else:
        w_s, w_p = float("nan"), 1.0
    cohen_d = float(diff.mean() / diff.std(ddof=1)) if diff.std(ddof=1) > 0 else 0.0
    print(f"\nPaired pnl (comp−raw): mean_diff={diff.mean():.1f}")
    print(f"  t-test  t={t_t:.3f} p={t_p:.4f}")
    print(f"  Wilcoxon W={w_s:.1f} p={w_p:.4f} (n_nonzero={len(nz)})")
    print(f"  Cohen's d={cohen_d:.3f}")

    # Paired hit (McNemar-ish)
    print(f"\nHit: raw={sum(r['hit'] for r in raw)} comp={sum(r['hit'] for r in comp)}")

    # Stratify: surprise-heavy (>=2 longshot winners AGF<10) vs not
    surp_idx = []
    for i, s in enumerate(snaps):
        nlong = 0
        for ayak in range(6):
            w = s["actual_results"][ayak]
            ah = {h["number"]: h["agf_pct"] for h in s["result"]["legs_summary"][ayak]["all_horses_with_mp"]}
            if ah.get(w, 100) < 10:
                nlong += 1
        surp_idx.append(nlong >= 2)
    for label, mask in [("surprise-heavy (≥2 longshot winner)", surp_idx),
                        ("favori-heavy (<2)", [not x for x in surp_idx])]:
        idx = [i for i, m in enumerate(mask) if m]
        if not idx:
            continue
        rh = sum(raw[i]["hit"] for i in idx); ch = sum(comp[i]["hit"] for i in idx)
        rp = sum(raw[i]["pnl"] for i in idx); cp = sum(comp[i]["pnl"] for i in idx)
        print(f"\n  [{label}] n={len(idx)}  hit raw={rh} comp={ch}  pnl_proxy raw={rp:.0f} comp={cp:.0f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
