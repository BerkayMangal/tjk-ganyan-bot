"""Phase 5.3.5 smoke — TJK_KUPON_MODE gating (V7 retire + smart_genis defer).

Pipeline assembly'yi (yerli_engine 2579-2584 + has_v7 4491) replike eder:
- default v5_1_only → V7 ANALİZ + SMART GENİŞ + V7 coupon YOK (tek kupon)
- all (rollback) → hepsi VAR
Run: PYTHONPATH=.:dashboard python audit/smoke_phase_5_3_5_kupon_mode.py
"""
import json
import os
import sys
import warnings

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import yerli_engine as ye  # noqa: E402


def _assemble(all_results, date_str):
    """yerli_engine 2579-2584 mantığını replike (env gate'li)."""
    base = ye._format_telegram_simple(all_results, date_str)  # has_v7 İÇERDE env-gated
    if os.getenv("TJK_KUPON_MODE", "v5_1_only") == "all":
        base = ye._format_smart_genis_for_telegram(base, all_results)
    if os.getenv("TJK_KUPON_MODE", "v5_1_only") == "all":
        base = ye._format_v7_for_telegram(base, all_results)
    return base


def main():
    snap = json.load(open(os.path.join(_REPO, "data/live_tests/2026-05-22.json")))
    all_results = snap["hippodromes"]
    date_str = "2026-05-22"

    os.environ["TJK_KUPON_MODE"] = "v5_1_only"
    msg_v51 = _assemble(all_results, date_str)
    os.environ["TJK_KUPON_MODE"] = "all"
    msg_all = _assemble(all_results, date_str)
    os.environ["TJK_KUPON_MODE"] = "v5_1_only"

    checks = [
        ("v5_1_only: V7 ANALİZ YOK", "V7 ANAL" not in msg_v51),
        ("v5_1_only: SMART GENİŞ YOK", "SMART GEN" not in msg_v51),
        ("all: V7 ANALİZ VAR (rollback)", "V7 ANAL" in msg_all),
        ("all: SMART GENİŞ VAR (rollback)", "SMART GEN" in msg_all),
        ("v5_1_only mesajı daha kısa (V7+smart çıktı)", len(msg_v51) < len(msg_all)),
        ("v5_1_only: kupon hâlâ üretiliyor (boş değil)", len(msg_v51) > 100),
        ("anti-regression: DAR/ALTILI başlık korunuyor", "ALTILI" in msg_v51),
    ]
    ok = True
    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n  v5_1_only msg: {len(msg_v51)} char | all msg: {len(msg_all)} char")
    print(f"{'✅ ALL PASS' if ok else '❌ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
