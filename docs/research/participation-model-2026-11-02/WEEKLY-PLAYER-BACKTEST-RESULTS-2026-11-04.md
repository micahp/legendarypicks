# Week-over-week backtest of player snap shares from the lineup layer: results, 2026-11-04

Script: `weekly_player_backtest.py` (committed before the run, `dcaec3de`). Output: `outputs/weekly_player_backtest_2022_2025.json`.
Inputs: the 2016 to 2025 scrimmage participation table (`324c4e1a...`, `build_tables.py --backfill-dir`), the nflverse
snap counts and weekly rosters (written once to JSON by `--prepare`, `b546bad4...`), `players.csv` (`c5239e14...`). Run on
the fast host, 16 lineup runs per team-game, 4 workers. Exploratory research evidence: 2022 to 2025 have been used in
earlier fits, so nothing here is an untouched holdout. 2026 was not read.

## What was forecast

For every RB, FB, TE and WR on a team's active roster (published weekly roster, status ACT) in every game of 2022 to 2025
(26,872 player-games): his share of the team's offensive snaps, against the published nflverse share (0 for an active
player with no offensive snap). The forecast runs the engine's own lineup code (`participation_field.Field.advance`) along
the game's observed groupings, so this scores who is on the field given the grouping, not the grouping. Score: mean
absolute error of the share per player-game. Lower is better.

Coverage: published skill snaps by players not on the active roster (they cannot be drawn): 93 of 185,802 in 2022, 0 in
2023 to 2025. Snap rows whose pfr id has no gsis id: at most 177 skill snaps a season.

## Arms and selected parameters (chosen on 2019 to 2021)

- P0: the table as fitted now (four prior seasons at 1, 0.5, 0.25, 0.125) and a leave hazard by class and stint only.
- P1: the grouping backtest's season weights (0.75 ** age over six seasons).
- P1h: P1 with a player-dependent leave hazard, the class hazard times ((1 - r) / (1 - c)) ** alpha, r the player's
  on-field rate and c his class's on-field mean. alpha = 1.5 (grid 0.5, 1, 1.5, 2; tuning error 0.2156 at alpha 0, 0.2039
  at 1.5).
- P2: P1h plus each player's published share of his team's snaps in its earlier games this season that he was active
  for, blended as (N0 * table rate + G * share) / (N0 + G). N0 = 1, the smallest value in the grid (1, 2, 4, 8, 16, 32;
  tuning error rises steadily with N0, 0.1495 to 0.1742).
- N: not the lineup layer, a reference: the published share to date where the player has an earlier active game this
  season, else P1h.

## Results, 2022 to 2025

| Arm | All | Observed share > 0 | RB | TE | WR | Weeks 1-4 | Weeks 5-9 | Weeks 10-18 | Postseason |
|---|---|---|---|---|---|---|---|---|---|
| P0 | 0.2163 | 0.2131 | 0.1838 | 0.1984 | 0.2489 | 0.2126 | 0.2150 | 0.2185 | 0.2187 |
| P1 | 0.2175 | 0.2145 | 0.1853 | 0.1998 | 0.2496 | 0.2130 | 0.2158 | 0.2202 | 0.2214 |
| P1h | 0.2034 | 0.2023 | 0.1785 | 0.1815 | 0.2333 | 0.1950 | 0.2009 | 0.2083 | 0.2085 |
| P2 | 0.1553 | 0.1597 | 0.1343 | 0.1393 | 0.1789 | 0.1532 | 0.1486 | 0.1598 | 0.1559 |
| N | 0.1268 | 0.1297 | 0.1104 | 0.1213 | 0.1411 | 0.1342 | 0.1218 | 0.1271 | 0.1163 |

Differences, with game-clustered 95% intervals (negative: the second arm is better):

| Comparison | All | Observed share > 0 | Weeks 1-4 | Weeks 10-18 |
|---|---|---|---|---|
| P1 - P0 | +0.0012 [+0.0007, +0.0017] | +0.0014 | +0.0003 (n.s.) | +0.0017 |
| P1h - P1 | -0.0141 [-0.0154, -0.0128] | -0.0122 | -0.0179 | -0.0119 |
| P2 - P1h | -0.0482 [-0.0498, -0.0465] | -0.0426 | -0.0419 | -0.0485 |
| N - P2 | -0.0284 [-0.0304, -0.0263] | -0.0300 | -0.0190 | -0.0327 |

By season (all player-games), P2: 0.157, 0.162, 0.155, 0.147; N: 0.128, 0.126, 0.126, 0.128 (2022 to 2025).

Simulation noise does not explain the gap to N (which has none): on a 2025 sample of 1,126 player-games, P2's error is
0.1443 with 16 runs and 0.1431 with 64.

## Findings

- The lineup layer as it stood (P0) spreads snaps too evenly within a position class. Every class's total is right (on
  a 2025 sample, RB 1.10, TE 1.30, WR 2.52 per snap against 1.10, 1.32, 2.51 observed), but starters get too few snaps and
  backups too many. The cause is the leave hazard: it depended only on class and stint, so a regular left as often as a
  backup. Given each player's actual share in the same game, it still erred by 0.146 on a 2021 sample (0.089 with the
  player hazard at alpha 1).
- The player-dependent hazard helps in every part of the season (-0.014).
- The current-season snap-count weights are the largest gain (-0.048), in every part of the season, with the smallest
  N0 in the grid: the current season's share should dominate the prior seasons' rate.
- The six-season weights that improved the grouping forecast make player rates slightly worse (+0.0012). The refit keeps
  one set of weights for the whole table; the grouping gain is the larger one.
- The plain share to date (N) still beats the layer with all updates, by 0.028. The lineup process does not yet carry the
  published share through to the simulated share. Possible causes, untested: the player weight multiplies a rate that is
  then subject to stint and count constraints; 634 to 769 player weights a season hit the 50x upper clip (a blended share
  more than 50 times the table rate; the lower clip cannot bind, since the smallest weight is N0 / (N0 + G)).

## Limits

- The groupings are given (the observed ones). Errors in the grouping draw add to these in a full game.
- The passer is chosen as the active QB with the most earlier snaps; he matters only for second-QB groupings.
- N0 and the clip were not explored beyond the pre-declared grid and value.
- The roster is the published weekly active list, which is retrospective (it includes late scratches as inactive).
