# Week 11 rerun with the roster preflight: 12 games, graded

Date: 2026-11-23. 100 seeds per game and model, six models (v1, v1.5, v1.6, v2, pbv1, pbv1-off). Every run used a
snapshot that passed the roster preflight, and every run in this report passed the postflight.

Graded: all 12 Sunday and Thursday games against the final scores and the published player stats. CIN at WAS
(Monday night) was rerun on a current snapshot after the first runs failed (see below). It is compared to the market
but not graded: it kicks off 2026-11-24 01:15 UTC.

## Result

- **No model beats the market on games.** Home-win Brier: market 0.155, best model v2 0.181, then v1.6 0.198. The
  market spread missed the final margin by 7.8 points on average; the best model mean (v1.6) missed by 10.0.
- **Every model is too cautious with big favorites.** The five favorites of 10 or more points (KC, HOU, DEN, BUF, CHI)
  all won. The market gave them 0.83 to 0.91; the models gave them 0.34 to 0.86. Over all 12 games the mean model
  margin is 2.7 to 3.4 points short of the spread, for every model.
- **No model beats the market on props.** Prop Brier: market 0.235, v1.6 0.284, v2 0.307, the rest 0.316 to 0.322.
- **Prop side hit rate** (bet the side where the sim differs from the market): v2 0.524, v1.6 0.515, v1.5 0.511,
  v1 0.500, pbv1 0.499. Break-even at -110 is 0.524. 942 graded props per model, one standard error about 0.016:
  no model is above break-even.
- **Best groups:** v2 rushing 0.586 (191 props) and v1.6 touchdowns 0.580 (200 props). Receiving is below 0.49 in both.
  One week of data, so these are leads to test, not signals.
- **v1.6 is still closest to the market on props** (mean absolute P(over) gap 0.173, others 0.226 to 0.241).
  v2 is closest on game lines (mean absolute home-win gap 0.110, v1.6 0.120).
- **pbv1-off equals pbv1** in every number, as in every earlier batch.

## CIN at WAS (Monday night): runs invalid

All six 100-seed runs failed the postflight. Reserve players got stats: Terry McLaurin in 98 of 100 seeds, Jeremy
McNichols in 100, Tanner Hudson in 71. The snapshot was built at 23:41 UTC on 11-22, before the fix that passes
exclusions to the engine (23:53 UTC). The resolution hash did not change, so the preflight passed.

Fixed in `8b92bf26` (on dev): the batch preflight now checks that every excluded depth-chart player is Out in the
injury report, and a one-seed smoke test for every game and model must pass the postflight before the full runs.
### CIN at WAS rerun (valid)

- Snapshot built 2026-11-23 14:18 UTC from current data (depth chart 07:01 UTC, weekly roster, injury news to that
  time): `/root/runs/week-11/snapshots/cinwas-current-2026-11-23T1418/` on the fast host. All preflight checks PASS,
  including the new exclusion check. QB1: Joe Burrow and Jayden Daniels.
- The first smoke test stopped the batch at 14:27 UTC: the postflight named Van Jefferson as the WSH passer in the
  v1.6 seed (one trick pass, Daniels had 36). That was a bug in the check, fixed in `14bacb1a` (on dev): a seed's
  passer is now the player with the most attempts.
- The second run (`cinwas-current-100b`): smoke test passed for all six models, then all six 100-seed runs passed the
  postflight. Done 15:12 UTC.

Market: CIN -6, total 54.5, WAS no-vig win 0.28. WAS is home.

| model | valid games | WAS win | WAS margin | WAS covers +6 | total | over 54.5 |
|---|---|---|---|---|---|---|
| v1 | 97 | 0.28 | -8.0 | 0.43 | 53.0 | 0.46 |
| v1.5 | 97 | 0.30 | -5.6 | 0.47 | 50.9 | 0.37 |
| v1.6 | 100 | 0.21 | -8.1 | 0.38 | 49.3 | 0.31 |
| v2 | 100 | 0.30 | -5.0 | 0.51 | 45.8 | 0.18 |
| pbv1 | 100 | 0.35 | -4.9 | 0.55 | 51.6 | 0.42 |

