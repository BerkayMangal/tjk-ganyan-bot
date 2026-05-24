"""Phase 5.5 PART C smoke — FLB shadow integration.

Loader no-op/değer + build_kupon ENV OFF (değişmez) vs ON (re-sort) + never-crash.
Run: PYTHONPATH=.:dashboard python audit/smoke_phase_5_5_shadow.py
"""
import os
import sys
import warnings

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from calibration_loader import flb_multiplier, apply_flb_compensation  # noqa: E402
from simulation.snapshot_builder import build_snapshots                # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy           # noqa: E402


def main():
    ok = True
    checks = []

    # 1) loader yönü
    m_long = flb_multiplier(2)    # longshot
    m_fav = flb_multiplier(60)    # ağır favori
    checks.append(("longshot mult > 1", m_long > 1.0))
    checks.append(("favori mult < 1", m_fav < 1.0))
    checks.append(("apply_flb_compensation çarpıyor",
                   abs(apply_flb_compensation(1.0, 2) - m_long) < 1e-3))
    checks.append(("None raw → None (no-op)", apply_flb_compensation(None, 10) is None))

    # 2) build_kupon ENV OFF vs ON
    snaps = build_snapshots("raw")
    diffs = 0
    valid = 0
    for s in snaps[:20]:
        r = s["result"]
        os.environ["TJK_FLB_ACTIVE"] = "0"
        off = v5_1_strategy(r)["legs_selected"]
        os.environ["TJK_FLB_ACTIVE"] = "1"
        on = v5_1_strategy(r)["legs_selected"]
        if off:
            valid += 1
        if off != on:
            diffs += 1
    os.environ["TJK_FLB_ACTIVE"] = "0"
    checks.append(("OFF geçerli kupon üretir", valid == 20))
    checks.append(("ON en az bir altılıda seçim değiştirir", diffs > 0))

    # 3) never-crash: bozuk env
    os.environ["TJK_FLB_ACTIVE"] = "garbage"
    try:
        v5_1_strategy(snaps[0]["result"])
        checks.append(("garbage env crash etmez", True))
    except Exception:
        checks.append(("garbage env crash etmez", False))
    os.environ["TJK_FLB_ACTIVE"] = "0"

    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n{'✅ ALL PASS' if ok else '❌ FAIL'}  (ON vs OFF farklı altılı: {diffs}/20)")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
