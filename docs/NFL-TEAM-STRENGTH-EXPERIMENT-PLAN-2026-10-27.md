# NFL team-strength experiment plan: incremental Brier improvement (v1)

Status: plan only, for review. No model is trained, no forecast is written, and no production output changes. Dev-only.
The 2026 season is the sealed holdout. It is not used to choose, tune or confirm anything.

Depends on: `NFL-TEAM-BOX-SCORE-SCHEMA-2026-10-27.md` (the box score) and `NFL-SITUATIONAL-STATE-CONTRACT-2026-10-27.md`
(the pregame layer and the cutoff rule).

## 1. Question

Does each addition of situational information improve forecasts on games that were not used to select it?

| Model | Pregame information | Testable on history? |
|---|---|---|
| S0 | The existing Legendary Picks game-winner baseline | Not from the database (see section 2) |
| S1 | Opponent-adjusted team strength, recent form, home or away | Yes |
| S2 | S1 plus calendar (weekday, kickoff window), rest and travel | Yes |
| S3 | S2 plus venue (roof, surface, dated capacity), officials, and weather forecasts | Venue and officials yes (publication time for officials unknown, so a sensitivity case); weather forecasts no until archived forecasts exist (E1) |
| S4 | S3 plus frozen expected-starter availability | No for history. The availability snapshots start in 2026. S4 can be tested only on frozen 2026 weeks, which are the sealed holdout |
| S5 | S4 plus player-strength priors, possibly including Madden ratings | After the Madden inventory, and only where the edition and the dates match the season |

The plan states up front which steps can run now. The rest are marked as blocked, not approximated.

## 2. The S0 problem

The database stores game-winner predictions for 2026 only. `game_projections` has 168 NFL rows, all for 2026. The graded
results in `projection_grades` (124 rows) are also 2026 only, and they cover several model versions. No historical
NFL game-winner forecast for 2010 to 2025 exists in the stored tables. The `game_projections` table also carries market
spreads and totals. Those columns stay out of any independent comparison.

Two options, and a decision is needed before S0 can be tested:

- S0a, reconstructed: rerun the existing NFL model code on historical data, under the cutoff rule. This requires an audit
  of the code's inputs and of whether it can run without future information. It is the faithful baseline.
- S0b, documented simple baseline: home advantage plus each team's prior-game margin average, with the cutoff rule. This
  is not the existing model. It is a reference point that every model must beat.

The 2026 grades cannot serve as a historical comparison for choosing a model. They are holdout data, so they may be
used only in the final sealed evaluation, once, after the model is fixed.

## 3. Eligible games

- Regular-season team games that are completed, with a final score, from 2010 onward. Postseason games are a separate
  stratum, reported but not pooled into the main test.
- Each team must have at least four prior regular-season games in the same season before a game can be scored by a
  strength model. Earlier games in a season are reported as a separate, unscored stratum. This is a rule, not a fallback.
- A game is eligible for a strict test only if every field the model uses has a known pregame time before the cutoff
  (contract, section 3). The list is written once, before any model runs, and every model uses the same list.
- Ties are excluded from the binary Brier score and reported separately. The count of ties is part of the report.

## 4. Chronological splits

| Split | Seasons | Use | Rule |
|---|---|---|---|
| Fit | 2010 to 2017 | Estimate team strength and the model parameters | Only prior-game information within the fit window |
| Validation | 2018 to 2020 | Choose among variants, with rolling-origin refits | Each season scored by a model fitted only on earlier seasons |
| Final test | 2021 to 2025 | Evaluate the chosen model once | Fixed model, no refitting on test games |
| Sealed holdout | 2026 | Final sealed evaluation only, after the model is frozen | Not opened during model development |

COVID-affected 2020 is in validation, and its crowd and attendance fields are flagged. The split boundaries are fixed here,
before any result is seen. Changing them requires a new version of this plan.

## 5. Metrics

