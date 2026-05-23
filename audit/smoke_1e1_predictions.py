"""Phase 1E.1 smoke — write_predictions_for_altili.

Snapshot consensus → shadow (run_shadow_validation) → writer akışını taklit eder.
Gerçek pipeline'ın yaptığı zinciri lokal fixture ile koşturur. Geçici JSONL kullanır.
Run: python audit/smoke_1e1_predictions.py
"""
import json
import os
import sys
import tempfile
from collections import Counter

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard"))
import bet_diary as bd          # noqa: E402
import bet_diary_writer as bdw  # noqa: E402
import source_consensus as sc   # noqa: E402

SNAP = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                    "data", "live_tests", "2026-05-22.json")


def main():
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    os.remove(tmp)
    bd.BET_DIARY_LOG_PATH = tmp
    try:
        snap = json.load(open(SNAP))
        total = vbets = 0
        for h in snap.get("hippodromes", []):
            cons = h.get("consensus", [])
            sc_out = sc.run_shadow_validation(h.get("hippodrome"), h.get("altili_no"),
                                              consensus_result=cons)
            r = bdw.write_predictions_for_altili(h, None, sc_out.to_dict(), "2026-05-21")
            total += r["records_written"]
            vbets += r["value_bets"]
            if r["errors"]:
                print("  errors:", r["errors"][:3])
        rows = bd.read_bets()
        grades = Counter(x["confidence_grade"] for x in rows)
        bet_grades = Counter(x["confidence_grade"] for x in rows if x["did_we_bet"])
        print(f"[smoke] altılı: {len(snap.get('hippodromes', []))}")
        print(f"[smoke] yazılan kayıt: {total} | value_bet (did_we_bet): {vbets}")
        print(f"[smoke] read_bets: {len(rows)}")
        print(f"[smoke] confidence_grade (tümü): {dict(grades)}")
        print(f"[smoke] confidence_grade (did_we_bet): {dict(bet_grades)}")
        sample = next((x for x in rows if x["did_we_bet"]), None) or (rows[0] if rows else None)
        if sample:
            keys = ["hippodrome", "race_number", "horse_number", "model_prob",
                    "agf_pct_at_prediction", "odds_at_prediction", "ev_at_prediction",
                    "kelly_fraction", "recommended_bet_size", "did_we_bet", "confidence_grade"]
            print("[smoke] örnek kayıt:")
            for k in keys:
                print(f"    {k}: {sample.get(k)}")
            print(f"    bet_rationale: {sample.get('bet_rationale')}")
        return 0
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)


if __name__ == "__main__":
    raise SystemExit(main())
