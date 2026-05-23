"""Phase 1E.0 — Bet Diary (pro betçi günlüğü) — scaffolding.

CLV / EV / Kelly math + persistence. Pipeline entegrasyonu YOK (Phase 1E.1).
Persistence: JSONL (lokal) + event_store('bet_decision' → pipeline_events) dual-write.
bet_diary tablosu (migrations/m4_bet_diary.sql) doğrudan yazımı Phase 1E.1.

CLV = log(odds_at_prediction / odds_at_close): pozitif = yüksek odds yakaladık
(piyasa sonradan bizi onayladı). Plan'ın ters-işaretli formülü düzeltildi.
"""
from __future__ import annotations

import json
import math
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

_HERE = os.path.dirname(os.path.abspath(__file__))
_REPO_ROOT = os.path.dirname(_HERE)
BET_DIARY_LOG_PATH = os.path.join(_REPO_ROOT, "audit", "reports", "bet_diary_log.jsonl")

CONFIDENCE_GRADES = ("strong", "moderate", "limited", "insufficient")


@dataclass
class BetRecord:
    # zorunlu çekirdek
    hippodrome: str
    race_number: int
    horse_number: int
    model_prob: float
    # kimlik / zaman
    prediction_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    predicted_at: str = ""
    race_starts_at: Optional[str] = None
    altili_no: Optional[int] = None
    horse_name: Optional[str] = None
    # olasılık / fiyat
    model_prob_calibrated: Optional[float] = None     # Phase 2 doldurur
    agf_pct_at_prediction: Optional[float] = None
    agf_pct_at_close: Optional[float] = None
    odds_at_prediction: Optional[float] = None
    odds_at_close: Optional[float] = None
    ev_at_prediction: Optional[float] = None
    kelly_fraction: Optional[float] = None
    # stake / karar
    flat_bet_size: float = 10.0
    recommended_bet_size: Optional[float] = None
    did_we_bet: bool = False
    bet_rationale: dict = field(default_factory=dict)
    confidence_grade: str = "insufficient"
    consensus_snapshot: Optional[dict] = None         # Phase 1B.1 ValidatorOutput
    # sonuç (update_bet_outcome doldurur)
    actual_winner_number: Optional[int] = None
    did_we_win: Optional[bool] = None
    payout: Optional[float] = None
    theoretical_pnl_flat: Optional[float] = None
    theoretical_pnl_kelly: Optional[float] = None
    notes: Optional[str] = None

    def __post_init__(self):
        if not self.predicted_at:
            self.predicted_at = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> dict:
        return asdict(self)


# ───────────────────────── math ─────────────────────────

def compute_ev(model_prob: float, odds: float) -> float:
    """EV = model_prob·odds − 1. Pozitif = +EV bahis."""
    return model_prob * odds - 1.0


def compute_kelly(model_prob: float, odds: float) -> float:
    """Kelly fraction = (b·p − q)/b, b=odds−1, p=win, q=1−p. Negatif → 0 (bahis yok)."""
    b = odds - 1.0
    if b <= 0:
        return 0.0
    p = model_prob
    q = 1.0 - p
    return max(0.0, (b * p - q) / b)


def compute_clv(odds_at_prediction: Optional[float],
                odds_at_close: Optional[float]) -> Optional[float]:
    """CLV = log(odds_pred / odds_close). Pozitif = yüksek odds yakaladık (piyasa onayı)."""
    if (not odds_at_prediction or not odds_at_close
            or odds_at_prediction <= 0 or odds_at_close <= 0):
        return None
    return math.log(odds_at_prediction / odds_at_close)


def odds_from_agf(agf_pct: Optional[float]) -> Optional[float]:
    """AGF % → kaba decimal odds: 1/(agf_pct/100). agf_pct=25 → 4.0."""
    if not agf_pct or agf_pct <= 0:
        return None
    return 100.0 / agf_pct


# ──────────────── persistence (JSONL + event_store) ────────────────

def write_bet_decision(record: BetRecord) -> bool:
    """Append a bet decision. JSONL (lokal) + event_store dual-write. Returns JSONL ok."""
    rec = record.to_dict()
    ok = False
    try:
        os.makedirs(os.path.dirname(BET_DIARY_LOG_PATH), exist_ok=True)
        with open(BET_DIARY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        ok = True
    except Exception:
        pass
    try:
        from event_store import write_event
        write_event(
            "bet_decision",
            payload=rec,
            event_date=(record.predicted_at or "")[:10] or None,
            hippodrome=record.hippodrome,
            altili_no=record.altili_no,
        )
    except Exception:
        pass
    return ok


def _read_all_raw() -> list[dict]:
    if not os.path.exists(BET_DIARY_LOG_PATH):
        return []
    out: list[dict] = []
    with open(BET_DIARY_LOG_PATH, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    return out


def read_bets(since: Any = None, hippodrome: Optional[str] = None) -> list[dict]:
    """Latest record per prediction_id (append-only → son satır kazanır)."""
    latest: dict = {}
    for r in _read_all_raw():
        latest[r.get("prediction_id")] = r
    rows = list(latest.values())
    if since is not None:
        s = since.isoformat() if hasattr(since, "isoformat") else str(since)
        rows = [r for r in rows if (r.get("predicted_at") or "") >= s]
    if hippodrome:
        rows = [r for r in rows if r.get("hippodrome") == hippodrome]
    return rows


def update_bet_outcome(prediction_id: str, actual_winner: int, payout: float) -> bool:
    """Outcome güncelle: did_we_win + theoretical P&L. Append (read_bets son'u alır)."""
    rec = next((r for r in read_bets() if r.get("prediction_id") == prediction_id), None)
    if rec is None:
        return False
    won = (rec.get("horse_number") == actual_winner)
    odds = rec.get("odds_at_prediction")
    flat = rec.get("flat_bet_size") or 0.0
    kelly_stake = rec.get("recommended_bet_size") or 0.0
    rec["actual_winner_number"] = actual_winner
    rec["did_we_win"] = won
    rec["payout"] = payout
    if won and odds:
        rec["theoretical_pnl_flat"] = flat * (odds - 1.0)
        rec["theoretical_pnl_kelly"] = kelly_stake * (odds - 1.0)
    else:
        rec["theoretical_pnl_flat"] = -flat
        rec["theoretical_pnl_kelly"] = -kelly_stake
    try:
        with open(BET_DIARY_LOG_PATH, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False, default=str) + "\n")
        return True
    except Exception:
        return False
