# SLC scoring calibration against the 2024 regular season, 2026-10-29

Exploratory calibration, not a predictive test. Model: the locked SLC v1 (`ad7e26d9`), with the play-call artifact fitted through
2023 and the play pool cut to 2022 and 2023 (cutoff 2024 week 1). Replay: `scoring_calibration_2024.py`, 5 seeds per game. Comparison:
`scoring_compare_2024.py`, raw output `SLC-SCORING-CALIBRATION-2024-COMPARE-2026-10-29.json`.

## Coverage

- Replay: 229 games, 2,290 team-games, 0 engine errors. 43 games were skipped because a team had no earlier depth chart (all of
  week 1) or no single RB1 in the depth data.
- Actual: 2024 regular season, weeks 2 to 18, 512 team-games from the database's play-by-play and schedule scores.

## Per team-game

| Measure | Replay | Actual 2024 | Difference |
|---|---|---|---|
| Points | 19.47 | 22.91 | -3.44 (-15%) |
| Drives (possessions) | 11.22 | 10.77 | +0.45 |
| Points per drive | 1.74 | 2.13 | -0.39 |
| Plays per drive (run and pass) | 6.51 | 5.83 | +0.68 |

Drive count is not the problem. The gap is in points per drive, and plays per drive run higher.

## Drive terminals per team-game

| Terminal | Replay | Actual | Difference |
|---|---|---|---|
| Touchdown | 2.00 | 2.56 | -0.56 |
| Field goal attempt (made and missed) | 2.17 | 2.02 | +0.15 |
| Punt | 4.15 | 3.73 | +0.42 |
| Turnover | 1.07 | 1.06 | 0.00 |
| Turnover on downs | 0.85 | 0.57 | +0.28 |
| Safety | 0.03 | 0.03 | 0.00 |

Taxonomy: the replay's `halftime` and `end_of_regulation` (0.95 together) and the actual `end_of_period` and `other` (0.79 together)
are period-ending possessions in both, so drive totals are comparable. Field-goal make rate is not in this summary (the drive record
keeps made or missed only in the play records, which this run did not store), so the field-goal contribution to points is not
quantified.

## Reading

- Touchdowns explain the points gap. Losing 0.56 touchdowns per team-game is worth about 3.9 points if each is worth 7, against a
  total gap of 3.4. Field goals, which run slightly high in attempts, and the missing extra points and two-point tries in the
  replay summary account for the remainder. Those are not separated here.
- Turnovers on downs run 0.28 per team-game above the actual rate, and punts 0.42 above. Both are decisions made at fourth down, not
  outcome draws. The fourth-down choice still uses the situation cell's historical share, which is a labelled fallback.

## What this does not establish

- Which transition layer causes the touchdown deficit. Candidates are the outcome draw from the situation cell (the historical play
  distribution, which is only partly conditioned on field position) and the fourth-down decision fallback. A targeted run that stores
  the decision and the outcome for each red-zone drive is needed to separate them.
- Whether the 2022 and 2023 pool, which is older than the 2024 season, explains part of the gap. Era differences are not controlled.
- Any predictive accuracy. This is a calibration check on the engine, and it is not used to tune the model on 2026 results.

## Next step

Run the replay with decisions and outcomes stored for red-zone drives, and compare the red-zone touchdown rate and the fourth-down go
rate with the 2024 actuals from the same play-by-play. That decides between the outcome draw and the fourth-down fallback.
