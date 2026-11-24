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
  postflight. Done 15:12 UTC. The log has no errors.
- Valid games: the table counts every complete game, overtime included. The runner log and the engine's
  `simulation.valid_full_games` count regulation games only (v1 91, v1.5 97, v2 94, the rest 98), so they read lower.
  The same split shows in 75 of the 78 earlier week 11 files. Only v1 and v1.5 lost seeds, 3 each, to engine blocks:
  missing run or scramble source rows, an unresolved punt outcome, and a kick return outside the field.

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

## Seed completion and failures (13 games)

A seed is completed when the game reaches a legal end (regulation or overtime). Every seed below was attempted. Source:
`seed_completion.json` (`matched_seeds.py`).

| model | attempted | completed | completion | failures | unsupported cell | engine error | games with a failure |
|---|---|---|---|---|---|---|---|
| v1 | 1,300 | 1,244 | 95.69% | 56 | 56 | 0 | 13 |
| v1.5 | 1,300 | 1,259 | 96.85% | 41 | 41 | 0 | 13 |
| v1.6 | 1,300 | 1,298 | 99.85% | 2 | 0 | 2 | 2 |
| v2 | 1,300 | 1,300 | 100% | 0 | 0 | 0 | 0 |
| pbv1 | 1,300 | 1,300 | 100% | 0 | 0 | 0 | 0 |
| pbv1-off | 1,300 | 1,300 | 100% | 0 | 0 | 0 | 0 |

Two failure classes, logged separately:

- **Unsupported cell** (v1, v1.5): the engine has no historical rows for the play it must draw, so it stops the seed
  on purpose. Issue: `docs/issues/slc-v1-v15-unsupported-cells.md`.
- **Engine error** (v1.6): a sack fumble row moves the ball behind the offense's own goal line, and the reducer raises.
  Issue: `docs/issues/slc-v16-sack-fumble-own-end-zone-error.md`.

### v1 and v1.5 failures by transition type

Field is yards to the opponent goal (`1-9` is the red zone, `80-99` is deep in its own end). Kick blocks do not record
the field state.

| transition | down | distance | field | v1 | v1.5 |
|---|---|---|---|---|---|
| QB scramble, no scramble rows | 1 | 1-3 | 1-9 | 1 | 0 |
| | 2 | 1-3 | 1-9 | 0 | 1 |
| | 2 | 1-3 | 20-49 | 1 | 1 |
| | 2 | 1-3 | 50-79 | 0 | 2 |
| | 2 | 4-6 | 10-19 | 2 | 1 |
| | 2 | 4-6 | 50-79 | 0 | 1 |
| | 2 | 7-10 | 1-9 | 1 | 0 |
| | 2 | 7-10 | 10-19 | 2 | 0 |
| | 2 | 7-10 | 20-49 | 2 | 1 |
| | 2 | 7-10 | 50-79 | 6 | 4 |
| | 2 | 11+ | 10-19 | 1 | 0 |
| | 3 | 1-3 | 10-19 | 1 | 0 |
| | 3 | 1-3 | 20-49 | 2 | 0 |
| | 3 | 7-10 | 80-99 | 3 | 0 |
| | 3 | 11+ | 80-99 | 1 | 0 |
| | 4 | 1-3 | 1-9 | 0 | 1 |
| | 4 | 1-3 | 50-79 | 0 | 2 |
| Designed run, no non-scramble run rows | 3 | 4-6 | 50-79 | 1 | 2 |
| | 3 | 4-6 | 80-99 | 1 | 1 |
| | 4 | 4-6 | 10-19 | 6 | 9 |
| | 4 | 4-6 | 20-49 | 2 | 0 |
| | 4 | 11+ | 10-19 | 0 | 2 |
| Run called, no run outcomes in the cell | 4 | 4-6 | 80-99 | 2 | 0 |
| | 4 | 7-10 | 1-9 | 5 | 3 |
| | 4 | 7-10 | 80-99 | 1 | 0 |
| Blocked kick return lands outside the field | | | | 5 | 5 |
| Blocked kick recovery by the kicking team outside the field | | | | 3 | 1 |
| Kick row with a penalty, fumble or review, unresolved (punt) | | | | 2 | 2 |
| Kick row with a penalty, fumble or review, unresolved (field goal) | | | | 2 | 1 |
| Field goal 50+ cell too thin | | | | 2 | 0 |
| Safety free kick at a quarter end | | | | 1 | 1 |
| **Total** | | | | **56** | **41** |

Scrimmage cells: 41 of 56 for v1 and 31 of 41 for v1.5; the other 15 and 10 are kicks. 4th down is 16 of v1's and 17
of v1.5's. Scrambles are the largest single type (23 and 14).

### How the newer models handle the same cells

The engine code is the same in all models (`slc_playcall.py`, `game_state.py`, `reducer.py`). The difference is five
opt-in fixes, `e2_reference.BLOCKER_FIXES`, chosen when the pack is built. Each week 11 pack was loaded on the fast host
on 2026-11-23 and its `reference.blocker_fixes` read: v1 and v1.5 have none; v1.6 and v2 have all five. pbv1 shares
v2's code commit and its pack audit log lists all five.

