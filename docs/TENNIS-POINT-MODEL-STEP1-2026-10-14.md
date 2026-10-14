# Tennis point model, step 1 (ATP), 2026-10-14

Status: v1 is built and evaluated on the ATP scratch database. ATP only. Nothing is in dev. The work is on
the local branch `feat/tennis-point-model`, not pushed.

## The model

For a server X against a returner Y on surface s, the model gives P(X wins a point on serve).

- Surface baseline b_s: the cumulative serve points-won rate on s, from matches dated before the prediction.
  Before a surface has any history it uses 0.64.
- Serve rate of X: shrunk toward b_s with prior strength k points: (won + k*b_s) / (points + k).
- Return rate of Y: shrunk toward 1 - b_s the same way, using Y's points won when returning.
- Combined on the odds scale, relative to the baseline:

      odds(P) = odds(serve_X) * odds(1 - return_Y) / odds(b_s)

  Two players at baseline give P = b_s. A better serve raises P. A better return lowers it.

k = 500 points. It was chosen on the validation year from {100, 250, 500, 1000, 2000, 4000}, and the curve is
flat between 250 and 1000.

## Data

ATP tour-level matches (levels G, M, A, F) from 2000, with serve stats present. Sides without serve stats
(5.6%) are excluded. The source is the ATP mirror, licence CC BY-NC-SA 4.0 (decision D1 is open).

## Evaluation

- Walk-forward. Each match is predicted from matches dated before its date only. Results are added after
  every match on that date has been predicted, so same-day matches don't inform each other.
- Validation: 2022, 3,991 matches. This window selects k.
- Test: 2023 to 2026, 13,831 matches and 2,155,571 served points. Scored once, with k = 500.
- Metric: log loss per served point (lower is better). Also the mean predicted rate against the observed rate.

## Results on the test window

| Model | Log loss per point | Mean predicted | Observed |
|---|---|---|---|
| Surface baseline only | 0.65498 | 0.6288 | 0.6368 |
| Server's serve rate only | 0.65386 | 0.6329 | 0.6368 |
| Combined (serve and return) | 0.65312 | 0.6338 | 0.6368 |

By surface, baseline against combined (log loss per point; mean predicted against observed):

| Surface | Baseline | Combined | Predicted | Observed |
|---|---|---|---|---|
| Hard | 0.65209 | 0.64992 | 0.6395 | 0.6426 |
| Clay | 0.66512 | 0.66363 | 0.6148 | 0.6181 |
| Grass | 0.64233 | 0.64092 | 0.6557 | 0.6581 |

A rolling two-year baseline was also tried. It was slightly worse (combined 0.65320, mean predicted 0.6306),
so the default is the full history.

## What the numbers say

- The combined model improves log loss by 0.00186 per point over the surface baseline, about 0.28%. Player
  serve rates account for about 0.0011 of that, and returners for about 0.0007.
- The model still under-predicts the test rate by about 0.003. Most of that gap is on Hard. Serve rates have
  risen since the training years, and a cumulative baseline is slow to follow the trend.
- The per-point gain is small. Its value depends on how it compounds in the simulator, which step 2 builds.

## Not in v1

- Recent form and rest, the brief's small adjustments.
- A time trend in the baseline, or a time-varying one, to close the remaining 0.003 gap.
- WTA. It waits on the tour-level decision (D4). Women's tourney_level codes differ from men's.
- Dev DB. Nothing was written. The model reads the scratch ATP table.

## Commands

    python3 backend/tennis_point_model.py --db <scratch-atp.db> --tour atp \
      --validate-start 20220101 --test-start 20230101 --test-end 20261231

Add `--baseline-years 2` for the rolling baseline. Results are in the session scratchpad as
`point-model-atp-wf-b0.json` (full history) and `point-model-atp-wf-b2.json` (two years).

## Next

1. Close the remaining calibration gap, with a time trend in the baseline or a rolling baseline with a longer window.
2. Add recent form and rest as small adjustments.
3. Step 2: the game, set and match simulator, built on the point probability.
4. Step 3: a chronological backtest against Elo.
