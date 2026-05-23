"""Phase 5.8 PART 4 — niş edge matrisi (bias × bias kesişimi).

skill × yaş × mesafe × hipodrom hücreleri → ROI proxy + gap. Min n=20. Top niş'ler value/avoid.
⚠ ROI = implied-odds PROXY (gerçek odds/takeout yok). Run: PYTHONPATH=. python -m simulation.analytics.niche_edge_matrix
"""
from __future__ import annotations

import math
from collections import defaultdict

from simulation.analytics.dataset import (build, gap, jockey_skill, roi_proxy,
                                          skill_quartiles)

MIN_N = 20


def _tag(rows):
    sk = jockey_skill(rows)
    lo, hi = skill_quartiles(sk)
    out = []
    for r in rows:
        s = sk.get(r.get("jockey"))
        skill = "skill?" if s is None else ("skillHI" if s >= hi else ("skillLO" if s <= lo else "skillMID"))
        age = "yaş?" if not r.get("age") else ("genç" if r["age"] <= 4 else "yaşlı")
        dist = "mesafe?" if not r.get("distance") else ("sprint" if r["distance"] <= 1400 else "route")
        out.append({**r, "_skill": skill, "_age": age, "_dist": dist})
    return out


def _cells(rows, keyfn):
    g = defaultdict(list)
    for r in rows:
        g[keyfn(r)].append(r)
    res = []
    for k, rs in g.items():
        if len(rs) < MIN_N:
            continue
        res.append({"cell": k, "n": len(rs), "win": round(sum(x["won"] for x in rs) / len(rs), 3),
                    "agf": round(sum(x["agf_implied"] for x in rs) / len(rs), 3),
                    "gap": round(gap(rs), 4), "roi_proxy": round(roi_proxy(rs), 4)})
    return res


def _walk_forward_skill(rows):
    """Circularity kontrolü: skill TRAIN'den (ilk yarı, tarih), ROI TEST'te (ikinci yarı).
    In-sample leakage'ı kaldırır — gerçek tradeable edge mi?"""
    srt = sorted([r for r in rows if r.get("jockey")], key=lambda x: x["date"])
    cut = len(srt) // 2
    train, test = srt[:cut], srt[cut:]
    sk = jockey_skill(train)
    lo, hi = skill_quartiles(sk)
    tiers = defaultdict(list)
    for r in test:
        s = sk.get(r["jockey"])
        if s is None:
            tier = "yeni(train'de yok)"
        elif s >= hi:
            tier = "skillHI"
        elif s <= lo:
            tier = "skillLO"
        else:
            tier = "skillMID"
        tiers[tier].append(r)
    print("\n=== WALK-FORWARD skill (TRAIN→TEST, circularity-free) ===")
    for t in ("skillHI", "skillMID", "skillLO", "yeni(train'de yok)"):
        rs = tiers.get(t) or []
        if len(rs) < MIN_N:
            print(f"   {t:20} n={len(rs)} (n<{MIN_N}, atla)")
            continue
        print(f"   {t:20} n={len(rs):5} win={sum(x['won'] for x in rs)/len(rs):.3f} "
              f"gap={gap(rs):+.4f} ROIproxy={roi_proxy(rs):+.4f}")


def main():
    rows = _tag(build())
    print(f"n={len(rows)} (tagged)\n")
    _walk_forward_skill(rows)
    print()

    # 1-D marjinaller (yorumlanabilirlik)
    print("=== MARJİNAL (1-D) ===")
    for dim, kf in [("skill", lambda r: r["_skill"]), ("yaş", lambda r: r["_age"]),
                    ("mesafe", lambda r: r["_dist"]), ("hipodrom", lambda r: r["hip"])]:
        print(f"-- {dim} --")
        for c in sorted(_cells(rows, kf), key=lambda x: -x["roi_proxy"]):
            print(f"   {str(c['cell']):14} n={c['n']:5} win={c['win']:.3f} agf={c['agf']:.3f} "
                  f"gap={c['gap']:+.4f} ROIproxy={c['roi_proxy']:+.4f}")

    # 4-D kesişim
    cells = _cells(rows, lambda r: (r["_skill"], r["_age"], r["_dist"], r["hip"]))
    # skor = |ROI| × sqrt(n) (etki × güven)
    for c in cells:
        c["score"] = abs(c["roi_proxy"]) * math.sqrt(c["n"])
    cells.sort(key=lambda x: -x["score"])
    print(f"\n=== TOP 20 NİŞ (4-D, |ROI|×√n) — n≥{MIN_N} ===")
    print("VALUE (ROI>0, underbet) ↑ / AVOID (ROI<0, overbet) ↓")
    for c in cells[:20]:
        tag = "VALUE" if c["roi_proxy"] > 0 else "AVOID"
        print(f"  [{tag}] {str(c['cell']):42} n={c['n']:4} gap={c['gap']:+.3f} ROIproxy={c['roi_proxy']:+.3f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
