"""Kelly criterion + bankroll matematiği + stake önerileri.

Berkay (2026-07-01): 'para para para' + defansif money management.

Kelly criterion:
  f* = (b·p - q) / b
  where b = decimal_odds - 1, p = fair_prob, q = 1-p

  Fractional Kelly (safer): f_used = k × f*, k ∈ [0.25, 0.5]
  0.25 (Quarter Kelly) — çok defansif, düşük varyans
  0.5 (Half Kelly) — dengeli
  1.0 (Full Kelly) — agresif, teorik optimal

Bu modülün amacı:
  1) At başına Kelly fraction hesap
  2) Bankroll × conservative multiplier → TL stake
  3) Portfolio: gün içi tüm bahisler bankroll % ile normalize
  4) Simüle: N bahis sonrası beklenen bankroll (Monte Carlo)

DÜRÜST NOT: Kelly VARIANCE-HIGH. Kısa vadede negative streak olabilir.
Half/Quarter Kelly kullan. Berkay bot değil — sadece bilgi verir.

API
---
- kelly_stake(bankroll_tl, decimal_odds, fair_prob, kelly_fraction=0.25)
- portfolio_stakes(bankroll_tl, bets, max_per_bet_pct=0.05, kelly_k=0.25)
- monte_carlo_bankroll(start_tl, bets, kelly_k, n_sims=1000)
"""
from __future__ import annotations

import os
import random
from typing import Iterable

DEFAULT_KELLY_K = float(os.environ.get("TJK_KELLY_FRACTION", "0.25"))
DEFAULT_MAX_PER_BET_PCT = float(
    os.environ.get("TJK_MAX_STAKE_PCT", "5.0"))


def kelly_fraction(decimal_odds: float, fair_prob: float) -> float:
    """Klasik Kelly: f* = (b·p - q) / b. Negative → no bet."""
    if decimal_odds <= 1.0 or fair_prob <= 0 or fair_prob >= 1:
        return 0.0
    b = decimal_odds - 1.0
    p = fair_prob
    q = 1.0 - p
    f_star = (b * p - q) / b
    return max(0.0, f_star)


def kelly_stake(bankroll_tl: float, decimal_odds: float,
                 fair_prob: float,
                 kelly_k: float = None,
                 max_pct: float = None) -> dict:
    """Bir bahis için önerilen stake.

    Args:
      bankroll_tl: mevcut bankroll (TL)
      decimal_odds: bookmaker decimal odds
      fair_prob: fair probability (0..1)
      kelly_k: fraction of Kelly (0.25 quarter, 0.5 half, 1.0 full)
      max_pct: cap per bet as % of bankroll

    Returns: {kelly_fraction, kelly_stake_pct, stake_tl, expected_profit_tl,
              expected_ev_pct}
    """
    kelly_k = kelly_k if kelly_k is not None else DEFAULT_KELLY_K
    max_pct = max_pct if max_pct is not None else DEFAULT_MAX_PER_BET_PCT

    f_star = kelly_fraction(decimal_odds, fair_prob)
    f_used = min(f_star * kelly_k, max_pct / 100.0)
    stake_tl = round(bankroll_tl * f_used, 2)
    ev_pct = (fair_prob * (decimal_odds - 1) - (1 - fair_prob)) * 100
    expected_profit = stake_tl * ev_pct / 100
    return {
        "kelly_star_pct": round(f_star * 100, 3),
        "kelly_used_pct": round(f_used * 100, 3),
        "stake_tl": stake_tl,
        "expected_profit_tl": round(expected_profit, 2),
        "expected_ev_pct": round(ev_pct, 2),
        "kelly_k": kelly_k,
        "capped": f_star * kelly_k > (max_pct / 100.0),
    }


