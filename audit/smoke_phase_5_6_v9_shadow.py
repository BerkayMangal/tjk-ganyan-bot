"""Phase 5.6 PART 7 smoke — v9 shadow routing (PATCH_5_6_V9_SHADOW).

get_v9_pipeline → f(result) shadow META; ENV off=on prod davranışı aynı; jockey/form yoksa
graceful (L5/L6 neutral); hata→{error}. Telegram DOKUNULMAZ. Run: PYTHONPATH=.:dashboard python ...
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

from calibration_loader import get_v9_pipeline   # noqa: E402


def main():
    ok = True
    checks = []
    run = get_v9_pipeline()
    checks.append(("get_v9_pipeline callable döndürür", callable(run)))

    # 1) reconstructed snapshot (jockey/form yok → prod-benzeri)
    from simulation.snapshot_builder import build_snapshots
    snap = build_snapshots("raw")[0]["result"]
    os.environ["TJK_V8_STRATEGY_ROUTER"] = "off"
    sh_off = run(snap)
    os.environ["TJK_V8_STRATEGY_ROUTER"] = "on"
    sh_on = run(snap)
    os.environ["TJK_V8_STRATEGY_ROUTER"] = "off"
    checks.append(("shadow dict üretildi (error yok)", "error" not in sh_off))
    checks.append(("strategy alanı dolu", bool(sh_off.get("strategy"))))
    checks.append(("ENV off→router_active False", sh_off.get("router_active") is False))
    checks.append(("ENV on→router_active True", sh_on.get("router_active") is True))
    checks.append(("off vs on: strateji AYNI (sadece flag farkı)",
                   sh_off.get("strategy") == sh_on.get("strategy")))

    # 2) live_test snapshot (gerçek prod-şekli, all_horses jockey/form yok) → graceful
    live = json.load(open(os.path.join(_REPO, "data/live_tests/2026-05-22.json")))
    h = live["hippodromes"][0]
    h.setdefault("date", "2026-05-22")
    sh_live = run(h)
    checks.append(("live_test snapshot graceful (error yok)", "error" not in sh_live))

    # 3) anti-regression: hook result['dar']'a dokunmaz (shadow yalnız v9_shadow ekler)
    dar_before = json.dumps(h.get("dar"), sort_keys=True)
    run(h)
    checks.append(("anti-regression: result['dar'] değişmedi", json.dumps(h.get("dar"), sort_keys=True) == dar_before))

    for name, passed in checks:
        print(f"  [{'PASS' if passed else 'FAIL'}] {name}")
        ok = ok and passed
    print(f"\n  örnek shadow: strategy={sh_off.get('strategy')} reason={str(sh_off.get('reason'))[:55]}")
    print(f"  kupon_preview cost(proxy)={sh_off.get('kupon_preview',{}).get('total_cost_proxy')}")
    print(f"{'✅ ALL PASS' if ok else '❌ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
