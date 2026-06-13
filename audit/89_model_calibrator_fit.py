"""Model_prob → outcome kalibrasyonu — bet_diary forward fit (Phase 5.2.6 sürümü).

Phase 1E.2 outcome update bug fix sonrası (commit 196898d): bet_diary'de 810
gerçek did_we_win çifti birikti. Bu script audit/87'deki grid'i bet_diary
verisiyle koşar, walk-forward kalibratör fit eder, active.pkl yazar.

Önemli farklar vs audit/87:
  - did_we_win'i bet_diary'den DİREKT okur (audit/87 build_bet_diary_joined'in
    race_no↔ayak join'i hatalıydı: outcomes TJK koşu no, bet_diary ayak no).
  - Walk-forward 3-fold (n=810 küçük; 5 olursa fold başına n_train<200).
  - Tüm calibrator class'ları simulation/calibrators/'tan import (prod-import-safe pkl).

Çıktı:
  - simulation/calibrators/fitted/active.pkl (dict: kind, method, model, n_train, metrics)
  - audit/reports/phase_5_2_6_model_fit_report.md
"""
from __future__ import annotations

import json
import os
import pickle
import sys
from datetime import datetime

import numpy as np
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _REPO)
sys.path.insert(0, os.path.join(_REPO, "simulation"))
from simulation.calibrators.beta import BetaCalibrator  # noqa: E402

BET_DIARY = os.path.join(_REPO, "audit", "reports", "bet_diary_log.jsonl")
FITTED_DIR = os.path.join(_REPO, "simulation", "calibrators", "fitted")
ACTIVE = os.path.join(FITTED_DIR, "active.pkl")
REPORT = os.path.join(_REPO, "audit", "reports", "phase_5_2_6_model_fit_report.md")

MIN_N_FIT = 50
MIN_N_TEST = 30
N_FOLDS = 3
EPS = 1e-9


def load_pairs():
    """bet_diary'den unique (model_prob, did_we_win) çiftleri çıkar (predicted_at sırasıyla)."""
    if not os.path.exists(BET_DIARY):
        return []
    latest = {}
    for line in open(BET_DIARY):
        try:
            r = json.loads(line)
        except Exception:
            continue
        pid = r.get("prediction_id")
        if pid:
            latest[pid] = r
    rows = []
    for r in latest.values():
        mp = r.get("model_prob")
        w = r.get("did_we_win")
        ts = r.get("predicted_at") or ""
        if mp is None or w is None:
            continue
        try:
            mp_f = float(mp)
        except Exception:
            continue
        if mp_f <= 0 or mp_f >= 1:
            continue
        rows.append((ts, mp_f, int(bool(w))))
    rows.sort(key=lambda x: x[0])
    return rows


def brier(y, p):
    return float(np.mean((np.asarray(p) - np.asarray(y)) ** 2))


def log_loss(y, p):
    p = np.clip(np.asarray(p), EPS, 1 - EPS)
    y = np.asarray(y)
    return float(-np.mean(y * np.log(p) + (1 - y) * np.log(1 - p)))


def ece(y, p, n_bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, n_bins + 1)
    e = 0.0
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < n_bins - 1 else p <= edges[i + 1])
        if m.sum() == 0:
            continue
        e += (m.sum() / len(p)) * abs(p[m].mean() - y[m].mean())
    return float(e)


def mce(y, p, n_bins=10):
    y, p = np.asarray(y), np.asarray(p)
    edges = np.linspace(0, 1, n_bins + 1)
    worst = 0.0
    for i in range(n_bins):
        m = (p >= edges[i]) & (p < edges[i + 1] if i < n_bins - 1 else p <= edges[i + 1])
        if m.sum() == 0:
            continue
        worst = max(worst, abs(p[m].mean() - y[m].mean()))
    return float(worst)


class IsotonicCalibrator:
    def __init__(self):
        self.model = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0)

    def fit(self, p, y):
        self.model.fit(np.asarray(p), np.asarray(y))
        return self

    def predict(self, p):
        return np.clip(self.model.predict(np.asarray(p)), 0.0, 1.0)


