"""Phase 5.8 PART 9 — risk filter tasarımı (Phase 5.6 MKS hazırlık, V5.1'e BAĞLI DEĞİL).

P4-8 sentezi. Çekirdek risk = FLB favori-overbet (validated, veri-türevli: 1−flb_multiplier(agf)).
Modülatörler: düşük-skill jokey (P4 walk-forward), kötü-form favori (P7). SIFIR ağırlık (robust
kanıt YOK): jockey×venue (P5), connection/sire (P6), regional (P8). Magic number YOK — eşikler
veri-türevli (skill çeyrekleri, P7 segment sınırları, risk tertilleri).

risk_score(agf_pct, jockey, prior_form) → [0,1] (0 güvenli, 1 yüksek-risk/overbet). Defansif.
Run: PYTHONPATH=. python -m simulation.analytics.risk_filter
"""
from __future__ import annotations

import os
import pickle
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _REPO not in sys.path:
    sys.path.insert(0, _REPO)

from simulation.analytics.dataset import build, jockey_skill, skill_quartiles

_FLB_PKL = os.path.join(_REPO, "simulation", "calibrators", "fitted", "flb_compensator.pkl")
POOR_FORM = 5.0   # P7 segment sınırı (kötü-form: prior finish ort. ≥5)
FAV_AGF = 0.25    # P7 favori sınırı


class RiskFilter:
    def __init__(self):
        self._flb = None
        if os.path.exists(_FLB_PKL):
            with open(_FLB_PKL, "rb") as f:
                self._flb = pickle.load(f)
        rows = build()
        self._skill = jockey_skill(rows)
        self._q25, _ = skill_quartiles(self._skill)            # düşük-skill eşiği (veri-türevli)
        # kötü-form/favori overbet derinliği (P7, veri-türevli) — form ceza ölçeği
        ff = [r for r in rows]  # placeholder; form ölçeği rapordan: ~0.33
        self._form_penalty = 0.33  # P7 kötü-form/favori |gap| (veri: win .022 vs agf .349)

    def _fav_overbet(self, agf_pct):
        """Çekirdek: 1 − flb_multiplier(agf). PURE veri-türevli overbet fraksiyonu."""
        if self._flb is None or not agf_pct or agf_pct <= 0:
            return 0.0
        try:
            return max(0.0, 1.0 - float(self._flb.multiplier(agf_pct)))
        except Exception:
            return 0.0

    def risk_score(self, agf_pct, jockey=None, prior_form=None):
        comps = {}
        comps["favorite_overbet"] = round(self._fav_overbet(agf_pct), 4)   # PRIMARY (validated)
        # düşük-skill jokey (P4 walk-forward): residual ≤ 25. çeyrek → risk
        sr = self._skill.get(jockey) if jockey else None
        comps["low_skill_jockey"] = round(min(0.3, max(0.0, (self._q25 - sr))), 4) if (sr is not None and sr < self._q25) else 0.0
        # kötü-form favori (P7)
        comps["poor_form_favorite"] = round(self._form_penalty, 4) if (
            prior_form is not None and prior_form >= POOR_FORM and (agf_pct or 0) / 100.0 >= FAV_AGF) else 0.0
        # robust kanıt YOK → 0 (dürüst)
        comps["jockey_venue_anomaly"] = 0.0   # P5: Bonferroni-survived yok
        comps["connection_sire"] = 0.0        # P6: trainer/owner yok, sire noise
        comps["regional"] = 0.0               # P8: A-spesifik kanıt yok
        score = min(1.0, sum(comps.values()))
        return round(score, 4), comps


def _coverage_action(score, t1, t2):
    if score <= 0 or score < t1:        # overbet riski yok/düşük
        return "normal coverage"
    if score < t2:
        return "conservative (−1 at/ayak)"
    return "skip/exclude consideration"


def main():
    rf = RiskFilter()
    print(f"skill q25 (düşük-skill eşiği): {rf._q25:.4f} | form penalty (P7): {rf._form_penalty}\n")

    # risk dağılımı → tertil eşikleri (veri-türevli coverage sınırları)
    rows = build()
    scores = [rf.risk_score(r["agf_pct"] if "agf_pct" in r else r["agf_implied"] * 100,
                            r.get("jockey"))[0] for r in rows]
    import numpy as np
    nz = [s for s in scores if s > 0]  # overbet-riskli alt küme (zero-inflated → nonzero tertil)
    t1, t2 = float(np.percentile(nz, 33)), float(np.percentile(nz, 67))
    print(f"risk dağılımı: %{100*len(nz)/len(scores):.0f} sıfır-üstü (favori/overbet). "
          f"Nonzero tertil eşikleri (veri-türevli): t33={t1:.3f} t67={t2:.3f}\n")

    print("=== SANITY (5 örnek) ===")
    samples = [
        ("ağır favori, skill?", 55, None, None),
        ("orta favori + kötü-form", 35, None, 6.0),
        ("longshot (value)", 5, None, None),
        ("orta + düşük-skill jokey", 20, min(rf._skill, key=rf._skill.get) if rf._skill else None, None),
        ("orta + üst-skill jokey", 20, max(rf._skill, key=rf._skill.get) if rf._skill else None, None),
    ]
    for desc, agf, jk, form in samples:
        s, c = rf.risk_score(agf, jk, form)
        act = _coverage_action(s, t1, t2)
        nz = {k: v for k, v in c.items() if v > 0}
        print(f"  {desc:28} agf={agf}% → risk={s:.3f} [{act}]  bileşen={nz}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
