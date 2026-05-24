"""Phase 5.8 PART 7 — form vs AGF mismatch (L3 anomaly).

Pencere-içi form (isimle takip, prior finish S ortalaması) vs AGF. Mismatch = market "biliyor"
mu yoksa form mu haklı? ⚠ H3 (Phase 5.5) recency confound'una benzer (kısa pencere seçilim) →
DİKKATLİ. Run: PYTHONPATH=. python -m simulation.analytics.form_agf_mismatch
"""
from __future__ import annotations

from collections import defaultdict

from simulation.analytics.dataset import build, gap, roi_proxy


def _attach_form(rows):
    """Her ata pencere-içi prior_form (önceki S ortalaması) + prior_n ekle."""
    by_name = defaultdict(list)
    for r in sorted(rows, key=lambda x: x["date"]):
        if r.get("name"):
            by_name[r["name"]].append(r)
    out = []
    for name, apps in by_name.items():
        prior_S = []
        for r in apps:
            r = dict(r)
            r["prior_form"] = (sum(prior_S) / len(prior_S)) if prior_S else None
            r["prior_n"] = len(prior_S)
            out.append(r)
            if r.get("S"):
                prior_S.append(r["S"])
    return out


def _cell(rows, name):
    if len(rows) < 15:
        return f"{name}: n={len(rows)} (<15, atla)"
    return (f"{name}: n={len(rows):4} win={sum(x['won'] for x in rows)/len(rows):.3f} "
            f"agf={sum(x['agf_implied'] for x in rows)/len(rows):.3f} gap={gap(rows):+.4f} "
            f"ROIproxy={roi_proxy(rows):+.3f}")


def main():
    rows = [r for r in _attach_form(build()) if r.get("prior_form") is not None]
    print(f"prior_form'lu satır (pencere-içi 2+ koşu): {len(rows)}\n")

    # form sınıfı: iyi (prior_form≤3, top3 ort) / kötü (prior_form≥5)
    hi_form = [r for r in rows if r["prior_form"] <= 3]
    lo_form = [r for r in rows if r["prior_form"] >= 5]
    print("=== FORM × AGF mismatch ===")
    print(" [iyi-form ≤3]      ", _cell(hi_form, "tüm"))
    print("   iyi-form + düşük-AGF(<.10):", _cell([r for r in hi_form if r["agf_implied"] < .10], "x"))
    print("   iyi-form + favori(≥.25)   :", _cell([r for r in hi_form if r["agf_implied"] >= .25], "x"))
    print(" [kötü-form ≥5]     ", _cell(lo_form, "tüm"))
    print("   kötü-form + favori(≥.25)  :", _cell([r for r in lo_form if r["agf_implied"] >= .25], "x"))
    print("   kötü-form + düşük-AGF(<.10):", _cell([r for r in lo_form if r["agf_implied"] < .10], "x"))

    # Asimetri: form ve AGF disagree → kim haklı?
    # disagree-A: iyi-form ama düşük-AGF → form haklıysa win yüksek olmalı
    # disagree-B: kötü-form ama favori → market haklıysa win yüksek
    dA = [r for r in hi_form if r["agf_implied"] < .15]
    dB = [r for r in lo_form if r["agf_implied"] >= .20]
    print("\n=== ASİMETRİ (form vs market disagree) ===")
    if len(dA) >= 15:
        wr = sum(x["won"] for x in dA) / len(dA); ag = sum(x["agf_implied"] for x in dA) / len(dA)
        print(f"  A: iyi-form/düşük-AGF n={len(dA)} win={wr:.3f} vs agf={ag:.3f} → "
              f"{'FORM haklı (win>agf)' if wr > ag else 'MARKET haklı (win≤agf)'}")
    if len(dB) >= 15:
        wr = sum(x["won"] for x in dB) / len(dB); ag = sum(x["agf_implied"] for x in dB) / len(dB)
        print(f"  B: kötü-form/favori n={len(dB)} win={wr:.3f} vs agf={ag:.3f} → "
              f"{'MARKET fazla güveniyor (win<agf, OVERBET)' if wr < ag else 'MARKET haklı'}")
    print("\n⚠ CAVEAT: pencere-içi form = H3 recency confound riski (seçilim/zayıf saha). Korelasyonel.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
