"""Phase 5.5 PART B — FLBCompensator fit + sanity + monotonicity + save.

Run: PYTHONPATH=. python simulation/fit_flb_compensator.py
"""
from __future__ import annotations

import csv
import os
import pickle
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)

from simulation.calibrators.flb_compensator import FLBCompensator  # noqa: E402

DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
OUT = os.path.join(_REPO, "simulation", "calibrators", "fitted", "flb_compensator.pkl")


def _load():
    agf, won = [], []
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        try:
            agf.append(float(r["agf_pct"]))
            won.append(int(wf))
        except (ValueError, KeyError):
            continue
    return agf, won


def main():
    agf, won = _load()
    print(f"n={len(agf)}")
    fc = FLBCompensator().fit(agf, won)
    print(f"CV Brier: {fc._cv_brier}")
    print(f"seçilen smoothing: {fc._method}")
    print(f"clamp (bucket-corr extremleri): {fc._clamp}")

    # B.4 sanity
    print("\nSanity (multiplier yönü):")
    for a, exp in [(2, ">1.5 bonus"), (8, "~1"), (15, "~1"), (40, "<0.8 ceza"), (60, "<0.7 ceza")]:
        m = fc.multiplier(a)
        print(f"  AGF {a:>3}% → mult {m:.3f}  (beklenen {exp})")

    # B.5 monotonicity (Spearman: agf↑ → mult↓ beklenir)
    import numpy as np
    grid = list(range(1, 70))
    mults = [fc.multiplier(a) for a in grid]
    # Spearman = Pearson on ranks
    ar = np.argsort(np.argsort(grid)); mr = np.argsort(np.argsort(mults))
    sp = float(np.corrcoef(ar, mr)[0, 1])
    n_inc = sum(1 for i in range(1, len(mults)) if mults[i] > mults[i - 1] + 1e-9)
    print(f"\nMonotonicity: Spearman(agf,mult)={sp:.3f} (negatif=longshot bonus yönü); "
          f"artış-ihlali={n_inc}/{len(mults)-1}")

    # ASCII multiplier curve
    print("\nMultiplier eğrisi (AGF% → mult):")
    for a in [1, 3, 5, 8, 12, 18, 25, 35, 45, 60]:
        m = fc.multiplier(a)
        bar = "#" * int(m * 20)
        print(f"  {a:>3}% {m:.2f} {bar}")

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "wb") as f:
        pickle.dump(fc, f)
    print(f"\nsaved: {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
