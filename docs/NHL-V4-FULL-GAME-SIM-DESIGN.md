# NHL v4: stateful full-game simulator (deferred)

**Status:** Future design only. This is NOT v3 and not an implemented predictor.
The v3 scope is team/period shot creation and location/type-adjusted goalie
response, documented in `docs/NHL-V3-DESIGN-2026-10-20.md`. V4 consumes the
outputs of v3 and models the dynamic sequence of a game.

## Why v4 is separate

A period-level statistical forecast is not the same as a generative game
simulation. V4 must evolve the scoreboard, manpower, possession/chance
creation and player deployment through time, so live or final win probabilities,
score margins, totals, period markets and player props are internally coherent.

## State and transitions

At each simulated step maintain:
- game ID, period, game clock, home/away official and statistical scores,
  possession / zone if observable, current line combinations and goalies,
  fatigue and shift duration;
- active penalties, penalty type and remaining duration, manpower
  configurations (5v5, 5v4, 4v5, 5v3, 4v4, 3v3), pulled goalies and empty nets;
- score state, home ice, rest, pregame lineups, and uncertainty for an
  unknown starting goalie.

Transitions:
1. Draw penalty opportunities from league/team/score-state/period
   distributions, and model penalty start, expiration, overlap and
   minor-terminating PP goals correctly.
2. Draw team shot attempts and unblocked/on-goal events from v3
   period/score/manpower/line dependent intensity estimates.
3. Draw shot location/type/pre-shot context and goaltender-specific
   goal probability from v3 shot quality and goalie layer.
4. Attribute on-ice outcomes, score updates and optional player
   shots/goals/assists, with valid shift substitutions and real exposure.
5. Handle empty-net decisions, regulation end, 3v3 overtime and
   shootout winner/official score settlement explicitly.

V4 should model **both PP opportunities and exposure minutes**: one
opportunity is not always two full minutes. Power-play goals per game
are determined by opportunity rate, time at strength, shot creation,
and shot conversion. Model 5v4 separately from 5v3; distinguish
power-play, even-strength and short-handed goals.

## Data backfill

- Existing LP team game logs contain `powerplay_goals` and
  `powerplay_opps` aggregates; this supports a simple baseline.
- Backfill official NHL PBP penalties, goals, shots and event clocks,
  align NHL shift charts, and obtain location/shot danger from
  permitted sources. Inventory historical coverage by season instead
  of assuming all back to 2007-08 is complete.
- Maintain exact time provenance and record whether each feature
  would have been known at pregame decision time.
- Check source rights; MoneyPuck's bulk research downloads
  are not automatically licensed for commercial use.

## Evaluation

Compare against v2 and v3 simpler score models on matched, strictly
forward periods. In addition to ordinary Brier and log loss, inspect:
- score and goal distribution fit, winning margin / total tails,
  calibration on 1.5 puck lines and posted integer/half-point totals,
  first-/second-/third-period goals and PP goals;
- observed power-play opportunity counts and PP minutes/strength mix,
  penalty frequencies and OT/shootout frequencies;
- conditional player exposure and rates, line and goalie uncertainty,
  simulation reproducibility with seeded randomness;
- official market settlement including shootout-decider goal and pushes.

Monte Carlo sampling of an unchanged independent Poisson model is a
*control*, not evidence of new information. V4 must improve the
state transition model, not merely draw more samples from old priors.

The simulator may enhance decision quality, but **profitability is
evaluated only in a distinct trading experiment with executable prices,
fees, slippage, timestamps and selection bias controls**. Do not block
trading research on finishing V4.

## Deferred milestones

1. Audited NHL PBP + shift + manpower timeline backfill.
2. Event grammar and deterministic state transition tests.
3. League PP/PK/penalty opportunity model then team and unit effects.
4. Add v3 period/shot/goalie intensity priors to the state engine.
5. Implement regulation, OT, shootout, empty-net and accurate market settlement.
6. Run chronological calibration, matched baselines, seed reproducibility and
   only then consider an optional prospective research deployment.