- `run_scramble_backoff`: when the exact cell has no rows for the chosen play class (scramble, designed run), the engine
  keeps the play class and widens the cell in steps: exact cell (at least 10 rows), same down and field bucket (25),
  same down and distance (25), same field bucket (50), all league plays of that class (50). It also allows sparse cells.
  This covers all three scrimmage block types above.
- `long_field_goal_feasibility`: a long field goal uses a fitted distance model, not the thin 50+ cell.
- `blocked_kick_source_audit` and `blocked_kick_geometry`: blocked kicks draw from an audited outcome file, and only
  among outcomes that end legally at the live field position. This covers the outside-the-field blocks.
- `safety_free_kick_boundaries`: a safety at a quarter end gets its free kick.

In week 11, v1.6, v2 and both pbv1 models had 0 unsupported-cell failures in 1,300 seeds each, while v1 and v1.5 had 56
and 41. A backoff draw is a wider-cell guess, not the exact
situation: the newer models finish these plays with less specific data, they do not have more data.

### v1.6 engine errors and PR #49

| game | seed | state | play | ends at |
|---|---|---|---|---|
| MIA at BUF | 300081 | Q3, 3rd and 8, 97 to go to the goal | sack fumble, -9 | 6 yards deep in its own end zone |
| MIN at SF | 300097 | Q3, 3rd and 7, 92 to go to the goal | sack fumble, -10 | 2 yards deep in its own end zone |

PR #49 (merge `a716c649`, 2026-11-17) is about this exact state. It is not in v1.6 (pack code `1bb3bd50`) or in dev.
It is in the v1.7 pack (`1ca59e0d`). With only `own_end_zone='resolve'`, these two seeds become a named block
(`own_end_zone_fumble_recovery_unresolved`) and still do not complete. With the geometry filter or the recovery model
from the same line, they continue. So the #49 line addresses both failures, but it must be ported as a new, separately
versioned v1.6 build. It was not rerun here. Details in the issue file.

The same guard is in every week 11 model. The reducer code for v1, v1.5, v1.6, v2 and pbv1 has no own-end-zone option,
so this state always stops the seed. Only v1.6 reached it in week 11 (2 of 1,300 seeds). The other models can reach it too.

## Matched-seed sensitivity

A sensitivity check, not a correction for selection bias. For each game, keep only the seeds that all six models
completed: 1,203 of 1,300 (88 to 96 per game). Then rerun the same report, props and grading scripts. The all-seed
numbers were rerun first, and they reproduce the published grading exactly. Source: `sensitivity.json`
(`sensitivity.py`).

A seed number is not the same game in two models, so this does not remove "the same" games. It also cannot show what a
failed seed would have produced. It shows how much each number moves when every model uses the same seed set.

Games (12 graded):

| model | win Brier all / matched | cover Brier change | over Brier change | margin error change | total error change |
|---|---|---|---|---|---|
| v1 | 0.233 / 0.229 | -0.001 | -0.001 | -0.10 | -0.06 |
| v1.5 | 0.210 / 0.212 | +0.005 | +0.000 | +0.08 | -0.04 |
| v1.6 | 0.198 / 0.193 | -0.008 | -0.006 | -0.08 | -0.09 |
| v2 | 0.181 / 0.179 | -0.005 | -0.007 | -0.03 | -0.21 |
| pbv1 | 0.234 / 0.242 | +0.006 | -0.001 | +0.13 | +0.05 |

Mean change per game (13 games, mean absolute / largest): home win 0.007 to 0.011 / up to 0.026; mean margin 0.16 to
0.26 points / up to 0.67; mean total 0.17 to 0.30 points / up to 0.85.

Props (942 graded per model) and player projections (1,280 props per model):

| model | prop Brier all / matched | side hit rate all / matched | P(over) change, mean / max | sim mean change, share of line | sides that flip |
|---|---|---|---|---|---|
| v1 | 0.321 / 0.322 | 0.500 / 0.502 | 0.005 / 0.039 | 1.6% | 6 |
| v1.5 | 0.316 / 0.317 | 0.511 / 0.506 | 0.007 / 0.034 | 1.9% | 18 |
| v1.6 | 0.284 / 0.282 | 0.515 / 0.522 | 0.009 / 0.047 | 2.2% | 20 |
| v2 | 0.307 / 0.307 | 0.524 / 0.522 | 0.009 / 0.046 | 2.4% | 20 |
| pbv1 | 0.322 / 0.322 | 0.499 / 0.504 | 0.008 / 0.046 | 2.3% | 20 |

Result:

- No ranking changes. Market still beats every model; v2 then v1.6 are still best on win Brier; v1.6 is still best on
  prop Brier.
- v1 and v1.5 do not move more than the models that lost no seeds. v2 and pbv1 completed every seed, so their shift is
  only from using fewer seeds, and it is the same size or larger. So the measured effect of the dropped seeds is within
  the noise of dropping about 8% of seeds at random.
- The size of that noise matters: up to 0.85 points on a game total and up to 0.047 on one prop P(over), from 7 or 8
  fewer seeds. Single props near the market line can change side (6 to 20 per model).
- What this cannot measure: the failed seeds stop in rare, high-leverage states (4th down, scrambles, blocked kicks,
  sack fumbles deep in its own end). Their outcomes are missing, not observed. If those games end differently from the
  rest, the bias is in v1 and v1.5's tails (late 4th-down drives, defensive scores), and matching does not show it. The
  only clean measure is a separately versioned build that completes them.

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
