# Where the 2024 scoring deficit comes from, 2026-10-29

Replay: `scripts/nfl_sequence/scoring_redzone_2024.py`, 2 seeds per game, weeks 2 to 18, exploratory (cutoff 2024 week 1). Actual:
2024 regular season, same weeks, from play-by-play. Raw output: `SLC-SCORING-REDZONE-2024-2026-10-29.json`.

Definitions: a red-zone trip is a drive that reaches 20 yards or closer at any scrimmage play. Fourth-down go means a run or pass on
down 4. Converted means the next play in the drive is first down (the play-by-play has no conversion column, so the same test is
applied to both sides).

## Measured

| Measure | Replay | Actual | Difference |
|---|---|---|---|
| Red-zone trips per team-game | 3.29 | 3.94 | -0.65 (-16%) |
| Touchdown per red-zone trip | 0.485 | 0.623 | -0.14 |
| Field-goal attempt as trip ending | 34% | 27% | +7 points |
| Fourth-down go rate | 21.5% | 18.8% | +2.7 points |
| Fourth-down conversion | 41.3% | 46.6% | -5.3 points |

Touchdowns per team-game from trips: replay 1.60, actual 2.45, a gap of -0.85. The total touchdown gap is -0.56, because the replay
also records a few touchdowns from other terminals, which this breakdown does not include.

## What this says about the layers

- The deficit has two parts of similar size. Fewer trips cost about 0.41 touchdowns per team-game, and a lower conversion rate inside
  the red zone costs about 0.45.
- Fewer trips follow from drives that stall before the 20. The replay has more punts (4.15 against 3.73) and more turnovers on downs
  (0.85 against 0.57). Both come from drive progression (the outcome draw) and from the fourth-down decision, which still uses the
  situation cell's historical share.
- Lower conversion inside the red zone shows up as more field-goal endings and fewer touchdowns. The fourth-down field-goal share
  matches the actual (26% against 25% of fourth-down tries), so the excess field goals are not from the fourth-down decision. The
  outcome draw inside the red zone is the more likely source. This is not isolated, because the run did not store per-play red-zone
  decisions and outcomes.

## Not established

- Which layer carries how much of the deficit. The breakdown names the mechanisms, not their weights.
- Whether the 2022 and 2023 pool explains part of it. Era differences are not controlled.
- Any predictive claim. This is a calibration diagnostic.

## Next step

Store each red-zone play's decision and outcome, then split the trip-conversion gap between the decision (go or kick at fourth down
inside the 20) and the outcome draw (touchdown, field goal or turnover given the play). That is the input to the formation-conditioned
outcome layer, which must be tested against these same actuals before any calibration of final scores.
