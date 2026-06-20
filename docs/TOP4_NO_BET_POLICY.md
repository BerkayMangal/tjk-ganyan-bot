# No-Bet Policy

The engine deliberately emits NO_BET frequently. This is a feature, not
a bug. In a structurally -EV pari-mutuel market (TR Tote), the only
sustainable strategies are (a) abstain from races without an edge or
(b) move to a +EV venue (Betfair exchange).

## Hard NO_BET triggers

1. Required candidate-set size ≥ `max(8, 0.6 * field)` on a field ≥ 14.
2. Race-level uncertainty `CHAOS` AND zero BANKER.
3. Structure: 0 BANKER, ≤1 CORE, required set ≥ 7.
4. Fewer than 4 horses carry any signal (calibration absent, no AGF).

## Soft downgrades

- Flat AGF entropy (public has no opinion) → drop one confidence level.
- Calibration `method="insufficient_data"` for the top-3 horses →
  drop confidence to LOW.

## What the user sees

The Telegram message includes:

```
🛑 NO-BET (öneri): <reasons>
Not: bu bir tahmin/araştırma çıktısıdır, otomatik bahis YOK.
```

The user remains the decision-maker. NO_BET is a recommendation, not
an enforcement.