class PlattCalibrator:
    def __init__(self):
        self.model = None
        self._fallback = 0.0

    def fit(self, p, y):
        p, y = np.asarray(p, dtype=float).reshape(-1, 1), np.asarray(y)
        if len(np.unique(y)) < 2:
            self._fallback = float(np.mean(y)) if len(y) else 0.0
            return self
        self.model = LogisticRegression().fit(p, y)
        return self

    def predict(self, p):
        if self.model is None:
            return np.full(len(p), self._fallback)
        return self.model.predict_proba(np.asarray(p, dtype=float).reshape(-1, 1))[:, 1]


class RawIdentity:
    def fit(self, p, y):
        return self

    def predict(self, p):
        return np.clip(np.asarray(p, dtype=float), 0.0, 1.0)


CALIBRATORS = {
    "raw":      lambda: RawIdentity(),
    "isotonic": lambda: IsotonicCalibrator(),
    "platt":    lambda: PlattCalibrator(),
    "beta":     lambda: BetaCalibrator(),
}


def walk_forward(rows, n_folds=N_FOLDS):
    """Expanding window: 5 fold için fold k → train: ilk (k+1)/(n+1) blok, test: k+1. blok."""
    n = len(rows)
    step = n // (n_folds + 1)
    if step < MIN_N_FIT:
        return None  # yetersiz
    folds = []
    for k in range(n_folds):
        tr_end = step * (k + 1)
        te_end = step * (k + 2)
        folds.append((slice(0, tr_end), slice(tr_end, te_end)))
    return folds


