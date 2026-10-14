# Tennis point model, step 1 (ATP), 2026-10-14

Status: v1 is built and calibrated on the ATP scratch database. ATP only. Nothing is in dev. The work is on
the local branch `feat/tennis-point-model`, not pushed.

## The model

For a server X against a returner Y on surface s, the model gives P(X wins a point on serve).

- Surface baseline b_s: the cumulative serve points-won rate on s, from matches dated before the prediction.
  Before a surface has any history it uses 0.64. An exponentially weighted baseline is also available (see below).
- Serve rate of X: shrunk toward b_s with prior strength k points: (won + k*b_s) / (points + k).
- Return rate of Y: shrunk toward 1 - b_s the same way, using Y's points won when returning.
- Combined on the odds scale, relative to the baseline:

      odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b_s)

  Two players at baseline give P = b_s. A better serve raises P. A better return lowers it.
- Calibration: a single logit shift, fitted so that the predicted rate on the validation year equals the observed rate.

k = 500 points, chosen on the validation year from {100, 250, 500, 1000, 2000, 4000}. The curve is flat
between 250 and 1000.

## Data

ATP tour-level matches (levels G, M, A, F) from 2000, with serve stats present. Sides without serve stats
(5.6%) are excluded. The source is the ATP mirror, licence CC BY-NC-SA 4.0 (decision D1 is open).

## Evaluation

- Walk-forward. Each match is predicted from matches dated before its date only. Results are added after every
  match on that date has been predicted, so same-day matches don't inform each other.
- Validation: 2022, 3,991 matches. This window chooses k, the half-life and the calibration shift.
- Test: 2023 to 2026, 13,831 matches and 2,155,571 served points. Scored once with those choices.
- Metric: log loss per served point (lower is better). Also the mean predicted rate against the observed rate.

## Results on the test window

| Model | Log loss per point | Mean predicted | Observed |
|---|---|---|---|
| Surface baseline only | 0.65498 | 0.6288 | 0.6368 |
| Server's serve rate only | 0.65386 | 0.6329 | 0.6368 |
| Combined (serve and return) | 0.65312 | 0.6338 | 0.6368 |
| Combined, calibrated | 0.65310 | 0.6358 | 0.6368 |

The calibration shift is +0.0087 on the logit scale. It was fitted on 2022, where the uncalibrated model predicted
0.6297 against an observed 0.6318. The same shift takes the test-window gap from 0.0030 to 0.0010. It barely
changes log loss, so the model's value lies in discrimination, not calibration.

By surface, baseline against combined (log loss per point; mean predicted against observed):

| Surface | Baseline | Combined | Predicted | Observed |
|---|---|---|---|---|
| Hard | 0.65209 | 0.64992 | 0.6395 | 0.6426 |
| Clay | 0.66512 | 0.66363 | 0.6148 | 0.6181 |
| Grass | 0.64233 | 0.64092 | 0.6557 | 0.6581 |

## Time weighting: tested, not chosen

An exponentially weighted surface baseline was tested with half-lives of 0.5, 1, 2 and 4 years. The cumulative
baseline was chosen. Validation log loss was 0.65565 to 0.65568 across all five settings, so the choice made
no real difference there.

| Half-life (years) | Test combined log loss | Test mean predicted |
|---|---|---|
| 0 (cumulative, chosen) | 0.65312 | 0.6338 |
| 0.5 | 0.65321 | 0.6301 |
| 1 | 0.65319 | 0.6308 |
| 2 | 0.65317 | 0.6313 |
| 4 | 0.65315 | 0.6319 |

The weighted baseline itself is correct. At the start of 2023 its Hard value, 0.6366 at a half-life of 0.5 years,
matches the realised 2022 Hard rate of 0.6369. The shift is in the combined predictions, not in the baseline.

## What the numbers say

- Player serve rates add about 0.0011 per point over the surface baseline, and returners about 0.0007.
  The combined model improves on the baseline by 0.0019 per point, about 0.28%.
- Calibration leaves a residual gap of about 0.001 on the test window. The shift is fitted on one year, so it should
  be refitted as new data arrives.
- Serve rates rose within every tour level from the training years to 2023 to 2026. Grand Slams rose about 0.4
  points, Masters about 0.9 and 250/500-level events about 1.1. The match mix changed too, with fewer 250/500-level
  matches in the test window.
- The per-point gain is small. Its value depends on how it compounds in the simulator, which step 2 builds.

## Per-level baseline: tested, not adopted

The surface baseline and the shrinkage were also keyed by tournament level (G, M, A, F). Validation log loss
rose from 0.65565 to 0.65584. On test, the uncalibrated log loss rose from 0.65312 to 0.65341, and the calibration gap
widened from +0.0030 to +0.0037. The cumulative surface baseline stays. This test didn't shrink the level baseline toward
the surface baseline, so a hierarchical version could behave differently. That's left open.

## Not in v1

- Recent form and rest, the brief's small adjustments.
- Tournament level or best-of effects in the baseline. A per-level baseline is the next candidate for the remaining gap.
- WTA. It waits on the tour-level decision (D4). See the proposed allowlist in the WTA loader document.
- Dev DB. Nothing was written. The model reads the scratch ATP table.

## Commands

    python3 backend/tennis_point_model.py --db <scratch-atp.db> --tour atp \
      --validate-start 20220101 --test-start 20230101 --test-end 20261231

`--half-lives` sets the candidate half-lives in years, with 0 for cumulative. The default is `0,0.5,1,2,4`.
Results are in the session scratchpad as `point-model-atp-cal2.json`.

## Next

1. (Per-level baseline tested and not adopted; see above.)
2. Recent form and rest as small adjustments.
3. Step 2: the game, set and match simulator, built on the point probability.
4. Step 3: a chronological backtest against Elo.
