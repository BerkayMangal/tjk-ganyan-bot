"""Phase 5.3 — AGF backfill → prod-şekilli `result` snapshot reconstructor.

calibration_dataset_complete.csv (date,hippodrome,altili_no,ayak,at_no,agf_pct,
agf_implied_prob,won_flag) → her altılı için yerli_engine `result` snapshot'ı +
actual_results (kazanan at_no/ayak). 3 strateji (V5.1/V7/smart_genis) bunu tüketir.

⚠ DÜRÜSTLÜK SINIRI: tarihsel `model_prob` YOK (replay OOD, Phase 5.2). Bu yüzden:
- prob_mode="raw":        model_prob = agf_pct (value_edge=0 → value sinyali yok)
- prob_mode="calibrated": model_prob = isotonic(agf_implied)·100 (FLB-value sinyali enjekte)
Bu replay STRATEJİ-YAPISI (genişlik/coverage) ölçer, prod-modelin value-edge'ini DEĞİL.
"""
from __future__ import annotations

import csv
import os
import pickle
from collections import defaultdict, OrderedDict

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATASET = os.path.join(_REPO, "data", "backfill", "calibration_dataset_complete.csv")
PKL = os.path.join(_REPO, "simulation", "calibrators", "fitted", "agf_outcome_calibrator.pkl")


def _load_calibrator():
    if not os.path.exists(PKL):
        return None
    with open(PKL, "rb") as f:
        return pickle.load(f).get("model")


def _load_rows():
    rows = []
    for r in csv.DictReader(open(DATASET, encoding="utf-8")):
        wf = (r.get("won_flag") or "").strip()
        try:
            rows.append({
                "date": r["date"], "hippodrome": r["hippodrome"],
                "altili_no": r["altili_no"], "ayak": int(r["ayak"]),
                "at_no": int(r["at_no"]), "agf_pct": float(r["agf_pct"]),
                "agf_implied": float(r["agf_implied_prob"]),
                "won": (1 if wf == "1" else (0 if wf == "0" else None)),
            })
        except (ValueError, KeyError):
            continue
    return rows


def _horse(at_no, agf_pct, model_prob_pct):
    """all_horses_with_mp öğesi (prod şeması: name/number/score/agf_pct/model_prob/value_edge)."""
    return {
        "name": f"at_{at_no}",
        "number": at_no,
        "score": round(model_prob_pct / 100.0, 4),  # ranking — agf'de monoton
        "agf_pct": round(agf_pct, 2),
        "model_prob": round(model_prob_pct, 1),
        "value_edge": round(model_prob_pct - agf_pct, 1),
    }


def build_snapshots(prob_mode: str = "raw") -> list:
    """[{result, actual_results, key}] — tüm 6 ayağı etiketli altılılar.

    prob_mode: "raw" (model_prob=agf_pct) | "calibrated" (isotonic(agf_implied)·100).
    """
    calib = _load_calibrator() if prob_mode == "calibrated" else None
    rows = _load_rows()

    # (date,hip,altili) → {ayak → [row...]}
    altilis: dict = defaultdict(lambda: defaultdict(list))
    for r in rows:
        altilis[(r["date"], r["hippodrome"], r["altili_no"])][r["ayak"]].append(r)

    out = []
    for (date, hip, altili_no), ayaklar in altilis.items():
        if len(ayaklar) < 6 or any(ayaklar[a][0]["won"] is None for a in ayaklar if ayaklar[a]):
            continue
        if not all(a in ayaklar for a in range(1, 7)):
            continue

        legs_summary = []
        actual_results = []
        ok = True
        for ayak in range(1, 7):
            horses_raw = ayaklar[ayak]
            winner = next((h["at_no"] for h in horses_raw if h["won"] == 1), None)
            if winner is None:
                ok = False
                break
            actual_results.append(winner)

            horses = []
            for h in horses_raw:
                if prob_mode == "calibrated" and calib is not None:
                    mp = float(calib.predict([h["agf_implied"]])[0]) * 100.0
                else:
                    mp = h["agf_pct"]
                horses.append(_horse(h["at_no"], h["agf_pct"], mp))
            horses.sort(key=lambda x: -x["model_prob"])

            legs_summary.append({
                "ayak": ayak, "race_number": ayak,
                "n_runners": len(horses), "has_model": True,
                "confidence": 0, "agreement": 0.5,
                "leg_type": "", "breed": "", "distance": "",
                "top3": horses[:3],
                "all_horses_with_mp": horses,
            })
        if not ok:
            continue

        result = {
            "hippodrome": hip, "altili_no": altili_no, "date": date,
            "data_quality_status": "OK", "agf_missing": False,
            "legs_summary": legs_summary,
        }
        out.append({"result": result, "actual_results": actual_results,
                    "key": (date, hip, altili_no)})
    return out


if __name__ == "__main__":
    for mode in ("raw", "calibrated"):
        snaps = build_snapshots(mode)
        n_full = sum(1 for s in snaps if None not in s["actual_results"])
        print(f"{mode}: {len(snaps)} altılı, tam-sonuçlu {n_full}, "
              f"örnek actual={snaps[0]['actual_results'] if snaps else '-'}")
