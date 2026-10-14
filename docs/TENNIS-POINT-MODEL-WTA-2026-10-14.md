# Tennis point model, WTA main tour (step 1), 2026-10-14

Status: v1 for WTA, on the main-tour rule approved on 2026-10-14. It reads the dev DB read-only, and it writes
nothing to dev. The work is on the local branch `feat/tennis-point-model`, not pushed.

## The rule

Main tour = `tourney_level` in G, F, P, PM, I, T1 to T5, or `W` dated before 2010.

- Excluded: `C` (WTA 125 events from 2018, and ITF events from 1983 to 1995), `CC` (low-tier circuits), the numeric
  ITF prize-money codes, `D` (team competitions), `O` (Olympics), `E` (exhibition), `J` (juniors) and the `+H` codes.
- Held out for review: `W` from 2010 onward. That's 11 events and 436 matches, including the 2015 WTA Finals and
  "Buenos Aires 125" (2024).
- Check: no event whose name contains "125" passes the rule.

## Data

Main-tour matches from 2000, with serve stats present. Validation is 2022 with 3,706 matches. Test is 2023 to 2026
with 13,264 matches and 1,880,683 served points.

## Model

Same as the ATP model: a surface baseline, serve and return rates shrunk toward it with k = 500 points,
combined on the odds scale, with a validation-fitted logit shift. Walk-forward evaluation. Time weighting was
tested with half-lives of 0.5 to 4 years. Validation loss was flat across them (0.68328 to 0.68331), so the
cumulative baseline was chosen, as for ATP.

## Results on the test window

| Model | Log loss per point | Mean predicted | Observed |
|---|---|---|---|
| Surface baseline only | 0.68468 | 0.5604 | 0.5643 |
| Server's serve rate only | 0.68368 | 0.5644 | 0.5643 |
| Combined (serve and return) | 0.68319 | 0.5651 | 0.5643 |
| Combined, calibrated | 0.68319 | 0.5654 | 0.5643 |

By surface, baseline against combined (log loss per point):

| Surface | Baseline | Combined |
|---|---|---|
| Hard | 0.68437 | 0.68271 |
| Clay | 0.68818 | 0.68687 |
| Grass | 0.67873 | 0.67778 |

## Reading the results

- The combined model improves log loss by 0.00149 per point over the surface baseline, about 0.22%. ATP's improvement
  was 0.00186, about 0.28%.
- The serve-point win rate is about 0.564 for WTA, against about 0.637 for ATP. That's the expected gap between the two tours.
- The calibration shift is not useful here. On validation the uncalibrated model was 0.0003 under, which gave a
  logit shift of +0.0014. On the test years the uncalibrated model is 0.0008 over, so the shift widens the gap to
  0.0011. Log loss doesn't change. Keep the uncalibrated model for WTA until a longer validation window supports a shift.

## Per-level baseline: tested, not adopted

Keying the baseline and shrinkage by tournament level made WTA worse. Validation log loss rose from 0.68328 to 0.68363.
On test, the combined log loss rose from 0.68319 to 0.68363. The calibration gap was about the same, +0.0005 against +0.0008.
The cumulative surface baseline stays, as for ATP.

## Limits

- The 11 held-out `W` events from 2010 onward are out until someone reviews them.
- `C` includes WTA 125 events from 2018, about 7,262 matches. The rule excludes them. A separate lower-tier category could
  use them later, as the reply suggested, but that's not part of this model.
- Team competitions and the Olympics are excluded.
- No form, rest, tournament-level or best-of effects yet.
- The loader stores the raw codes. The rule is applied in the model.

## Commands

    python3 backend/tennis_point_model.py --db <dev DB, read-only> --tour wta \
      --validate-start 20220101 --test-start 20230101 --test-end 20261231

Results are in the session scratchpad as `point-model-wta.json`.

## Next

1. Review the 11 held-out `W` events from 2010 onward.
2. (Per-level baseline tested on both tours and not adopted; see above.)
3. Recent form and rest as small adjustments, for both tours.
4. Step 2, the simulator, built on these point probabilities.
