# Week 11 rerun with the roster preflight: MIN at SF

Date: 2026-11-23. Game: 2026_11_MIN_SF, Sunday night, kickoff 01:20 UTC. 100 seeds per model, all six models. No grading against the final score in this report.

## Result

- **All six runs finished before kickoff** (last one at 01:12 UTC) and **all passed the postflight**: no excluded player got stats in any model, and each team's passer was its resolved QB1 (Kirk Cousins, Brock Purdy).
- **Player props are much closer to the market than in the first week 11 batch.** The mean gap in P(over) is about -0.03 in every model, against -0.13 to -0.18 for MIN_SF in the batch that used month-old rosters. v1.6 has the smallest mean absolute gap (0.156).
- **Game lines:** v1.6 and v2 are closest to the market (SF -3.5, total 46.5). v1, v1.5 and pbv1 have the game near even with high totals.
- **Engine gap: fullbacks never get the ball.** Kyle Juszczyk is SF's eligible FB1 and has receptions, receiving-yards and rushing-plus-receiving-yards lines, but no model gives him a touch. The engine's usage shares have no fullback role.
- **pbv1-off equals pbv1** again (same outcomes and props), as in every earlier batch.
- 100 seeds per model: each share can be off by about 5 points either way. No model has a proven edge, so these are not betting signals.

## Inputs

- Snapshot: `docs/research/model-snapshots-2026/week-11/2026_11_MIN_SF.json`, built from the live 90-minute cutoff capture (`cutoff-snapshots-2026/week-11/2026_11_MIN_SF.json`, saved 23:50 UTC). Cutoff 2026-11-22T23:50:00Z. Roster resolution hash `ef041e89f1d3`, the same file for all six models.
- Preflight (all PASS): weekly-roster membership, depth chart 8.4 hours old at the cutoff, injury statuses with publish times for this game, resolved QB1 for both teams, no unresolved required role, no player on both teams.
- Packs: the six packs in `/root/runs/week-11/inputs/models/portable-models-2026-11-19/` on the fast host (v1.6 is the verified pack `6cf1e836`). Seeds 300001 to 300100.
- Runner: `scripts/nfl_sequence/run_portable_batch.py`, manifest `manifest.week11-preflight-100-ordered.json` (every preflight and postflight table).
- Game lines: nflverse `games.csv` fetched 2026-11-22 about 22:05 UTC, sha256 `deb5cae20e8c68d2...`: SF -3.5, total 46.5, SF -190, MIN +159, SF no-vig win 0.629.
- Player props: `props` in `picks.dev.db`, rows captured before kickoff. Line = median over-line across books. Market P(over) = mean no-vig over probability across books quoting both sides at that line.
- Files here: `game_market_comparison.json` (`build_report.py`), `props_comparison.json` (`props_compare.py`).

## Game lines

| model | valid games | SF win | SF margin | SF covers -3.5 | total | over 46.5 |
|---|---|---|---|---|---|---|
| v1 | 95 | 0.46 | +0.4 | 0.36 | 50.7 | 0.62 |
| v1.5 | 99 | 0.54 | +0.4 | 0.43 | 52.3 | 0.72 |
| v1.6 | 99 | 0.68 | +5.5 | 0.59 | 45.8 | 0.48 |
| v2 | 100 | 0.60 | +3.3 | 0.55 | 45.4 | 0.51 |
| pbv1 | 100 | 0.50 | +0.5 | 0.44 | 49.0 | 0.56 |

## Player props by model

The gap is sim P(over) minus market P(over).

| model | props | mean P(over) gap | mean abs gap |
|---|---|---|---|
| v1 | 83 | -0.032 | 0.220 |
| v1.5 | 83 | -0.029 | 0.218 |
| v1.6 | 83 | -0.029 | 0.156 |
| v2 | 83 | -0.029 | 0.212 |
| pbv1 | 83 | -0.034 | 0.218 |

## Player props by market group (players in the sim)

