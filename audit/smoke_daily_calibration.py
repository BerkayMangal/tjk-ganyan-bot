"""Phase 5.1.5 — günlük kalibrasyon diagnostiği (çağrılabilir smoke).

bet_diary son 30 gün → 04_bet_diary_report Section 2. n<50 → PENDING (hata atmaz).
Calibrator scaffold'larını da synthetic veriyle doğrular (sklearn yüklü mü).
Run: python audit/smoke_daily_calibration.py
"""
import importlib.util
import os
import sys
from datetime import date, timedelta

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)


def _load_report():
    spec = importlib.util.spec_from_file_location(
        "rpt", os.path.join(_REPO, "audit", "04_bet_diary_report.py"))
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


def main():
    import bet_diary as bd
    rpt = _load_report()
    since = (date.today() - timedelta(days=30)).isoformat()
    rows = bd.read_bets(since=since)
    print(f"[daily-cal] bet_diary son 30 gün: {len(rows)} kayıt")
    if not rows:
        print("[daily-cal] PENDING — veri yok (migration apply + forward collection bekleniyor).")
    else:
        print(rpt._sec_calibration(rows))

    # Calibrator scaffold doğrulama (synthetic — sklearn yüklü mü)
    print("[daily-cal] calibrator scaffold testi (synthetic):")
    try:
        from simulation.calibrators.isotonic import IsotonicCalibrator
        from simulation.calibrators.platt import PlattCalibrator
        raw = [0.1, 0.2, 0.3, 0.5, 0.7, 0.9]
        out = [0, 0, 0, 1, 1, 1]
        iso = IsotonicCalibrator().fit(raw, out)
        plt = PlattCalibrator().fit(raw, out)
        print(f"  isotonic.predict([0.4]) = {iso.predict([0.4])}")
        print(f"  platt.predict([0.4])    = {[round(x,3) for x in plt.predict([0.4])]}")
        print("  → calibrators ÇALIŞIYOR (Phase 5.2'de gerçek veriyle fit edilecek).")
    except Exception as e:
        print(f"  calibrator ERR: {repr(e)[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
