# Deployment Gates

What goes live, what stays offline.

## LIVE (when `TJK_TOP4_SCIENTIFIC=1`)

These layers can run alongside the existing V7 pipeline as a SHADOW
read-only addition:

- Calibrated `p_*_cal` annotations in the forecast struct.
- Role labels (BANKER/CORE/SPREAD/CHAOS/AVOID/NO_SIGNAL).
- Race uncertainty level.
- No-bet recommendation.
- Forward log JSONL.
- AGF benchmark diagnostics (offline reports).
- Safer language renderer (no "insider", "kesin", etc.).

## OFFLINE ONLY (until walk-forward proves robust improvement)

- New specialist model weights.
- Draw bias features.
- New trainer/jockey shrinkage features.
- Plackett-Luce exact combo optimizer for ticket assembly.
- Aggressive EV-maximizing ticket optimizer.
- Retraining the V7 ensemble.

## Gating rule

A layer is "ready to flip on" only after:

1. Walk-forward backtest shows non-trivial calibration improvement
   (ECE down, Brier down) **and**
2. Forward log has ≥ 50 graded predictions covering the relevant
   segment **and**
3. The change is reversible by a single env-var flip.

Until then, the layer ships as a report or shadow log only.