def run():
    pairs = load_pairs()
    if not pairs:
        print("FAIL  bet_diary'de geçerli (model_prob, did_we_win) çifti yok")
        return
    n_total = len(pairs)
    base = np.mean([w for _, _, w in pairs])
    print(f"dataset: n={n_total}, base-rate={base:.4f}")
    print(f"tarih aralığı: {pairs[0][0][:10]} → {pairs[-1][0][:10]}")
    print()

    folds = walk_forward(pairs, N_FOLDS)
    if folds is None:
        print(f"FAIL  walk-forward yetersiz (n={n_total} / fold={N_FOLDS} → fold n<MIN_N_FIT={MIN_N_FIT})")
        print(f"      en az n_total ≥ {(N_FOLDS + 1) * MIN_N_FIT} gerek (varsayılan {N_FOLDS} fold).")
        return

    p_all = np.asarray([mp for _, mp, _ in pairs])
    y_all = np.asarray([w for _, _, w in pairs])

    results = {}
    for cal_name in CALIBRATORS:
        per_fold = []
        for tr_sl, te_sl in folds:
            p_tr, y_tr = p_all[tr_sl], y_all[tr_sl]
            p_te, y_te = p_all[te_sl], y_all[te_sl]
            if len(p_tr) < MIN_N_FIT or len(p_te) < MIN_N_TEST:
                continue
            cal = CALIBRATORS[cal_name]()
            try:
                cal.fit(p_tr, y_tr)
                p_pred = cal.predict(p_te)
            except Exception as e:
                print(f"  {cal_name} fail: {e}")
                continue
            per_fold.append({
                "n_tr": len(p_tr), "n_te": len(p_te),
                "brier": brier(y_te, p_pred),
                "ece": ece(y_te, p_pred),
                "ll": log_loss(y_te, p_pred),
                "mce": mce(y_te, p_pred),
            })
        if per_fold:
            avg = {
                "brier": np.mean([f["brier"] for f in per_fold]),
                "ece":   np.mean([f["ece"] for f in per_fold]),
                "ll":    np.mean([f["ll"] for f in per_fold]),
                "mce":   np.mean([f["mce"] for f in per_fold]),
            }
            results[cal_name] = {"per_fold": per_fold, "avg": avg}

    print("WALK-FORWARD ortalamalar (3 fold):")
    print(f"  {'method':10s}  {'Brier':>9s}  {'ECE':>9s}  {'LogLoss':>9s}  {'MCE':>9s}")
    for cal_name, r in sorted(results.items(), key=lambda kv: kv[1]["avg"]["brier"]):
        a = r["avg"]
        print(f"  {cal_name:10s}  {a['brier']:9.5f}  {a['ece']:9.5f}  {a['ll']:9.5f}  {a['mce']:9.5f}")

    # Combined score: Brier + ECE (lower better)
    def comb(r):
        a = r["avg"]
        return a["brier"] + a["ece"]

    best = min(results.items(), key=lambda kv: comb(kv[1]))
    print()
    print(f"En iyi: {best[0]} (Brier+ECE={comb(best[1]):.5f})")

    if best[0] == "raw":
        print("Raw en iyi → kalibrasyon gerekli değil; active.pkl YAZILMADI.")
        return

    # Full-data fit + kaydet
    final = CALIBRATORS[best[0]]()
    final.fit(p_all, y_all)
    artifact = {
        "kind": "model_prob->outcome",
        "method": best[0],
        "model": final,
        "n_train": int(n_total),
        "n_val": 0,
        "base_rate": float(base),
        "wf_metrics": best[1]["avg"],
        "date_range": [pairs[0][0][:10], pairs[-1][0][:10]],
        "fitted_at": datetime.utcnow().isoformat() + "Z",
    }
    os.makedirs(FITTED_DIR, exist_ok=True)
    with open(ACTIVE, "wb") as f:
        pickle.dump(artifact, f)
    print(f"✓ {ACTIVE} (method={best[0]}, n={n_total})")

    # Rapor
    lines = [
        "# Phase 5.2.6 — Model_prob kalibrasyonu (forward fit)",
        f"_Tarih: {artifact['fitted_at']}_  ·  _Veri: bet_diary forward_",
        "",
        f"**Dataset:** n={n_total} (model_prob+did_we_win), base-rate={base:.4f}, "
        f"tarih={pairs[0][0][:10]} → {pairs[-1][0][:10]}",
        f"**Yöntem:** walk-forward {N_FOLDS}-fold (expanding window), Brier+ECE combined skor",
        f"**Seçilen kalibratör:** **{best[0]}** (Brier+ECE={comb(best[1]):.5f})",
        "",
        "## Walk-forward ortalamalar",
        "",
        "| Method | Brier | ECE | LogLoss | MCE |",
        "|---|---|---|---|---|",
    ]
    for cal_name, r in sorted(results.items(), key=lambda kv: kv[1]["avg"]["brier"]):
        a = r["avg"]
        lines.append(f"| {cal_name} | {a['brier']:.5f} | {a['ece']:.5f} | "
                     f"{a['ll']:.5f} | {a['mce']:.5f} |")
    lines += [
        "",
        "## Aktivasyon",
        f"- `{ACTIVE}` yazıldı → calibration_loader.apply_calibration() artık no-op değil",
        "- yerli_engine her tahmin için `calibrated_prob` üretir (legs_summary.all_horses_with_mp)",
        "- UX davranışı değişmez (kupon `model_prob` ham değerden gider); shadow meta + audit için kayıt",
        "",
        "## Sınırlamalar (dürüst)",
        f"- n={n_total} marjinal (büyük güven aralıkları); 1-2 hafta sonra yeniden koş",
        "- Walk-forward fold sayısı 3 (n<{} olsaydı yetersiz; çift veri birikince 5'e çık)".format((N_FOLDS + 1) * MIN_N_FIT),
        "- model_prob race-içi softmax-normalize (yarış başına toplam 1), bu binary calibrator hâlâ basit kuralı",
        "  uygulanabilir kabul ediliyor (Phase 5.5 forward görev: per-target/per-breed buckets).",
        "",
        f"## Rollback",
        f"```bash",
        f"rm {ACTIVE}   # apply_calibration tekrar no-op olur",
        f"```",
    ]
    with open(REPORT, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"✓ rapor: {REPORT}")


if __name__ == "__main__":
    run()
