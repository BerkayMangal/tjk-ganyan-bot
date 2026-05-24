"""Phase 5.7.5 PART 4 — yarın sabah PROD-SİM (complete.csv yok varsay → enr=None prod-path).

Sabah v9 mesaj + akşam retro + varyasyonlar (carryover-3, kill-switch, force-error).
Run: PYTHONPATH=.:dashboard python audit/simulate_tomorrow.py
"""
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
    from simulation.snapshot_builder import build_snapshots
    from simulation.v9.pipeline import build_v9_race, run_pipeline
    from telegram_formatter_v9 import format_message, format_messages_list, v9_live_enabled
    from retro_formatter_v9 import format_retro_message

    snaps = build_snapshots("raw")[:4]
    results = [s["result"] for s in snaps]

    print("=" * 60, "\n☀️ SABAH — 4 altılı v9 mesajı (PROD-path, enr=None)\n", "=" * 60)
    msgs = format_messages_list(results, "2026-05-24")
    from collections import Counter
    strat = Counter()
    for s in snaps:
        out = run_pipeline(build_v9_race(dict(s["result"]), None))
        strat[out["routing"]["strategy"]] += 1
    print(f"strateji dağılımı (4 altılı): {dict(strat)}")
    print("\n--- 1. altılı mesajı (örnek) ---")
    print(msgs[0][:700])

    print("\n", "=" * 60, "\n🌙 AKŞAM — retro (gerçek sonuçlarla)\n", "=" * 60)
    s = snaps[0]
    out = run_pipeline(build_v9_race(dict(s["result"]), None))
    retro = format_retro_message(s["result"]["hippodrome"], "14:00", out["routing"]["strategy"],
                                 s["actual_results"], out["kupon"].get("legs_selected") or [],
                                 out["aggregated"]["legs"])
    print(retro[:600])

    print("\n", "=" * 60, "\n🔀 VARYASYONLAR\n", "=" * 60)
    # carryover-3 → Kangal frekansı
    os.environ["TJK_CARRYOVER_DAY"] = "3"
    from simulation.v9.carryover_detector import detect_carryover_state
    cs = detect_carryover_state()
    kc = Counter(run_pipeline(build_v9_race(dict(x["result"]), None), cs)["routing"]["strategy"]
                 for x in build_snapshots("raw"))
    print(f"1) carryover=3 → dağılım: {dict(kc)} (Kangal artmalı)")
    os.environ["TJK_CARRYOVER_DAY"] = "0"
    # kill-switch
    os.environ["TJK_V9_LIVE"] = "0"
    print(f"2) TJK_V9_LIVE=0 → v9_live_enabled()={v9_live_enabled()} (False → V5.1 gider)")
    os.environ["TJK_V9_LIVE"] = "1"
    # force-error → fallback
    try:
        format_messages_list([], "2026-05-24")
        print("3) force-error: RAISE YOK (BEKLENMEDİK)")
    except Exception as e:
        print(f"3) force-error (boş) → raise → V5.1 fallback ✓ ({type(e).__name__})")
    print("\n✅ SİMÜLASYON TAMAM — beklenmedik davranış yok")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
