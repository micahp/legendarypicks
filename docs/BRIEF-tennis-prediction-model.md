# BRIEF — Tennis match prediction model

## Question
For a given player pair on a given surface and format, how likely is each player to win a point when serving against this opponent, and what does that imply for match winner, set score, total games, tiebreaks and aces?

## Build order
1. Point model: estimate P(A wins a point on serve vs B) and P(B wins a point on serve vs A). Start from surface-specific serve and return points-won rates, adjusted for opponent strength, with recent form and rest as small adjustments.
2. Game, set and match simulator: hold probabilities from the point model, tiebreaks at 6-6, best-of-3 and best-of-5 scoring. Output win probability, set-score distribution, total games, and tiebreak and three-set probabilities.
3. Validation: chronological backtest against an Elo-only baseline, scored on calibration and log loss. No betting-edge claim until calibration holds.
4. Props later: expected service points times ace rate for aces; break and double-fault rates after that.

## Constraints
- Data in this repo is for research. Do not assume commercial licence for Match Charting Project or Tennis-Data; flag any source you use in the report.
- Predict points first, not winners. Every market comes from one simulator.
- Store aces, double faults and service points per match from the start.
- Measure before you claim. Report each number with its sample size.

## Start here
- `docs/TASK-tennis-set-scores.md` (per-set scores already flow from ESPN)
- Existing tennis spine and name-resolution work: branches `feat/tennis-spine`, `fix/tennis-unmatched-names`, `fix/tennis-unresolved-queue`

## Deliverable
A short written report in `docs/` on what the data supports, the point model's chronological backtest against Elo, and a go or no-go for the simulator.
