"""Phase 5.6.5 PART 7 smoke — HYBRID CANLI: v9 day message + V5.1 fallback + pas + banner.

Run: PYTHONPATH=.:dashboard python audit/smoke_phase_5_6_5_live.py
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


def main():
    os.environ["TJK_CARRYOVER_DAY"] = "0"
    from telegram_formatter_v9 import format_day_message
    from simulation.snapshot_builder import build_snapshots
    import user_warnings

    checks = []
    # 1) V9 normal — reconstructed snapshots (prod-path)
    all_results = [s["result"] for s in build_snapshots("raw")[:4]]
    msg = format_day_message(all_results, "2026-05-16")
    checks.append(("V9 day message üretildi", bool(msg) and len(msg) > 200))
    checks.append(("strateji başlığı var", any(k in msg for k in ("TAM SİSTEM", "FAVORİ YIKMA", "KANGAL", "net sinyal"))))
    checks.append(("footer payout=PROXY", "payout=PROXY" in msg))
    checks.append(("bot DEĞİL notu", "bot DEĞİL" in msg))

    # 2) V9 fail → raise (caller V5.1 fallback) : boş liste → RuntimeError
    try:
        format_day_message([], "2026-05-16")
        checks.append(("boş input → raise (fallback tetikler)", False))
    except Exception:
        checks.append(("boş input → raise (fallback tetikler)", True))

    # 3) live_test snapshot (gerçek prod-şekli) → çökmeden mesaj
    live = json.load(open(os.path.join(_REPO, "data/live_tests/2026-05-22.json")))
    try:
        m2 = format_day_message(live["hippodromes"], "2026-05-22")
        checks.append(("live_test snapshot → mesaj (çökmedi)", bool(m2)))
    except Exception as e:
        checks.append((f"live_test snapshot → mesaj: {repr(e)[:40]}", False))

    # 4) banner Phase 5.6.5
    os.environ["TJK_PHASE_5_2_WARNING"] = "1"
    b = user_warnings.get_banner()
    checks.append(("banner Phase 5.6.5", "5.6.5" in b and "router" in b))

    # 5) anti-regression: V5.1 path (_format_telegram_simple) hâlâ çalışıyor
    import yerli_engine as ye
    v51 = ye._format_telegram_simple(all_results, "2026-05-16")
    checks.append(("V5.1 fallback yolu çalışıyor (anti-regression)", bool(v51) and len(v51) > 50))

    ok = True
    for name, p in checks:
        print(f"  [{'PASS' if p else 'FAIL'}] {name}")
        ok = ok and p
    print(f"\n{'✅ ALL PASS' if ok else '❌ FAIL'}")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
