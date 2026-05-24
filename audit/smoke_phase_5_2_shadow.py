"""Phase 5.2 — shadow calibration smoke: no-op fallback + calibrator-varsa."""
import os
import pickle
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)
import calibration_loader as cl  # noqa: E402


def main():
    # 1. active.pkl YOK → no-op (None), çökmez
    assert not os.path.exists(cl._FITTED), "test öncesi active.pkl olmamalı"
    print(f"no-calibrator apply(0.5) = {cl.apply_calibration(0.5)} (None beklenir)")
    assert cl.apply_calibration(0.5) is None
    assert cl.apply_calibration(None) is None
    print("None input → None ✓ (no-op fallback çalışıyor)")

    # 2. fitted calibrator inject → calibrated değer döner
    from simulation.calibrators.isotonic import IsotonicCalibrator
    iso = IsotonicCalibrator().fit([0.1, 0.3, 0.5, 0.7, 0.9], [0, 0, 1, 1, 1])
    os.makedirs(os.path.dirname(cl._FITTED), exist_ok=True)
    with open(cl._FITTED, "wb") as f:
        pickle.dump(iso, f)
    cl._loaded = False; cl._cache = None  # cache reset
    try:
        v = cl.apply_calibration(0.6)
        print(f"with-calibrator apply(0.6) = {v} (sayı beklenir)")
        assert v is not None
    finally:
        os.remove(cl._FITTED)  # geçici — PART D: gerçek active.pkl üretilmedi (label yok)
        cl._loaded = False; cl._cache = None

    # 3. mock at dict — shadow yazım simülasyonu
    at = {"number": 5, "model_prob": 45.2}
    at["calibrated_prob"] = cl.apply_calibration((at["model_prob"] or 0) / 100.0)
    print(f"mock at: model_prob={at['model_prob']} → calibrated_prob={at['calibrated_prob']} (no-op None)")
    print("\n[smoke] shadow calibration OK: no-op güvenli, calibrator varsa çalışıyor, çökmez.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