Props, 91 per model with prices on both sides: mean P(over) gap -0.06 to -0.08; mean absolute gap v1.6 0.127, the
others 0.211 to 0.215. Jacory Croskey-Merritt (WSH RB) has lines but is RESERVE in the nflverse weekly roster, so the
sims give him nothing. Lines come from rows captured before 15:12 UTC; they can still move before kickoff.

## Inputs

- Snapshots: `/root/runs/week-11/snapshots/rerun-preflight-2026-11-23/` on the fast host, from the 90-minute cutoff
  captures (`docs/research/cutoff-snapshots-2026/week-11/`): depth chart, weekly roster and injury news at or before
  each cutoff. The new exclusion check passes for all 12 snapshots in this report.
- Packs: `/root/runs/week-11/inputs/models/portable-models-2026-11-19/`. Seeds 300001 to 300100.
- Runner: `run_portable_batch.py`, manifest `manifest.week11-preflight-100-ordered.json` (every preflight and
  postflight table). Batch done 2026-11-23 04:53 UTC.
- Game lines and final scores: nflverse `games.csv` fetched 2026-11-23 13:34 UTC (sha256 in `grading.json`). These
  are closing lines, so MIN at SF shows SF -4.5, total 44.5 (the first MIN at SF report used SF -3.5, 46.5).
- Player props: `props` in `picks.dev.db`, rows captured before kickoff. Line = median over-line across books. Market
  P(over) = mean no-vig over probability across books quoting both sides at that line.
- Actual player stats: nflverse `stats_player_week_2026.parquet` fetched 2026-11-23 13:34 UTC (all 24 teams of these
  games present), joined on gsis id.
- Files: `game_market_comparison.json` (`build_report.py`), `props_comparison.json` (`props_compare.py`),
  `grading.json` (`grade.py`).

## Games: market and models

Home win probability. Spread is the home margin (positive = home favored).

| game | final | spread / total | market | v1 | v1.5 | v1.6 | v2 | pbv1 |
|---|---|---|---|---|---|---|---|---|
| ARI at KC | 7-34 | +15.5 / 40.5 | 0.90 | 0.68 | 0.75 | 0.71 | 0.68 | 0.66 |
| BAL at CAR | 33-35 | +2.5 / 44.5 | 0.56 | 0.37 | 0.43 | 0.41 | 0.56 | 0.45 |
| IND at HOU | 3-26 | +12.5 / 44.5 | 0.85 | 0.54 | 0.63 | 0.52 | 0.65 | 0.55 |
| JAX at NYG | 18-23 | -6 / 45.5 | 0.31 | 0.48 | 0.39 | 0.22 | 0.33 | 0.39 |
| LV at DEN | 24-38 | +11.5 / 41.5 | 0.83 | 0.80 | 0.81 | 0.78 | 0.68 | 0.71 |
| MIA at BUF | 9-26 | +16.5 / 45.5 | 0.91 | 0.69 | 0.68 | 0.86 | 0.85 | 0.74 |
| MIN at SF | 10-35 | +4.5 / 44.5 | 0.64 | 0.46 | 0.54 | 0.68 | 0.60 | 0.50 |
| NO at CHI | 13-21 | +11.5 / 47.5 | 0.84 | 0.37 | 0.36 | 0.54 | 0.49 | 0.34 |
| NYJ at LAC | 27-24 | +3 / 43.5 | 0.62 | 0.84 | 0.79 | 0.59 | 0.56 | 0.76 |
| PIT at PHI | 16-19 | -3.5 / 37.5 | 0.36 | 0.64 | 0.67 | 0.53 | 0.47 | 0.52 |
| TB at DET | 21-31 | +3.5 / 48.5 | 0.66 | 0.66 | 0.74 | 0.71 | 0.72 | 0.68 |
| TEN at DAL | 30-51 | +7.5 / 55.5 | 0.75 | 0.77 | 0.79 | 0.75 | 0.70 | 0.74 |

