# Rolling-origin validation and incumbent selection: protocol

- **Written:** 2026-10-18, before any rolling result was computed.
- **Status:** Development. The 2015 to 2026 window was used by earlier replays and backtests, including the
  2023 to 2026 window, so no year is an untouched holdout. This protocol gives CP2 evidence only. It does not
  give CP4 evidence.
- **Branch:** `feat/tennis-track-b-2026-10-18`.

## Question

For each target the brief names, which model is the incumbent? Every candidate is scored on identical rows.
Each year Y is forecast using only information dated before Y, and the walk-forward runs through 2026.

## Targets, references and primary scores

| Target | Reference (incumbent unless beaten clearly) | Candidates | Primary score (lower is better) | Secondary |
|---|---|---|---|---|
| Match winner | M1 global Elo, K = 32, no surface term | M2 on 2000 history (same ratings as M1 plus surface Elo); M2 as deployed (history from 2020-01-01); constant 0.5 (floor) | Brier per match | Log loss |
| Total games | Direct format-only histogram (prior-only) | Direct format plus surface; direct format plus surface plus Elo competitiveness; current point simulator with exact scoring | CRPS on the discrete total | Log score; mean absolute error; coverage |
| Aces (per player-match) | C0: prior calendar-year tour and surface mean per player-match, Poisson | P0 Poisson; P0 Gamma-Poisson; P1 Poisson; P1 Gamma-Poisson (from the replay) | CRPS | Log score |
| Double faults (per player-match) | C0, as above | P0 Poisson; P0 Gamma-Poisson; P1 Poisson; P1 Gamma-Poisson | CRPS | Log score |

Constant 0.5 is the no-information floor for the winner (CP1). It is listed as a candidate so that it appears in
the table, but it cannot become the incumbent unless the reference is worse, which the table will show.

E2 is a candidate only if it can be reproduced exactly from committed code and frozen parameters. Otherwise it is
excluded, and the reason is recorded in the report.

## Populations and rows

- **Winner:** completed best-of-three main-tour matches with a recorded surface, the population of
  `backend/tennis_match_backtest.py`. Every model is scored on the same matches.
- **Total games:** the population of `backend/tennis_total_games_backtest.py` (completed, scoreable best-of-three
  format). The histogram start is moved from 2022 to 2000 by overriding the module constant, so that 2015 to 2021
  have prior data. Grand Slam matches before 2022 stay excluded, as in the source module.
- **Counts:** the population of `backend/tennis_props_rate_backtest.py`, with the replay's per-target validity rules.
  The replay runs from 2014 so that C0 has a prior calendar year for 2015. Scores for 2015 to 2026 do not change.

Sides are randomized for the winner and the counts. Total games are symmetric in the two players.

## Rolling origin

- Years evaluated: 2015 to 2026 (2026 is partial, to May).
- A match dated D is forecast from state that includes only matches dated before D. Matches on the same
  event-start date do not inform each other, as in the source code.
- C0 uses the prior calendar year only.

## Intervals

- Paired difference, candidate minus reference, on identical rows.
- Match-clustered bootstrap: cluster = match (both player rows of one match share a cluster for the counts).
  1,000 resamples, seed 20261018 for each slice.
- Tournament-clustered intervals are reported as a sensitivity only.
- Per-year intervals use only that year's matches.

## Selection rule (pre-declared)

Applied to both tours pooled, for each target separately.

1. **Clear win over the reference.** A candidate clearly beats the reference when its pooled primary-score
   difference (candidate minus reference) has a match-clustered 95% interval entirely below zero, and the
   difference is negative in at least 9 of the 12 evaluated years.
2. **Top candidate.** Among candidates that clearly beat the reference, the top candidate has the lowest pooled
   primary score. The runner-up is the next-lowest candidate overall, which may be the reference.
3. **Incumbent.** The top candidate becomes the incumbent only if its difference from the runner-up has a
   match-clustered 95% interval entirely below zero and is negative in at least 9 of 12 years.
   Otherwise the simpler of the top candidate and the runner-up becomes the incumbent. Simplicity order:
   - winner: M1 is simpler than both M2 variants; the floor is simplest of all;
   - total games: format-only, then format plus surface, then format plus surface plus competitiveness, then the simulator;
   - counts: C0, then Poisson rate, then Gamma-Poisson rate, then Poisson exposure, then Gamma-Poisson exposure.
4. **No clear win.** If no candidate clearly beats the reference, the reference stays the incumbent. The table
   and the report say so.
5. **Tour check.** The pooled incumbent's sign is also reported for ATP and WTA separately. A sign flip on one
   tour is reported as a caveat. It does not change the selection.

## M2 fate rule

M2 as deployed is "validated" only if it passes rule 1 against M1 with the same criteria, or it is selected under
rule 3. Otherwise it is recorded as **unvalidated in production**, which is a defect of the lock table, not a
validated status. If M2 on 2000 history passes but M2 as deployed does not, the report records a version
mismatch. The deployed history start (2020-01-01) is then part of the defect.

## E2 rule

E2 is included only if all of these hold:

- its row-level predictions can be regenerated from committed code and frozen parameters;
- the regeneration reproduces an already published aggregate exactly (for example `e2_mae` in
  `research/tennis/props/2026-10-14/e2-exposure-diagnostics.json`); and
- its count distributions (P1 negative binomial, X_bbin) can be computed from committed code.

Otherwise E2 is excluded, with the reason stated.

## Verification anchors (the run stops if any fails)

- M1 on 2023 to 2026, ATP: Brier 0.22802 with n = 11,777. WTA: 0.21596 with n = 13,066.
- Simulator total-games CRPS on 2023 to 2026: ATP 3.5327, WTA 3.5572 (values in
  `research/tennis/total-games/2026-10-16/{atp,wta}.json`). The simulator does not depend on the histogram start, so this must match exactly.
- Replay headline GP CRPS: ATP aces P0 2.0505 and P1 1.9934; ATP double faults P0 1.1047 and P1 1.0955; WTA aces
  P0 1.2221 and P1 1.2005; WTA double faults P0 1.3444 and P1 1.3308.

## Stated limits

- The incumbent is a development result. Prospective grading (CP4) is still open.
- Pooled results over 12 years are dominated by the years with the most matches, and the 2026 year is partial.
- The rule is written for these targets only. It is not a general standard.
