# Week 11 rerun with the roster preflight: 9 games, graded

Date: 2026-11-23. 100 seeds per game and model, six models (v1, v1.5, v1.6, v2, pbv1, pbv1-off). Every run used a
snapshot that passed the roster preflight and every run in this report passed the postflight.

Graded: 8 played games against the final scores and the published player stats. MIN at SF is in the market
comparison but is not graded (no final score at the time of the report). CIN at WAS is not in this report (see below).
JAX at NYG, LV at DEN and NYJ at LAC were still running.

## Result

- **No model beats the market on games.** Home-win Brier: market 0.105, best model v2 0.144, then v1.6 0.158 and
  v1.5 0.159. The market spread missed the final margin by 6.6 points on average; the best model mean (v2) missed by 9.6.
- **Every model is too cautious with big favorites.** KC (-15.5), BUF (-16.5), HOU (-12.5) and CHI (-11.5) all won.
  The market gave them 0.84 to 0.91. The models gave them 0.34 to 0.86. Mean margin is 3.4 to 5.2 points short of the
  spread for every model.
- **No model beats the market on props.** Prop Brier: market 0.235, v1.6 0.281, v2 0.292, the rest 0.306 to 0.312.
- **Prop side hit rate** (bet the side where the sim differs from the market): v2 0.536, pbv1 0.525, v1.5 0.523,
  v1 and v1.6 0.508. Break-even at -110 is 0.524. 610 graded props per model, so one standard error is about 0.020:
  no model is clearly above break-even.
- **v1.6 is still closest to the market on props** (mean absolute P(over) gap 0.183, others 0.225 to 0.244).
  v2 is closest on game lines (mean absolute home-win gap 0.121).
- **v2 rushing props hit 0.631** (122 props) and v1.6 rushing 0.582. This is the one group above break-even in more
  than one model. It is one week, so it is a lead to test, not a signal.
- **pbv1-off equals pbv1** in every number, as in every earlier batch.

## CIN at WAS (Monday night): runs invalid

All six 100-seed runs failed the postflight. Reserve players got stats: Terry McLaurin in 98 of 100 seeds, Jeremy
McNichols in 100, Tanner Hudson in 71. The snapshot was built at 23:41 UTC, before the fix that passes exclusions to
the engine (23:53 UTC). The resolution hash did not change, so the preflight passed.

Fixed in `8b92bf26` (on dev): the batch preflight now checks that every excluded depth-chart player is Out in the
injury report, and a one-seed smoke test for every game and model must pass the postflight before the full runs.
A rebuilt snapshot that passes the new check is on the fast host at
`/root/runs/week-11/snapshots/cinwas-fixed-2026-11-23/`. It will run after the Sunday games.

## Inputs

- Snapshots: `/root/runs/week-11/snapshots/rerun-preflight-2026-11-23/` on the fast host. Played games use the
  90-minute cutoff captures (`docs/research/cutoff-snapshots-2026/week-11/`); depth chart, weekly roster and injury
  news at or before each cutoff. The new exclusion check passes for all 12 snapshots other than CIN at WAS.
- Packs: `/root/runs/week-11/inputs/models/portable-models-2026-11-19/`. Seeds 300001 to 300100.
- Runner: `run_portable_batch.py`, manifest `manifest.week11-preflight-100-ordered.json` (every preflight and
  postflight table).
- Game lines and final scores: nflverse `games.csv` fetched 2026-11-23 04:15 UTC (sha256 in `grading.json`). These
  are closing lines, so MIN at SF now shows SF -4.5, total 44.5 (the earlier MIN at SF report used SF -3.5, 46.5).
- Player props: `props` in `picks.dev.db`, rows captured before kickoff. Line = median over-line across books. Market
  P(over) = mean no-vig over probability across books quoting both sides at that line.
- Actual player stats: nflverse `stats_player_week_2026.parquet` (release modified 2026-11-23 02:33 UTC), joined on
  gsis id.
- Files: `game_market_comparison.json` (`build_report.py`), `props_comparison.json` (`props_compare.py`),
  `grading.json` (`grade.py`).

## Games: market and models

Home win probability. Spread is the home margin (positive = home favored).

