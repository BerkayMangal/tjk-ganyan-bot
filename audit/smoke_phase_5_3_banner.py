"""Phase 5.3 PART F smoke — banner içeriği + env-flag davranışı.

get_banner(): flag açıksa Phase 5.3 metni (V5.1_DAR baz), flag kapalıysa boş, asla raise etmez.
Run: python audit/smoke_phase_5_3_banner.py
"""
import os
import sys

_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(_REPO, "dashboard"))

import user_warnings  # noqa: E402


def main():
    ok = True

    os.environ["TJK_PHASE_5_2_WARNING"] = "1"
    b = user_warnings.get_banner()
    checks = [
        ("flag-on non-empty", bool(b)),
        ("Phase 5.3 etiketi", "Phase 5.3" in b),
        ("V5.1_DAR baz", "V5.1_DAR" in b),
        ("V7/smart_genis emekli notu", "emekli" in b.lower()),
        ("eski 'KALİBRASYON DÖNEMİ' yok", "KALİBRASYON DÖNEMİ" not in b),
    ]

    os.environ["TJK_PHASE_5_2_WARNING"] = "0"
    b_off = user_warnings.get_banner()
    checks.append(("flag-off boş", b_off == ""))

    # never-raise: bozuk env
    os.environ["TJK_PHASE_5_2_WARNING"] = "garbage"
    try:
        user_warnings.get_banner()
        checks.append(("garbage env raise etmez", True))
    except Exception:
        checks.append(("garbage env raise etmez", False))

    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'✅ ALL PASS' if ok else '❌ FAIL'}")
    print("\n--- banner (flag-on) ---")
    os.environ["TJK_PHASE_5_2_WARNING"] = "1"
    print(user_warnings.get_banner())
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