- Winner Brier score: mean of (predicted home win probability minus the home team's result, 1 or 0) squared. The constant
  50/50 forecast scores 0.2500, which is the reference. Lower is better.
- Log loss, with probabilities clipped to 0.001 and 0.999.
- Calibration: reliability bins with at least 20 games each, and the calibration slope from a logistic recalibration.
- Score and margin distribution: CRPS of the predicted margin distribution against the actual margin. The binary Brier
  score does not apply to scores or margins.
- Game-level coverage: the share of eligible games scored, by season and by stratum.
- Condition breakdown: Brier by condition with its sample size and a bootstrap interval. Examples from the request:
  Sunday early against primetime, high wind against calm, confirmed QB1 against replacement QB. A condition with fewer than
  30 games is shown but not interpreted.

## 6. Decision rules (proposed, to be calibrated)

A model Sk replaces S(k-1) only when all of the following hold on the final test:

1. The Brier improvement over S(k-1) is at least 0.003. This threshold is proposed. It is to be checked against the spread
   of Brier differences in the validation seasons before the test runs, and revised there if it is too loose or too tight.
2. The 95 percent interval for that improvement, from a bootstrap that resamples whole weeks, excludes zero.
3. Calibration does not get worse: the slope stays between 0.9 and 1.1, and no reliability bin with at least 30 games
   misses its mean by more than 0.10.
4. The CRPS of the margin distribution does not get worse.
5. No condition with at least 60 games worsens by more than 0.01, unless the change is named in the report and explained.

A model that passes all five is kept as the candidate for the sealed 2026 evaluation. It is not promoted by that
evaluation alone.

Multiple comparisons: the condition breakdown is a family of tests. Report it with Benjamini-Hochberg control, as the
earlier team-adjusted families were. A condition that does not survive the correction is reported as descriptive.

## 7. What the test can resolve

With about 272 games a season over five seasons, the final test has roughly 1,360 games. Brier differences between nested
models are small, and their standard error is roughly 0.002 to 0.004 for a test of this size. The plan can therefore
detect improvements of about 0.005 and larger with reasonable confidence. It cannot reliably detect a 0.001 change, and
the report will say so.

## 8. Steps and gates

1. Resolve S0 (section 2). Gate: a documented S0, either reconstructed or simple, with its inputs listed.
2. Build the eligible-game list and the pregame fields for each game under the cutoff rule. Gate: every field has a
   time basis, and the count of fields with unknown time is reported.
3. Fit S1 on the fit seasons, score the validation seasons, and calibrate the threshold in section 6. Gate: the
   threshold check passes or is revised with a written reason.
4. Add S2, then S3, each scored the same way on validation. Gate: each step improves validation, or it stops there.
5. S4 is blocked for history. Record it as blocked. Run it only if a historical availability source appears.
6. S5 waits for the Madden inventory. Gate: the edition, the season match and the publication dates are verified for every
   season used. A rating revised after kickoff is excluded.
7. Run the chosen model once on the final test seasons. Report every metric in section 5.
8. Only after that, and only once, score the sealed 2026 season with the frozen model. The result is reported whatever it
   shows, and it does not change the model.

## 9. What would stop the plan

- S0 cannot be reconstructed and the simple baseline is not agreed. Then no comparison against the existing model is made,
  and the report says so.
- More than a fifth of the eligible games lack a field the model needs. Then the affected model is not tested on that
  stratum, and the coverage figure is reported.
- A reported improvement disappears when the cutoff margin is changed from 24 hours to 12 or 48. Then it is not counted.

## 10. Madden ratings

The Madden step is an inventory first: the edition for each season, the attributes available, the publication dates, the
player identifiers, the source terms and the coverage. Ratings enter a model only as cutoff-eligible priors, weighted by
expected workload. They are compared to the same model without them. Coefficients are never inserted directly, and current
ratings are never used for a past season.
