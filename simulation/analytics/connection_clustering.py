"""Phase 5.8 PART 6 — connection clustering (L2 anomaly, INTERNAL).

⚠ DATA SINIRI: TJK sonuç sayfası TRAINER/OWNER İÇERMİYOR (Forma|S|At|Yaş|Orijin|Sıklet|Jokey).
Gerçek connection (antrenör/sahip stable pattern) bu veriyle TEST EDİLEMEZ. Mevcut tek lineage:
ORİJİN/baba (sire) → breeding-connection PROXY (zayıf; aynı baba = aynı yetiştirme hattı).
⚠ ETİK: istatistiksel, fixing değil, internal. Run: PYTHONPATH=. python -m simulation.analytics.connection_clustering
"""
from __future__ import annotations

import math
from collections import defaultdict

from scipy import stats

from simulation.analytics.dataset import build

MIN_N = 15


def _wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def main():
    rows = [r for r in build() if r.get("sire")]
    print(f"sire'li satır: {len(rows)} / toplam (trainer/owner YOK → sire breeding-proxy)\n")
    if not rows:
        print("⚠ sire verisi yok (rich re-scrape gerekli) → PART 6 skip.")
        return 0

    by_sire = defaultdict(list)
    for r in rows:
        by_sire[r["sire"]].append(r)
    tested = {s: v for s, v in by_sire.items() if len(v) >= MIN_N}
    n_tests = len(tested)
    alpha = 0.05 / max(1, n_tests)
    print(f"test edilen sire (n≥{MIN_N}): {n_tests} | Bonferroni α={alpha:.2e}")

    res = []
    for sire, rs in tested.items():
        n = len(rs); k = sum(x["won"] for x in rs)
        actual = k / n; expected = sum(x["agf_implied"] for x in rs) / n
        lo, hi = _wilson(k, n)
        p = float(stats.binomtest(k, n, expected).pvalue) if 0 < expected < 1 else 1.0
        res.append({"sire": sire, "n": n, "actual": round(actual, 3), "expected": round(expected, 3),
                    "gap": round(actual - expected, 4), "p": round(p, 4),
                    "flag": bool((hi < expected or lo > expected) and p < alpha)})
    res.sort(key=lambda x: x["gap"])
    n_flag = sum(1 for r in res if r["flag"])
    print(f"FLAGGED (Bonferroni): {n_flag}\n")

    print("=== EN UNDERPERFORM 8 sire (gap<0) ===")
    for r in res[:8]:
        print(f"  {r['sire'][:16]:16} n={r['n']:3} act={r['actual']:.3f} exp={r['expected']:.3f} "
              f"gap={r['gap']:+.3f} p={r['p']:.3f} {'🚩' if r['flag'] else ''}")
    print("=== EN OVERPERFORM 5 sire (gap>0) ===")
    for r in res[-5:]:
        print(f"  {r['sire'][:16]:16} n={r['n']:3} act={r['actual']:.3f} exp={r['expected']:.3f} "
              f"gap={r['gap']:+.3f} p={r['p']:.3f} {'🚩' if r['flag'] else ''}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
