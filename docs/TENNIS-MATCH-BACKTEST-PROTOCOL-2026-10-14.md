# Tennis match backtest protocol (step 3), frozen 2026-10-14

Status: frozen before the match-level run. The rules below are the ones the run uses. Any change after the run is
reported as a change, with the numbers before and after.

## Question

Does the point model, passed through the simulator, predict match winners better than Elo, on the same matches,
walk-forward and out of sample?

## Data

- Dev database, read-only. `tennis_atp_matches` and `tennis_wta_matches`.
- Main-tour filters exactly as in `backend/tennis_point_model.py` (`TOUR_FILTER`). WTA includes the nine 2021
  and 2015 events named there, and excludes Parma 2021 and Buenos Aires 125 (both WTA 125s).

## Walk-forward

- Matches are processed in date order. Every match is predicted from matches dated before its date only.
  Matches on the same date do not inform each other: the whole date group is predicted before any of it is added.
- Test window: 2023-01-01 to 2026-12-31. Validation (2022) is not used here, since every choice was made on it
  already.

## Primary evaluation set

- `best_of` = 3.
- A score is present and complete: no `RET`, `W/O`, `DEF` or `ABD`.
- Both players are identified (`winner_id`, `loser_id`).
- Best-of-five matches, and matches with incomplete scores, are counted and reported, but not scored.

## Side assignment and target

- For each match, the labels A and B are assigned by a seeded random draw (seed 20261014). A is the winner with
  probability one half. The target is `y = 1` if A won. This stops the target from being "the winner".

## Point model inputs

- The form model from step 1 with player half-life 2 years and k = 250 points, chosen on validation for ATP and WTA.
  Uncalibrated for both tours. The validation-fitted logit shift is not used: it made no difference to log loss on
  either tour.
- Surface baseline: cumulative, as in step 1. Rest is not used. Its measurement is invalid (see the step 1 notes).
- History comes only from matches with serve statistics. A match's own statistics are never used to predict it.

## Simulator inputs

- `serve_A` = point_prob(serve rate of A, return rate of B, surface baseline). `serve_B` likewise, with the roles
  swapped. These are P(A wins a point on A's serve) and P(B wins a point on B's serve).
- Match probability = the average of the two first-server cases. Who serves first is not known in advance.
- Format: standard best-of-three. Every set is decided by a 7-point tiebreak at 6-6, and the final set too.
- A match whose third-set score is bracketed in the data (a match tiebreak such as `[10-8]`) uses a 10-point match
  tiebreak in place of the third set. The bracket is the only signal used for format.

## Elo baseline

- Standard Elo: starting rating 1500, K = 32 for every match, no surface term, no margin term.
- Updated from all main-tour matches in date order, including best-of-five and incomplete matches.
- Predictions use the ratings from before the date group, and the updates use the same pre-group ratings.

## Metrics

- Primary: log loss per match.
- Secondary: Brier score; calibration in ten equal-width bins on the predicted probability; the mean predicted
  minus the mean observed.
- Paired bootstrap 95% interval for the log-loss difference, simulator minus Elo: 1,000 resamples, seed 20261014.
- Breakdowns: by tour, by year, by surface, and by history depth. Depth is the minimum of the four effective point
  counts (A's serve and return, B's serve and return) on the surface, using the decayed counts the estimate uses.
  Thin is below 300 points, middling is 300 to 1,499, deep is 1,500 or more.
- Coverage: matches with and without serve statistics in the match itself. Both are scored, and both are reported.

## Decision rules (fixed now)

- P1, predictive value: for each tour, simulator log loss is lower than Elo log loss, and the 95% paired interval
  for (simulator minus Elo) lies entirely below zero.
- P2, calibration: for each tour, the largest |observed minus predicted| over bins with at least 200 matches is at
  most 0.03, and |mean predicted minus mean observed| is at most 0.01.
- P3, stability: for each tour, the simulator beats Elo in at least 3 of the 4 test years.
- S, simulation correctness: `python3 backend/tennis_match_sim.py --verify 50000` has max |z| below 4.5 in every case,
  and the simulator unit tests pass. This decision is separate from the predictive ones.
- L, licence: not assessed by this test. D1 (CC BY-NC-SA 4.0) is still open. This test covers research use only.

Decision mapping:

- The simulator is a GO for research if S holds.
- The complete system (point model plus simulator) "adds predictive value" if P1, P2 and P3 all hold on both tours.
- If P1, P2 or P3 fails on either tour, the predictive claim is a NO-GO, and the simulator stays research code.

## Limits, stated before the run

- The 2023 to 2026 window was already used for the step 1 point-level results. This is not an untouched holdout.
  A clean check needs matches played after this freeze, scored prospectively.
- Retirements, walkovers and defaults are excluded. This makes the match easier to model than live play.
- Mapping these player ids to Legendary Picks players is not part of this test.
- The match-level test does not show that the probabilities are right for betting. A price, a market and a
  commission are not part of this test.
