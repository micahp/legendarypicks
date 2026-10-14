# Tennis point model, step 1 (ATP), 2026-10-14

Status: v2. Recent form is added and kept. Rest is measured but not adopted, because the rest measure is invalid
(see below). ATP only. Nothing is in dev: the model reads the scratch ATP table. The work is on the local branch
`feat/tennis-point-model`, not pushed.

## The model

For a server X against a returner Y on surface s, the model gives P(X wins a point on serve).

- Surface baseline b_s: the cumulative serve points-won rate on s, from matches dated before the prediction. Before a
  surface has any history it uses 0.64.
- Serve rate of X: shrunk toward b_s with prior strength k points: (won + k * b_s) / (points + k).
- Return rate of Y: shrunk toward 1 - b_s the same way, using Y's points won when returning.
- Form: each player's serve and return counts are weighted by 0.5 ** (age / half-life), where age is in days. The
  half-life is 2 years. The counts are decayed lazily, when they are read or written.
- Combined on the odds scale, relative to the baseline:

      odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b_s)

- k = 250 points and the player half-life = 2 years. Both were chosen on the 2022 validation window from
  k in {100, 250, 500, 1000, 2000, 4000} and half-life in {0, 0.5, 1, 2} years (0 = cumulative).
- No calibration shift. Its effect on log loss was nil (see below).

## Data

ATP tour-level matches (levels G, M, A, F) from 2000, with serve stats present for the points that feed the model.
Matches without serve stats are not used as history. The source is the ATP mirror, licence CC BY-NC-SA 4.0
(decision D1 is open).

## Evaluation

- Walk-forward. Each match is predicted from matches dated before its date only. The whole date group is predicted
  before any of its results are added, so same-day matches don't inform each other.
- Validation: 2022, 3,991 matches. Test: 2023 to 2026, 13,831 matches and 2,155,571 served points.
- Metric: log loss per served point (lower is better), plus the mean predicted rate against the observed rate.

## Results on the test window

| Model | Log loss per point | Mean predicted | Observed |
|---|---|---|---|
| Surface baseline only | 0.654977 | 0.62884 | 0.63680 |
| Server's serve rate only | 0.653750 | 0.63502 | 0.63680 |
| Combined, cumulative (k = 500) | 0.653116 | 0.63376 | 0.63680 |
| Combined, form (half-life 2 years, k = 250), chosen | 0.652966 | 0.63681 | 0.63680 |
| Combined, form, with the validation shift (not used) | 0.652967 | 0.63722 | 0.63680 |

By surface, baseline against the chosen model (log loss per point):

| Surface | Baseline | Form model |
|---|---|---|
| Hard | 0.652087 | 0.649781 |
| Clay | 0.665117 | 0.663479 |
| Grass | 0.642331 | 0.640739 |

## Form: kept

Validation and test both improve, which is the rule. Validation: 0.655647 (cumulative) to 0.655524 (2-year
half-life). Test: 0.653116 to 0.652966.

The gain is small: 0.00015 per point on test (0.023%), and 0.0020 (0.31%) over the surface baseline. It is not steady
across half-lives. On both windows the 0.5-year half-life is worse than cumulative (test 0.653143), and the 1-year
and 2-year half-lives are better. The best value is at the edge of the grid, so a longer half-life was not tested.

The form model is level-calibrated on ATP without a shift: 0.63681 predicted against 0.63680 observed. The
validation-fitted shift (+0.0018 logit) left log loss unchanged (0.652967 against 0.652966), so it is not used.

## Rest: measured, not adopted

The fit ran, and both windows improved: validation in-sample 0.655524 to 0.655300, test 0.652966 to 0.652852. That
passes the letter of the rule. It is not adopted, because the feature does not measure rest.

- The data has no match dates. `tourney_date` is the event start, and every match a player plays in that event
  carries it. "Days since the last match" in the code is therefore days between event starts.
- The 0 to 3 day bucket is empty by construction. Only 14 of 17,611 consecutive event-start gaps (ATP, 2018 to 2022)
  are 3 days or fewer. Its coefficient stayed at 0.0 for that reason.
- The fitted coefficients (log-odds): server 4 to 7 days -0.024, 15 or more days -0.065, no earlier match -0.293;
  the returner's are -0.025, -0.055 and -0.170. The likely reading is that "no earlier match" marks debutants or
  unseen players, and "15 or more" marks players who skipped the previous event. Neither is fatigue.

To measure rest, match dates are needed. Options: a source with match dates; a within-event proxy from the round
(`round`), which needs an assumption about the days between rounds; or an explicitly redefined feature, "days since
the previous event start", with its own validation design.

## Limits

- The half-life is at the grid edge. A longer half-life has not been tested.
- Form works on event-start dates. A player's matches within one event don't inform each other, which loses
  information but cannot leak it.
- The surface baseline is cumulative. Keying it by tournament level was tested and not adopted (validation 0.65565
  to 0.65584; test 0.65312 to 0.65341).
- No tournament-level or best-of effects.
- The rest result is not evidence about rest.

## Commands

    python3 backend/tennis_point_model.py --db <scratch-atp.db> --tour atp \
      --validate-start 20220101 --test-start 20230101 --test-end 20261231

`--player-half-lives` sets the candidate player half-lives in years, with 0 for cumulative. The default is
`0,0.5,1,2`. Results are in the session scratchpad as `point-model-atp-formrest.json`.

## Next

1. Step 2, the simulator, is built on these point probabilities (see `TENNIS-MATCH-SIM-2026-10-14.md`).
2. Step 3, the match backtest against Elo, is frozen in `TENNIS-MATCH-BACKTEST-PROTOCOL-2026-10-14.md`.
3. Rest needs a decision: match dates, or an explicit redefinition with its own validation.
