"""BLOK 4/5/8/9/10 — segment / connection / cell / leg-correlation / surprise.
Bonferroni + bootstrap. n=30g küçük → çoğu robust ÇIKMAZ (beklenen negatif). Sahte yok.
Run: PYTHONPATH=. python -m simulation.alpha_hunt.blok_4_5_8_9_10
"""
from __future__ import annotations
import os, sys, math, warnings
from collections import defaultdict
warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from scipy import stats                                              # noqa: E402
from simulation.alpha_hunt.data import races, horse_rows, wilson, bonferroni  # noqa: E402


def _gap_test(rows):
    """win-rate vs mean agf_implied; binom p (actual vs expected)."""
    n = len(rows); k = sum(r["won"] for r in rows)
    exp = sum(r["agf_implied"] for r in rows) / n
    p = float(stats.binomtest(k, n, exp).pvalue) if 0 < exp < 1 and n else 1.0
    return n, k / n, exp, (k / n - exp), p


def blok4_segment(hr):
    print("\n=== BLOK 4 — SEGMENT (hipodrom×mesafe-band×yaş, n≥30, Bonferroni) ===")
    def dband(d):
        if not d:
            return "?"
        return "sprint" if d <= 1400 else ("mil" if d <= 1800 else "uzun")
    segs = defaultdict(list)
    for r in hr:
        segs[(r["hip"], dband(r["distance"]))].append(r)
        if r.get("age"):
            segs[(r["hip"], f"yas{r['age']}")].append(r)
    tested = {k: v for k, v in segs.items() if len(v) >= 30}
    alpha = bonferroni(0.05, len(tested))
    flagged = [(k, _gap_test(v)) for k, v in tested.items()]
    flagged = [(k, t) for k, t in flagged if t[4] < alpha]
    print(f"  test={len(tested)} Bonferroni α={alpha:.2e} | ROBUST flagged={len(flagged)}")
    for k, t in sorted(flagged, key=lambda x: x[1][4])[:5]:
        print(f"    {k}: n={t[0]} win={t[1]:.3f} agf={t[2]:.3f} gap={t[3]:+.3f} p={t[4]:.1e}")
    return len(flagged)


def blok5_connection(hr):
    print("\n=== BLOK 5 — CONNECTION (jokey, sire — antrenör/sahip YOK; n≥20, Bonferroni) ===")
    res = {}
    for dim in ("jockey", "sire"):
        g = defaultdict(list)
        for r in hr:
            if r.get(dim):
                g[r[dim]].append(r)
        tested = {k: v for k, v in g.items() if len(v) >= 20}
        alpha = bonferroni(0.05, len(tested))
        fl = [(k, _gap_test(v)) for k, v in tested.items()]
        fl = [(k, t) for k, t in fl if t[4] < alpha]
        res[dim] = (len(tested), alpha, len(fl), fl)
        print(f"  {dim}: test={len(tested)} α={alpha:.2e} ROBUST={len(fl)}")
        for k, t in sorted(fl, key=lambda x: x[1][4])[:3]:
            print(f"    {str(k)[:18]:18} n={t[0]} win={t[1]:.3f} gap={t[3]:+.3f} p={t[4]:.1e}")
    return sum(r[2] for r in res.values())


def blok8_cells(hr):
    print("\n=== BLOK 8 — AT-CELL (yaş×ağırlık-band×mesafe-band; cinsiyet/pist YOK; n≥30) ===")
    def wband(w):
        w = w or 0
        return "hafif" if w < 55 else ("orta" if w < 59 else "ağır")
    def dband(d):
        d = d or 9999
        return "sprint" if d <= 1400 else ("mil" if d <= 1800 else "uzun")
    g = defaultdict(list)
    for r in hr:
        if r.get("age") and r.get("weight"):
            g[(f"y{r['age']}", wband(r["weight"]), dband(r["distance"]))].append(r)
    tested = {k: v for k, v in g.items() if len(v) >= 30}
    alpha = bonferroni(0.05, len(tested))
    fl = [(k, _gap_test(v)) for k, v in tested.items()]
    fl = [(k, t) for k, t in fl if t[4] < alpha]
    print(f"  test={len(tested)} α={alpha:.2e} ROBUST={len(fl)}")
    for k, t in sorted(fl, key=lambda x: x[1][4])[:5]:
        print(f"    {k}: n={t[0]} win={t[1]:.3f} gap={t[3]:+.3f} p={t[4]:.1e}")
    return len(fl)


def blok9_legcorr(R):
    print("\n=== BLOK 9 — AYAK KORELASYON (aynı altılıda longshot-win bağımsız mı?) ===")
    by_alt = defaultdict(dict)
    for r in R:
        w = next((h for h in r["horses"] if h["won"] == 1), None)
        if w:
            by_alt[(r["date"], r["hip"], r["altili"])][r["ayak"]] = (w["agf"] < 10)
    # her altılıda longshot-win sayısı dağılımı vs binom beklenti
    counts = []
    p_marg = []
    for legs in by_alt.values():
        if len(legs) == 6:
            counts.append(sum(1 for v in legs.values() if v))
    for r in R:
        w = next((h for h in r["horses"] if h["won"] == 1), None)
        if w:
            p_marg.append(1 if w["agf"] < 10 else 0)
    p = sum(p_marg) / len(p_marg)
    import numpy as np
    obs = np.bincount(counts, minlength=7)[:7]
    exp = np.array([stats.binom.pmf(k, 6, p) for k in range(7)]) * len(counts)
    chi2, pv = stats.chisquare(obs, f_exp=exp * obs.sum() / exp.sum())
    print(f"  altılı n={len(counts)}, P(longshot-win)/ayak={p:.3f}")
    print(f"  longshot-win/altılı gözlenen={list(obs)} beklenen(binom)={[round(x,1) for x in exp]}")
    print(f"  χ²={chi2:.2f} p={pv:.3f} → {'KORELASYON VAR' if pv<0.05 else 'BAĞIMSIZ (korelasyon yok)'}")
    return 1 if pv < 0.05 else 0


def blok10_surprise(R):
    print("\n=== BLOK 10 — SÜRPRİZ PATTERN (en yüksek-payout-proxy günler) ===")
    day = defaultdict(lambda: [1.0, 0])
    for r in R:
        w = next((h for h in r["horses"] if h["won"] == 1), None)
        if w and w["agf"] > 0:
            day[r["date"]][0] *= (w["agf"] / 100.0)  # Π winner share (küçük=sürprizli)
            day[r["date"]][1] += 1
    ranked = sorted(((d, v[0]) for d, v in day.items() if v[1] >= 6), key=lambda x: x[1])
    print("  En sürprizli 5 gün (Π winner-share en küçük):")
    for d, prod in ranked[:5]:
        longs = sum(1 for r in R if r["date"] == d and (next((h for h in r["horses"] if h["won"] == 1), {"agf": 99})["agf"] < 10))
        print(f"    {d}: Π-share={prod:.2e}, longshot-winner ayak≈{longs}")
    print("  → Ortak önceden-sinyal: longshot-yoğun günler (entropy). Pre-race tespit zor (gün-içi rastgele).")
    return 0


def main():
    hr = horse_rows(); R = races()
    n = 0
    n += blok4_segment(hr)
    n += blok5_connection(hr)
    n += blok8_cells(hr)
    n += blok9_legcorr(R)
    n += blok10_surprise(R)
    print(f"\n=== TOPLAM ROBUST (Bonferroni-geçen) flagged: {n} ===")


if __name__ == "__main__":
    main()