def portfolio_stakes(bankroll_tl: float,
                      bets: Iterable[dict],
                      kelly_k: float = None,
                      max_per_bet_pct: float = None,
                      max_total_pct: float = 20.0) -> dict:
    """Günün tüm value bet'leri için stake önerisi.

    bets: [{name, decimal_odds, fair_prob, ...}, ...]

    max_total_pct: bankroll'un maximum yüzdesi (varyans koruması, default %20)
                    → tüm stake toplamı bu değeri aşarsa proportional scale-down.

    Returns: {bets_with_stakes, total_stake_tl, max_stake_tl,
              expected_total_profit, active_bets_count}
    """
    kelly_k = kelly_k if kelly_k is not None else DEFAULT_KELLY_K
    max_per_bet = (max_per_bet_pct if max_per_bet_pct is not None
                    else DEFAULT_MAX_PER_BET_PCT)

    results = []
    total_raw = 0.0
    for b in bets:
        odds = b.get("odds") or b.get("best_odds") or b.get("decimal_odds")
        fair_p = (b.get("fair_prob")
                  or b.get("consensus_prob_pct", 0) / 100.0)
        if not odds or not fair_p:
            continue
        s = kelly_stake(bankroll_tl, odds, fair_p,
                        kelly_k=kelly_k, max_pct=max_per_bet)
        if s["stake_tl"] <= 0:
            continue
        results.append({**b, **s})
        total_raw += s["stake_tl"]

    # Total cap enforcement
    total_cap = bankroll_tl * (max_total_pct / 100.0)
    scale_factor = 1.0
    if total_raw > total_cap:
        scale_factor = total_cap / total_raw
        for r in results:
            r["stake_tl"] = round(r["stake_tl"] * scale_factor, 2)
            r["kelly_used_pct"] = round(r["kelly_used_pct"] * scale_factor,
                                          3)
            r["expected_profit_tl"] = round(
                r["expected_profit_tl"] * scale_factor, 2)

    total_stake = sum(r["stake_tl"] for r in results)
    total_profit = sum(r["expected_profit_tl"] for r in results)
    max_stake = max((r["stake_tl"] for r in results), default=0)
    return {
        "bets_with_stakes": results,
        "total_stake_tl": round(total_stake, 2),
        "max_stake_tl": round(max_stake, 2),
        "expected_total_profit_tl": round(total_profit, 2),
        "active_bets_count": len(results),
        "scaled_down": scale_factor < 1.0,
        "scale_factor": round(scale_factor, 3),
        "bankroll_utilization_pct": round(
            100 * total_stake / bankroll_tl, 2) if bankroll_tl else 0,
    }


def monte_carlo_bankroll(start_tl: float, bets: list[dict],
                          n_sims: int = 1000,
                          kelly_k: float = None) -> dict:
    """Simüle N gün: bugünün bahis portföyünü N kere oyna, bankroll evrimi."""
    kelly_k = kelly_k if kelly_k is not None else DEFAULT_KELLY_K
    if not bets:
        return {}
    rng = random.Random(42)
    outcomes = []
    for _ in range(n_sims):
        bankroll = start_tl
        for b in bets:
            odds = (b.get("odds") or b.get("best_odds")
                    or b.get("decimal_odds"))
            fair_p = (b.get("fair_prob")
                      or b.get("consensus_prob_pct", 0) / 100.0)
            if not odds or not fair_p:
                continue
            stake = b.get("stake_tl", 0)
            if stake <= 0:
                continue
            if rng.random() < fair_p:
                bankroll += stake * (odds - 1)  # win
            else:
                bankroll -= stake  # lose
        outcomes.append(bankroll)
    outcomes.sort()
    n = len(outcomes)
    return {
        "n_sims": n,
        "mean_end_bankroll": round(sum(outcomes) / n, 2),
        "median_end_bankroll": round(outcomes[n // 2], 2),
        "p10_end_bankroll": round(outcomes[int(n * 0.10)], 2),
        "p90_end_bankroll": round(outcomes[int(n * 0.90)], 2),
        "win_probability_pct": round(
            100 * sum(1 for o in outcomes if o > start_tl) / n, 2),
        "min_end_bankroll": round(outcomes[0], 2),
        "max_end_bankroll": round(outcomes[-1], 2),
    }


def format_stake_recommendation(stake_result: dict,
                                 currency: str = "TL") -> str:
    """Kompakt Telegram/dashboard için stake string."""
    if not stake_result or stake_result.get("stake_tl", 0) <= 0:
        return ""
    st = stake_result["stake_tl"]
    ev = stake_result.get("expected_ev_pct", 0)
    kp = stake_result.get("kelly_star_pct", 0)
    kk = stake_result.get("kelly_k", 0.25)
    capped = " (cap)" if stake_result.get("capped") else ""
    return (f"💰 Stake: {st} {currency}  "
            f"(Kelly* %{kp:.1f}, x{kk} → {stake_result['kelly_used_pct']:.2f}%{capped})  "
            f"EV %{ev:+.1f}")
