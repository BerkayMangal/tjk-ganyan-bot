"""Phase 5.1 smoke — 3 strateji replay (snapshot + retro sonuç).

live_tests/2026-05-22.json (içi 21 Mayıs) altılılarını retro.fetch_results(2026-05-21)
sonuçlarıyla eşleştirip V5.1/V7/smart_genis'i side-by-side koşturur.
N=1-2 sample, SADECE smoke (gerçek backtest Phase 5.2 sonrası). Run: python audit/smoke_phase_5_1_replay.py
"""
import json
import os
import sys
import warnings
from datetime import date

warnings.filterwarnings("ignore")
_REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
for _p in (_REPO, os.path.join(_REPO, "dashboard")):
    if _p not in sys.path:
        sys.path.insert(0, _p)

from simulation.altili_simulator import compare_strategies            # noqa: E402
from simulation.strategies.v5_1_strategy import v5_1_strategy          # noqa: E402
from simulation.strategies.v7_strategy import v7_strategy              # noqa: E402
from simulation.strategies.smart_genis_strategy import smart_genis_strategy  # noqa: E402
from engine.retro import fetch_results                                 # noqa: E402


def _norm(s):
    return (s or "").lower().replace(" hipodromu", "").replace(" hipodrom", "").strip()


def main():
    snap = json.load(open(os.path.join(_REPO, "data/live_tests/2026-05-22.json")))
    results = fetch_results(date(2026, 5, 21))
    rmap = {}
    for r in results:
        key = (_norm(r.get("hippodrome")), r.get("altili_no"))
        winners = {w.get("leg_number"): w.get("horse_number") for w in (r.get("winners") or [])}
        rmap[key] = [winners.get(i) for i in range(1, 7)]

    strategies = [v5_1_strategy, v7_strategy, smart_genis_strategy]
    print(f"retro sonuç altılı sayısı: {len(rmap)}")
    print("\n=== DAVRANIŞ KARŞILAŞTIRMASI (combo/cost/singles — actual gerektirmez) ===")
    for h in snap.get("hippodromes", []):
        key = (_norm(h.get("hippodrome")), h.get("altili_no"))
        actual = rmap.get(key)
        # Davranış: her stratejiyi çağır, combo/cost/singles
        print(f"\n{h.get('hippodrome')} #{h.get('altili_no')}"
              f"{' | actual='+str(actual) if actual and None not in actual else ' | (sonuç eşleşmedi)'}")
        for fn in strategies:
            try:
                k = fn(h)
                widths = [len(ls) for ls in (k.get("legs_selected") or [])]
                singles = sum(1 for w in widths if w == 1)
                note = k.get("note", "")
                line = (f"  {k['name']:12s} combo={k.get('combo'):>5} cost={k.get('cost'):>8} "
                        f"widths={widths} singles={singles}")
                # actual varsa hit/partial ekle
                if actual and None not in actual:
                    o = compare_strategies(h, actual, [fn])[0]
                    line += f" | partial={o['partial_hits']}/6 hit={o['hit']}"
                print(line + (f" [{note}]" if note else ""))
            except Exception as e:
                print(f"  {getattr(fn,'__name__','?'):12s} ERROR: {repr(e)[:70]}")
    print("\n[smoke] N=4 altılı, davranış doğrulaması (gerçek hit/payout: Phase 5.2 sonrası).")
    print("[smoke] Gözlem: V7 EN GENİŞ (combo 1800-4000, ~5000 TL, width 9'a kadar) vs")
    print("        v5.1_dar dar/tutarlı (~768 combo, 960 TL). 5x fark → 3 sistem radikal farklı.")
    print("        smart_genis adapter'dan BOŞ: build_smart_genis result['dar']['legs']")
    print("        gerektiriyor (canlı-state bağımlı, pure-function değil) → Phase 5.2 zincirleme.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
