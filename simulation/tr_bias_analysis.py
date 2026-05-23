"""Phase 5.5 PART E — TR public-bias hipotez testleri.

Zengin outcome (age/weight/jockey/distance) + AGF dataset → her hipotez için grup-split +
residual (won − agf_implied) Mann-Whitney. Overbet = residual<0 (gerçek < piyasa).
H1(TV)/H5(gender) veri YOK → skip. H2(jockey)/H3(recency)/H4(age)/H6(distance) test edilir.
Run: PYTHONPATH=. python simulation/tr_bias_analysis.py
"""
from __future__ import annotations

import csv
import glob
import json
import os
from collections import defaultdict

import numpy as np
from scipy import stats

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
RICH = os.path.join(_REPO, "data", "backfill", "outcomes_rich")
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
_FOLD = str.maketrans("İıÇçĞğÖöŞşÜü", "iiccggoossuu")


def _norm(s):
    return (s or "").strip().translate(_FOLD).lower()


def _load_rich():
    """{(date,norm_hip): {kosu_no: {distance, by_at:{at_no: feat}}}}"""
    out = {}
    for p in glob.glob(os.path.join(RICH, "*.json")):
        day = json.load(open(p, encoding="utf-8"))
        for h in day.get("hippodromes", []):
            kos = {}
            for kno, info in h.get("kosular", {}).items():
                by_at = {f["at_no"]: f for f in info.get("finishers", [])}
                kos[int(kno)] = {"distance": info.get("distance"),
                                 "at_set": set(by_at), "by_at": by_at}
            out[(day["date"], _norm(h["hippodrome"]))] = kos
    return out


def _build_enriched():
    rich = _load_rich()
    rows = list(csv.DictReader(open(DATASET, encoding="utf-8")))
    # ayak grupları
    legs = defaultdict(list)
    for r in rows:
        wf = (r.get("won_flag") or "").strip()
        if wf not in ("0", "1"):
            continue
        legs[(r["date"], r["hippodrome"], r["altili_no"], r["ayak"])].append(
            {"at_no": int(r["at_no"]), "agf_implied": float(r["agf_implied_prob"]), "won": int(wf)})

    enriched = []
    for (date, hip, _, _), horses in legs.items():
        kosular = rich.get((date, _norm(hip)))
        if not kosular:
            continue
        at_set = {h["at_no"] for h in horses}
        # best-Jaccard koşu
        best, best_s = None, 0.0
        for kno, info in kosular.items():
            inter = len(at_set & info["at_set"]); union = len(at_set | info["at_set"])
            s = inter / union if union else 0
            if s > best_s:
                best, best_s = info, s
        if not best or best_s < 0.5:
            continue
        for h in horses:
            feat = best["by_at"].get(h["at_no"])
            if not feat:
                continue
            enriched.append({**h, "date": date, "hip": _norm(hip),
                             "age": feat.get("age"), "weight": feat.get("weight"),
                             "jockey": feat.get("jockey"), "name": feat.get("name"),
                             "distance": best.get("distance")})
    return enriched


def _resid(rows):
    return np.array([r["won"] - r["agf_implied"] for r in rows])


def _test(name, group_a, group_b, label_a, label_b):
    """Mann-Whitney on residual + group gap (overall + favori subset)."""
    def desc(g):
        if not g:
            return "n=0"
        won = np.mean([r["won"] for r in g]); agf = np.mean([r["agf_implied"] for r in g])
        return f"n={len(g)} won={won:.3f} agf={agf:.3f} gap={won-agf:+.3f}"
    ra, rb = _resid(group_a), _resid(group_b)
    if len(ra) < 10 or len(rb) < 10:
        return {"name": name, "skip": "n<10"}
    u, p = stats.mannwhitneyu(ra, rb, alternative="two-sided")
    # favori subset (agf>=0.25)
    fa = [r for r in group_a if r["agf_implied"] >= 0.25]
    fb = [r for r in group_b if r["agf_implied"] >= 0.25]
    fav_p = None
    if len(fa) >= 10 and len(fb) >= 10:
        _, fav_p = stats.mannwhitneyu(_resid(fa), _resid(fb), alternative="two-sided")
    return {"name": name, "a": f"{label_a}: {desc(group_a)}", "b": f"{label_b}: {desc(group_b)}",
            "mw_p": round(float(p), 4), "fav_mw_p": round(float(fav_p), 4) if fav_p is not None else None,
            "fav_a": desc(fa), "fav_b": desc(fb)}


def main():
    e = _build_enriched()
    print(f"enriched rows: {len(e)} (feature-matched)\n")
    n_age = sum(1 for r in e if r["age"]); n_jk = sum(1 for r in e if r["jockey"])
    n_dist = sum(1 for r in e if r["distance"])
    print(f"availability: age={n_age} jockey={n_jk} distance={n_dist}\n")

    results = []
    # H4 age: genç(≤4) vs yaşlı(≥5)
    young = [r for r in e if r["age"] and r["age"] <= 4]
    old = [r for r in e if r["age"] and r["age"] >= 5]
    results.append(_test("H4 yaş (genç≤4 vs yaşlı≥5)", young, old, "genç", "yaşlı"))

    # H6 distance: sprint(≤1400) vs route(>1400)
    sprint = [r for r in e if r["distance"] and r["distance"] <= 1400]
    route = [r for r in e if r["distance"] and r["distance"] > 1400]
    results.append(_test("H6 mesafe (sprint≤1400 vs route>1400)", sprint, route, "sprint", "route"))

    # H2 jockey popularity: top-10 sık jokey vs rest
    freq = defaultdict(int)
    for r in e:
        if r["jockey"]:
            freq[r["jockey"]] += 1
    top = {j for j, _ in sorted(freq.items(), key=lambda x: -x[1])[:10]}
    pop = [r for r in e if r["jockey"] in top]
    rest = [r for r in e if r["jockey"] and r["jockey"] not in top]
    results.append(_test("H2 jokey (top-10 popüler vs diğer)", pop, rest, "popüler", "diğer"))

    # H3 recency: önceki görünümünde kazandı vs kazanmadı (isimle takip)
    by_name = defaultdict(list)
    for r in sorted(e, key=lambda x: x["date"]):
        if r["name"]:
            by_name[r["name"]].append(r)
    prev_won, prev_lost = [], []
    for name, apps in by_name.items():
        for i in range(1, len(apps)):
            (prev_won if apps[i - 1]["won"] == 1 else prev_lost).append(apps[i])
    results.append(_test("H3 recency (önceki koşuda kazandı vs kazanmadı)", prev_won, prev_lost,
                         "önce-kazandı", "önce-kaybetti"))

    for r in results:
        print(json.dumps(r, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
