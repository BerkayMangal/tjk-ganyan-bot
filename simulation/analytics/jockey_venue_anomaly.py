"""Phase 5.8 PART 5 — jockey×venue STATISTICAL anomaly (INTERNAL, defansif).

⚠⚠ ETİK: Bu İSTATİSTİKSEL sapma tespiti — FIXING KANITI DEĞİL. Küçük örnek/FLB/saha-gücü
masum açıklamalar. Telegram'a/public'e/TJK'ya GİTMEZ. Sadece coverage-avoidance sinyali.

Her (jokey, hipodrom) n≥10: actual win-rate vs market-expected (mean agf_implied). Wilson 95%
CI + Bonferroni (çoklu test). Underperform = market'in fazla değer biçtiği → AVOID. Regional χ².
Run: PYTHONPATH=. python -m simulation.analytics.jockey_venue_anomaly
"""
from __future__ import annotations

import json
import math
import os
from collections import defaultdict

from scipy import stats

from simulation.analytics.dataset import build, region_of

MIN_N = 10
_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
OUT_JSON = os.path.join(_REPO, "data", "backfill", "anomaly", "jockey_venue.json")


def _wilson(k, n, z=1.96):
    if n == 0:
        return (0.0, 0.0)
    p = k / n
    d = 1 + z * z / n
    c = (p + z * z / (2 * n)) / d
    h = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / d
    return (max(0.0, c - h), min(1.0, c + h))


def analyze():
    rows = [r for r in build() if r.get("jockey")]
    pairs = defaultdict(list)
    for r in rows:
        pairs[(r["jockey"], r["hip"])].append(r)
    tested = {k: v for k, v in pairs.items() if len(v) >= MIN_N}
    n_tests = len(tested)
    alpha_bonf = 0.05 / max(1, n_tests)

    results = []
    for (jk, hip), rs in tested.items():
        n = len(rs)
        k = sum(x["won"] for x in rs)
        actual = k / n
        expected = sum(x["agf_implied"] for x in rs) / n
        lo, hi = _wilson(k, n)
        se = math.sqrt(expected * (1 - expected) / n) if 0 < expected < 1 else 1e-9
        z = (expected - actual) / se          # >0 = underperform (market overrated)
        # iki-yönlü binom p (actual vs expected)
        p_two = float(stats.binomtest(k, n, expected).pvalue)
        results.append({"jockey": jk, "hippodrome": hip, "n": n, "wins": k,
                        "actual": round(actual, 3), "expected": round(expected, 3),
                        "wilson": [round(lo, 3), round(hi, 3)], "anomaly_z": round(z, 2),
                        "p": round(p_two, 5),
                        "flag_underperform": bool(hi < expected and p_two < alpha_bonf),
                        "flag_overperform": bool(lo > expected and p_two < alpha_bonf),
                        "region": region_of(hip)})
    results.sort(key=lambda x: -x["anomaly_z"])
    return results, n_tests, alpha_bonf


def main():
    results, n_tests, alpha = analyze()
    n_under = sum(1 for r in results if r["flag_underperform"])
    n_over = sum(1 for r in results if r["flag_overperform"])
    print(f"test edilen pair (n≥{MIN_N}): {n_tests} | Bonferroni α={alpha:.2e}")
    print(f"FLAGGED underperform: {n_under} | overperform: {n_over}\n")

    print("=== TOP 20 anomaly_z (underperform — market fazla değer biçti) ===")
    print("(⚠ istatistiksel; fixing değil. jokey adı maskeli: skill internal)")
    for i, r in enumerate(results[:20], 1):
        flag = "🚩BONF" if r["flag_underperform"] else ("~" if r["p"] < 0.05 else "")
        jk_mask = r["jockey"][:3] + "***"
        print(f"  {i:2}. {jk_mask:8}@{r['hippodrome']:10} n={r['n']:3} act={r['actual']:.3f} "
              f"exp={r['expected']:.3f} z={r['anomaly_z']:+.2f} p={r['p']:.4f} {flag}")

    # Regional concentration: region × flagged (under OR raw p<0.05)
    print("\n=== Regional concentration (χ²) ===")
    reg_counts = defaultdict(lambda: [0, 0])  # region: [flagged_or_p05, total]
    for r in results:
        reg = r["region"]
        reg_counts[reg][1] += 1
        if r["p"] < 0.05:
            reg_counts[reg][0] += 1
    table = []
    for reg in ("A_small", "B_big", "C_mid", "other"):
        if reg in reg_counts:
            fl, tot = reg_counts[reg]
            print(f"   {reg:9} p<.05: {fl}/{tot} ({fl/tot*100:.1f}%)")
            table.append([fl, tot - fl])
    if len(table) >= 2:
        chi2, p, _, _ = stats.chi2_contingency(table)
        print(f"   χ²={chi2:.3f} p={p:.4f} → {'ANLAMLI fark' if p < 0.05 else 'fark YOK (noise/uniform)'}")

    os.makedirs(os.path.dirname(OUT_JSON), exist_ok=True)
    with open(OUT_JSON, "w", encoding="utf-8") as f:
        json.dump({"n_tests": n_tests, "alpha_bonferroni": alpha, "results": results},
                  f, ensure_ascii=False, indent=1)
    print(f"\n[internal JSON] {OUT_JSON} (gitignored)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
