# Ticket Construction

Tickets are proposals. The proposal layer never bets.

## Modes

- **no_bet** — skip the race.
- **small** — 2 BANKER + 2 CORE + 1 SPREAD (5 horses max).
- **balanced** — 2 BANKER + 3 CORE + 2 SPREAD + 1 CHAOS (≤8 horses).
- **wide** — 2 BANKER + 4 CORE + 3 SPREAD + 2 CHAOS (≤11 horses).

When the dedup'd set has fewer than 4 horses, the proposal is
auto-converted to `no_bet` with reason "fewer than 4 horses with signal".

## Stake-cap guidance

- `small` mode → `stake_cap_suggestion="small"`.
- `balanced` mode → `stake_cap_suggestion="small"`.
- `wide` mode → `stake_cap_suggestion="small_only"` (cap stake per
  ticket even though structure is wide).
- `no_bet` → `stake_cap_suggestion="none"`.

The system does NOT compute Kelly stakes. Kelly requires (a) a calibrated
probability and (b) a real bookmaker payout. Pari-mutuel payouts in TR
are only known post-race and are structurally -EV (see audit/67). Until a
Betfair adapter exists, the engine emits stake **suggestions**, not orders.