## Games: grading (12 games)

Brier: lower is better; a coin is 0.25. The market cover and over Brier is 0.25 by construction.

| model | win Brier | cover Brier | over Brier | winners right | cover side right | total side right | margin error | total error |
|---|---|---|---|---|---|---|---|---|
| market | 0.155 | 0.25 | 0.25 | 9 | | | 7.8 | 10.7 |
| v1 | 0.233 | 0.333 | 0.289 | 7 | 6 | 7 | 11.3 | 13.4 |
| v1.5 | 0.210 | 0.326 | 0.287 | 8 | 5 | 7 | 11.1 | 13.2 |
| v1.6 | 0.198 | 0.295 | 0.350 | 9 | 6 | 6 | 10.0 | 13.6 |
| v2 | 0.181 | 0.307 | 0.345 | 8 | 6 | 6 | 10.1 | 13.0 |
| pbv1 | 0.234 | 0.324 | 0.292 | 7 | 5 | 5 | 11.5 | 13.6 |

Margin and total error: mean absolute difference between the model's mean (or the market line) and the final.

## Props: market comparison (12 games)

Gap = sim P(over) minus market P(over), 1,022 props per model.

| model | mean gap | mean abs gap |
|---|---|---|
| v1 | -0.063 | 0.241 |
| v1.5 | -0.058 | 0.240 |
| v1.6 | -0.065 | 0.173 |
| v2 | -0.074 | 0.226 |
| pbv1 | -0.065 | 0.240 |

## Props: grading (12 games)

942 graded props per model. 77 props are ungraded because the player has no published stat row (he did not play:
for example Carson Beck, Kenneth Walker III, Jalon Daniels, Dalton Kincaid). 3 props are pushes. 432 of 942 went over.

| model | Brier | market Brier | side hits | side hit rate |
|---|---|---|---|---|
| v1 | 0.321 | 0.235 | 471 | 0.500 |
| v1.5 | 0.316 | 0.235 | 481 | 0.511 |
| v1.6 | 0.284 | 0.235 | 485 | 0.515 |
| v2 | 0.307 | 0.235 | 494 | 0.524 |
| pbv1 | 0.322 | 0.235 | 470 | 0.499 |

By market group, v1.6 and v2:

| model | group | props | Brier | market Brier | side hit rate |
|---|---|---|---|---|---|
| v1.6 | receiving | 409 | 0.309 | 0.247 | 0.467 |
| v1.6 | rushing | 191 | 0.320 | 0.249 | 0.539 |
| v1.6 | passing | 108 | 0.263 | 0.248 | 0.528 |
| v1.6 | touchdowns | 200 | 0.211 | 0.189 | 0.580 |
| v1.6 | interceptions | 34 | 0.270 | 0.247 | 0.529 |
| v2 | receiving | 409 | 0.350 | 0.247 | 0.487 |
| v2 | rushing | 191 | 0.324 | 0.249 | 0.586 |
| v2 | passing | 108 | 0.251 | 0.248 | 0.546 |
| v2 | touchdowns | 200 | 0.233 | 0.189 | 0.550 |
| v2 | interceptions | 34 | 0.292 | 0.247 | 0.412 |

All groups for all models are in `grading.json` (`prop_summary_by_group`). Markets the box scores do not hold were
skipped: kicking, field goals, extra points, sacks and longest plays.

## What this does not show

- One week, 12 games. Each share from 100 seeds can be off by about 5 points either way.
- The sim P(over) is far from the market (mean absolute gap 0.17 to 0.24), and its Brier is worse than the market's
  in every group. A side hit rate near 0.52 with that calibration is not an edge.
- Side hit rate assumes -110. It ignores the actual price.

## Next

1. Grade CIN at WAS after the game.
2. Find why every model shrinks big favorites (mean margin about 3 points short of the spread).
3. Give the fullback a usage role in the engine (Kyle Juszczyk gets no touches).
4. Drop pbv1-off or rebuild it so the switch changes the reference data.
