"""BLOK 2 — tek-yarış bahis türleri (ganyan/plase/ikili/üçlü). Bitiş sırası (S) GERÇEK.
⚠ payout=PROXY: ganyan=1/agf_implied (flat-bet ROI=won/agf−1). plase/ikili/üçlü ROI murky→hit-rate.
Walk-forward (train ilk 20g / test son 10g) + bootstrap CI. Run: PYTHONPATH=. python -m simulation.alpha_hunt.blok2_bet_types
"""
from __future__ import annotations
import os, sys, warnings
warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)
from simulation.alpha_hunt.data import races, horse_rows, bootstrap_ci  # noqa: E402


def _roi(rows):
    """flat-bet ganyan ROI proxy = mean(won/agf_implied) − 1."""
    v = [r["won"] / r["agf_implied"] for r in rows if r["agf_implied"] > 0]
    return (sum(v) / len(v) - 1, bootstrap_ci([x - 1 for x in v])) if v else (0, (0, 0))


def main():
    hr = horse_rows()
    dates = sorted({r["date"] for r in hr})
    test = set(dates[-10:])
    print("PRE-REG: ganyan flat-bet ROI proxy (=won/agf−1) — subset'lerde OOS pozitif mi? CI-lower>0 aranır.")
    print("H0: piyasa kalibre → ROI≈0; FLB+ longshot value olabilir AMA varyans yüksek.\n")

    # GANYAN value subset'leri (AGF bucket + FLB sign)
    print("=== GANYAN flat-bet ROI proxy (subset, ALL vs OOS) ===")
    print(f"{'subset':24} {'n':>5} {'win%':>6} {'ROIproxy':>9} {'ROI 95%CI':>20} | {'OOS n':>5} {'OOS ROI':>8} {'OOS CI':>18}")
    subsets = {
        "ALL (her at)": lambda r: True,
        "favori agf>=40": lambda r: r["agf"] >= 40,
        "agf 20-40": lambda r: 20 <= r["agf"] < 40,
        "agf 10-20": lambda r: 10 <= r["agf"] < 20,
        "agf 5-10": lambda r: 5 <= r["agf"] < 10,
        "longshot agf<5 (FLB+)": lambda r: r["agf"] < 5,
        "FLB+ (flb>1.05)": lambda r: r["flb"] > 1.05,
        "FLB- (flb<0.95)": lambda r: r["flb"] < 0.95,
    }
    flags = []
    for name, fn in subsets.items():
        allr = [r for r in hr if fn(r)]
        oosr = [r for r in allr if r["date"] in test]
        if len(allr) < 20:
            print(f"{name:24} n<20 atla"); continue
        roi, ci = _roi(allr); oroi, oci = _roi(oosr) if len(oosr) >= 20 else (None, None)
        w = sum(r["won"] for r in allr) / len(allr)
        oos_str = f"{oroi*100:>7.0f}% [{oci[0]*100:>5.0f},{oci[1]*100:>5.0f}]" if oroi is not None else " n<20"
        print(f"{name:24} {len(allr):>5} {w*100:>5.1f}% {roi*100:>8.0f}% [{ci[0]*100:>5.0f},{ci[1]*100:>5.0f}] | "
              f"{len(oosr):>5} {oos_str}")
        if oroi is not None and oci[0] > 0:
            flags.append((name, oroi, oci))

    # PLASE / İKİLİ-SIRALI / ÜÇLÜ-SIRALI hit-rate (descriptive; AGF-rank picks)
    print("\n=== PLASE / İKİLİ-SIRALI / ÜÇLÜ-SIRALI (AGF-rank pick, hit-rate; payout proxy murky) ===")
    R = [r for r in races() if all(h.get("S") for h in r["horses"]) and len(r["horses"]) >= 4]
    plase_fav = ikili_s = uclu_s = ikili_box = n = 0
    for r in R:
        n += 1
        by_agf = sorted(r["horses"], key=lambda h: -h["agf"])
        order = {h["at_no"]: h["S"] for h in r["horses"]}
        fav = by_agf[0]["at_no"]
        if order.get(fav, 99) <= 3:
            plase_fav += 1
        top2 = [by_agf[0]["at_no"], by_agf[1]["at_no"]]
        if order.get(top2[0]) == 1 and order.get(top2[1]) == 2:
            ikili_s += 1
        if {order.get(top2[0]), order.get(top2[1])} == {1, 2}:
            ikili_box += 1
        top3 = [h["at_no"] for h in by_agf[:3]]
        if [order.get(x) for x in top3] == [1, 2, 3]:
            uclu_s += 1
    print(f"  n_race={n}")
    print(f"  PLASE (agf-favori top-3 bitti): {plase_fav}/{n} = {plase_fav/n*100:.1f}%")
    print(f"  İKİLİ SIRALI (agf top2 = 1.,2.): {ikili_s}/{n} = {ikili_s/n*100:.1f}%")
    print(f"  İKİLİ KUTU (agf top2 = ilk2 sırasız): {ikili_box}/{n} = {ikili_box/n*100:.1f}%")
    print(f"  ÜÇLÜ SIRALI (agf top3 = 1.,2.,3.): {uclu_s}/{n} = {uclu_s/n*100:.1f}%")
    print(f"\nFLAGGED (OOS CI-lower>0): {flags if flags else 'YOK'}")
    return flags


if __name__ == "__main__":
    main()