| game | final | spread / total | market | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|---|---|
| ARI at KC | 7-34 | +15.5 / 40.5 | 0.90 | 0.68 | 0.75 | 0.71 | 0.68 | 0.66 |
| BAL at CAR | 33-35 | +2.5 / 44.5 | 0.56 | 0.37 | 0.43 | 0.41 | 0.56 | 0.45 |
| IND at HOU | 3-26 | +12.5 / 44.5 | 0.85 | 0.54 | 0.63 | 0.52 | 0.65 | 0.55 |
| MIA at BUF | 9-26 | +16.5 / 45.5 | 0.91 | 0.69 | 0.68 | 0.86 | 0.85 | 0.74 |
| MIN at SF | not final | +4.5 / 44.5 | 0.64 | 0.46 | 0.54 | 0.68 | 0.60 | 0.50 |
| NO at CHI | 13-21 | +11.5 / 47.5 | 0.84 | 0.37 | 0.36 | 0.54 | 0.49 | 0.34 |
| PIT at PHI | 16-19 | -3.5 / 37.5 | 0.36 | 0.64 | 0.67 | 0.53 | 0.47 | 0.52 |
| TB at DET | 21-31 | +3.5 / 48.5 | 0.66 | 0.66 | 0.74 | 0.71 | 0.72 | 0.68 |
| TEN at DAL | 30-51 | +7.5 / 55.5 | 0.75 | 0.77 | 0.79 | 0.75 | 0.70 | 0.74 |

## Games: grading (8 played games)

Brier: lower is better; a coin is 0.25. The market cover and over Brier is 0.25 by construction.

| model | win Brier | cover Brier | over Brier | winners right | cover side right | total side right | margin error | total error |
|---|---|---|---|---|---|---|---|---|
| market | 0.105 | 0.25 | 0.25 | 7 | | | 6.6 | 11.9 |
| v1 | 0.187 | 0.317 | 0.327 | 6 | 5 | 4 | 11.1 | 15.6 |
| v1.5 | 0.159 | 0.300 | 0.361 | 6 | 4 | 3 | 10.4 | 15.7 |
| v1.6 | 0.158 | 0.315 | 0.365 | 7 | 4 | 4 | 9.6 | 15.1 |
| v2 | 0.144 | 0.319 | 0.350 | 6 | 4 | 4 | 9.6 | 14.4 |
| pbv1 | 0.191 | 0.314 | 0.339 | 6 | 4 | 2 | 10.9 | 16.2 |

Margin and total error: mean absolute difference between the model's mean (or the market line) and the final.

## Props: market comparison (9 games)

Gap = sim P(over) minus market P(over), 757 props per model.

| model | mean gap | mean abs gap |
|---|---|---|
| v1 | -0.060 | 0.244 |
| v1.5 | -0.058 | 0.242 |
| v1.6 | -0.067 | 0.183 |
| v2 | -0.070 | 0.225 |
| pbv1 | -0.063 | 0.244 |

## Props: grading (8 played games)

610 graded props per model. 63 props are ungraded because the player has no published stat row (he did not play:
for example Carson Beck, Kenneth Walker III, Jalon Daniels, Dalton Kincaid). 1 prop is a push. 280 of 610 went over.

| model | Brier | market Brier | side hits | side hit rate |
|---|---|---|---|---|
| v1 | 0.312 | 0.235 | 310 | 0.508 |
| v1.5 | 0.306 | 0.235 | 319 | 0.523 |
| v1.6 | 0.281 | 0.235 | 310 | 0.508 |
| v2 | 0.292 | 0.235 | 327 | 0.536 |
| pbv1 | 0.310 | 0.235 | 320 | 0.525 |

By market group, v1.6 and v2:

| model | group | props | Brier | market Brier | side hit rate |
|---|---|---|---|---|---|
| v1.6 | receiving | 268 | 0.305 | 0.248 | 0.478 |
| v1.6 | rushing | 122 | 0.295 | 0.248 | 0.582 |
| v1.6 | passing | 71 | 0.303 | 0.248 | 0.437 |
| v1.6 | touchdowns | 131 | 0.210 | 0.186 | 0.534 |
| v1.6 | interceptions | 18 | 0.263 | 0.250 | 0.556 |
| v2 | receiving | 268 | 0.321 | 0.248 | 0.534 |
| v2 | rushing | 122 | 0.294 | 0.248 | 0.631 |
| v2 | passing | 71 | 0.275 | 0.248 | 0.479 |
| v2 | touchdowns | 131 | 0.240 | 0.186 | 0.496 |
| v2 | interceptions | 18 | 0.298 | 0.250 | 0.444 |

All groups for all models are in `grading.json` (`prop_summary_by_group`). Markets the box scores do not hold were
skipped: kicking, field goals, extra points, sacks and longest plays.

## What this does not show

- One week, 8 graded games. Each share from 100 seeds can be off by about 5 points either way.
- The sim P(over) is far from the market (mean absolute gap 0.18 to 0.24), and its Brier is worse than the market's
  in every group. A side hit rate near 0.52 with that calibration is not an edge.
- Side hit rate assumes -110. It ignores the actual price.

## Next

1. Run CIN at WAS on the fixed snapshot (smoke test first), then JAX at NYG, LV at DEN and NYJ at LAC finish.
2. Grade MIN at SF once the final score is in games.csv.
3. Find why every model shrinks big favorites (mean margin 3 to 5 points short of the spread).
4. Give the fullback a usage role in the engine (Kyle Juszczyk gets no touches).
5. Drop pbv1-off or rebuild it so the switch changes the reference data.