| model | market group | props | mean P(over) gap | mean abs gap |
|---|---|---|---|---|
| v1 | receiving | 31 | -0.105 | 0.262 |
| v1 | rushing | 12 | -0.079 | 0.173 |
| v1 | passing | 8 | +0.270 | 0.270 |
| v1 | touchdowns | 20 | -0.028 | 0.158 |
| v1 | interceptions | 4 | +0.066 | 0.071 |
| v1.5 | receiving | 31 | -0.100 | 0.260 |
| v1.5 | rushing | 12 | -0.077 | 0.171 |
| v1.5 | passing | 8 | +0.309 | 0.309 |
| v1.5 | touchdowns | 20 | -0.033 | 0.147 |
| v1.5 | interceptions | 4 | +0.041 | 0.041 |
| v1.6 | receiving | 31 | -0.075 | 0.183 |
| v1.6 | rushing | 12 | +0.059 | 0.224 |
| v1.6 | passing | 8 | +0.082 | 0.143 |
| v1.6 | touchdowns | 20 | -0.051 | 0.076 |
| v1.6 | interceptions | 4 | -0.014 | 0.044 |
| v2 | receiving | 31 | -0.067 | 0.256 |
| v2 | rushing | 12 | +0.031 | 0.283 |
| v2 | passing | 8 | +0.162 | 0.219 |
| v2 | touchdowns | 20 | -0.070 | 0.118 |
| v2 | interceptions | 4 | -0.065 | 0.065 |
| pbv1 | receiving | 31 | -0.110 | 0.259 |
| pbv1 | rushing | 12 | -0.022 | 0.240 |
| pbv1 | passing | 8 | +0.219 | 0.219 |
| pbv1 | touchdowns | 20 | -0.051 | 0.127 |
| pbv1 | interceptions | 4 | +0.150 | 0.150 |

## Largest gaps, v1.6

| player | team | market | line | market P(over) | sim mean | sim P(over) | gap |
|---|---|---|---|---|---|---|---|
| Kyle Juszczyk | SF | receptions | 0.5 | 0.56 | 0.0 | 0.00 | -0.56 |
| Deebo Samuel Sr. | SF | rushing_yards | 8.5 | 0.49 | 0.7 | 0.04 | -0.45 |
| Keenan Allen | SF | receptions | 2.5 | 0.51 | 0.5 | 0.06 | -0.45 |
| Keenan Allen | SF | receiving_yards | 26.5 | 0.50 | 6.0 | 0.07 | -0.43 |
| Jauan Jennings | MIN | receptions | 2.5 | 0.45 | 0.8 | 0.06 | -0.39 |
| Justin Jefferson | MIN | targets | 11.5 | 0.43 | 16.1 | 0.80 | +0.37 |
| Jauan Jennings | MIN | receiving_yards | 19.5 | 0.51 | 7.8 | 0.14 | -0.37 |
| Jordan Mason | MIN | rush_attempts | 12 | 0.50 | 7.6 | 0.15 | -0.35 |
| Aaron Jones | MIN | rushing_receiving_yards | 44.5 | 0.50 | 91.8 | 0.83 | +0.33 |
| Aaron Jones | MIN | total_rush_attempts | 8.5 | 0.47 | 16.0 | 0.79 | +0.32 |
| Kirk Cousins | MIN | rushing_yards | 2.5 | 0.49 | 14.8 | 0.81 | +0.32 |
| Jordan Mason | MIN | receptions | 0.5 | 0.64 | 0.5 | 0.33 | -0.30 |

Markets the box scores do not hold were skipped: kicking, field goals, extra points, sacks and longest plays.

## Postflight

- v1: excluded players receiving stats: 0
- v1.5: excluded players receiving stats: 0
- v2: excluded players receiving stats: 0
- v1.6: excluded players receiving stats: 0
- pbv1: excluded players receiving stats: 0
- pbv1-off: excluded players receiving stats: 0

## Next

1. Add CIN_WAS and the 11 played games to this report as they finish.
2. Give the fullback a usage role in the engine.
3. Drop pbv1-off or rebuild it so the switch changes the reference data.
4. Grade against final scores in a separate step.
