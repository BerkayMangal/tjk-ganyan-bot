"""Phase 5.8 PART 8 — bölgesel deep-dive (Berkay hipotezi: Elazığ/Urfa/Diyarbakır).

Grup A (küçük) vs B (büyük) vs C (orta): AGF kalibrasyon, favori-overbet derinliği, residual
dağılımı (Kruskal-Wallis). Pool-size confound (avg agf = ters field-size proxy). ⚠ anomaly≠fixing.
Run: PYTHONPATH=. python -m simulation.analytics.regional_deep_dive
"""
from __future__ import annotations

from collections import defaultdict

from scipy import stats

from simulation.analytics.dataset import build, region_of


def _brier(rows):
    return sum((r["agf_implied"] - r["won"]) ** 2 for r in rows) / len(rows) if rows else 0


def main():
    rows = build()
    groups = defaultdict(list)
    for r in rows:
        groups[region_of(r["hip"])].append(r)

    print("=== Bölge grupları (residual = won − agf_implied) ===")
    print(f"{'grup':9} {'n':>5} {'mean_won':>9} {'mean_agf':>9} {'gap':>8} {'fav_gap≥.3':>11} "
          f"{'avg_agf(pool)':>13} {'Brier':>7}")
    resid_by = {}
    for g in ("A_small", "B_big", "C_mid"):
        rs = groups.get(g) or []
        if not rs:
            continue
        won = sum(x["won"] for x in rs) / len(rs)
        agf = sum(x["agf_implied"] for x in rs) / len(rs)
        fav = [x for x in rs if x["agf_implied"] >= 0.30]
        fav_gap = (sum(x["won"] for x in fav) / len(fav) - sum(x["agf_implied"] for x in fav) / len(fav)) if fav else 0
        resid_by[g] = [x["won"] - x["agf_implied"] for x in rs]
        print(f"{g:9} {len(rs):>5} {won:>9.3f} {agf:>9.3f} {won-agf:>+8.4f} {fav_gap:>+11.4f} "
              f"{agf:>13.4f} {_brier(rs):>7.4f}")

    # Kruskal-Wallis: residual dağılımları A/B/C farklı mı
    samples = [resid_by[g] for g in ("A_small", "B_big", "C_mid") if g in resid_by]
    if len(samples) >= 2:
        h, p = stats.kruskal(*samples)
        print(f"\nKruskal-Wallis (residual A/B/C): H={h:.3f} p={p:.4f} → "
              f"{'ANLAMLI fark' if p < 0.05 else 'fark YOK'}")

    # Favori-overbet derinliği A vs (B+C): Berkay hipotezi A daha overbet mi?
    favA = [x["won"] - x["agf_implied"] for x in groups.get("A_small", []) if x["agf_implied"] >= 0.30]
    favBC = [x["won"] - x["agf_implied"] for g in ("B_big", "C_mid") for x in groups.get(g, []) if x["agf_implied"] >= 0.30]
    if len(favA) >= 10 and len(favBC) >= 10:
        u, pf = stats.mannwhitneyu(favA, favBC, alternative="two-sided")
        mA = sum(favA) / len(favA); mBC = sum(favBC) / len(favBC)
        print(f"Favori-overbet A vs B+C: A_gap={mA:+.3f}(n={len(favA)}) vs BC_gap={mBC:+.3f}"
              f"(n={len(favBC)}) MW p={pf:.4f} → {'A daha overbet' if mA < mBC and pf < 0.05 else 'anlamlı fark yok'}")

    # Pool-size confound: avg_agf (ters field-size) — A küçük pool → yüksek avg_agf?
    print("\n=== Pool-size confound (avg_agf yüksek = küçük field = gürültülü) ===")
    for g in ("A_small", "B_big", "C_mid"):
        rs = groups.get(g) or []
        if rs:
            print(f"  {g}: avg_agf={sum(x['agf_implied'] for x in rs)/len(rs):.4f} (n={len(rs)})")
    print("⚠ A daha gürültülüyse 'anomali' noise olabilir — fixing değil.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
