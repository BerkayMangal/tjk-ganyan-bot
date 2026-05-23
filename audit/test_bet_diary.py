"""Phase 1E.0 — bet_diary unit tests. pytest GEREKTİRMEZ (assert + exit code).

Run: python audit/test_bet_diary.py   (exit 0 = pass)
"""
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "dashboard"))
import bet_diary as bd  # noqa: E402


def approx(a, b, eps=1e-9):
    return a is not None and abs(a - b) < eps


def test_ev():
    assert approx(bd.compute_ev(0.3, 5.0), 0.5), bd.compute_ev(0.3, 5.0)
    assert approx(bd.compute_ev(0.1, 2.0), -0.8), bd.compute_ev(0.1, 2.0)


def test_kelly():
    # (b*p - q)/b = (4*0.3 - 0.7)/4 = 0.5/4 = 0.125
    assert approx(bd.compute_kelly(0.3, 5.0), 0.125), bd.compute_kelly(0.3, 5.0)
    # negatif edge → 0 (bahis yok)
    assert bd.compute_kelly(0.1, 2.0) == 0.0, bd.compute_kelly(0.1, 2.0)
    assert bd.compute_kelly(0.5, 1.0) == 0.0  # b<=0


def test_clv():
    # 4.0'da oynadık, kapanış 3.5 → YÜKSEK odds yakaladık → POZİTİF (piyasa onayı)
    c = bd.compute_clv(4.0, 3.5)
    assert c is not None and c > 0, c
    # ters: 3.5'te oynadık, kapanış 4.0 → düşük odds → NEGATİF
    assert bd.compute_clv(3.5, 4.0) < 0
    assert bd.compute_clv(None, 3.5) is None
    assert bd.compute_clv(4.0, 0) is None


def test_roundtrip(tmp):
    bd.BET_DIARY_LOG_PATH = tmp
    r = bd.BetRecord(hippodrome="Bursa", race_number=3, horse_number=5, model_prob=0.3,
                     odds_at_prediction=5.0, flat_bet_size=10.0, recommended_bet_size=1.25)
    assert bd.write_bet_decision(r)
    rows = bd.read_bets()
    assert len(rows) == 1, len(rows)
    assert rows[0]["prediction_id"] == r.prediction_id
    assert rows[0]["horse_number"] == 5


def test_outcome(tmp):
    bd.BET_DIARY_LOG_PATH = tmp
    # WIN
    r = bd.BetRecord(hippodrome="Bursa", race_number=3, horse_number=5, model_prob=0.3,
                     odds_at_prediction=5.0, flat_bet_size=10.0, recommended_bet_size=2.0)
    bd.write_bet_decision(r)
    assert bd.update_bet_outcome(r.prediction_id, actual_winner=5, payout=50.0)
    row = next(x for x in bd.read_bets() if x["prediction_id"] == r.prediction_id)
    assert row["did_we_win"] is True
    assert approx(row["theoretical_pnl_flat"], 40.0), row["theoretical_pnl_flat"]  # 10*(5-1)
    assert approx(row["theoretical_pnl_kelly"], 8.0), row["theoretical_pnl_kelly"]  # 2*(5-1)
    # LOSS
    r2 = bd.BetRecord(hippodrome="Bursa", race_number=4, horse_number=3, model_prob=0.2,
                      odds_at_prediction=6.0, flat_bet_size=10.0, recommended_bet_size=1.0)
    bd.write_bet_decision(r2)
    bd.update_bet_outcome(r2.prediction_id, actual_winner=7, payout=0.0)
    row2 = next(x for x in bd.read_bets() if x["prediction_id"] == r2.prediction_id)
    assert row2["did_we_win"] is False
    assert approx(row2["theoretical_pnl_flat"], -10.0), row2["theoretical_pnl_flat"]
    # update bilinmeyen id → False
    assert bd.update_bet_outcome("yok", 1, 0.0) is False


if __name__ == "__main__":
    test_ev()
    test_kelly()
    test_clv()
    fd, tmp = tempfile.mkstemp(suffix=".jsonl")
    os.close(fd)
    try:
        os.remove(tmp)
        test_roundtrip(tmp)
        os.remove(tmp)
        test_outcome(tmp)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    print("[bet_diary tests] ALL PASS")
