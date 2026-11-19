# Player props versus simulated stats: IND at HOU, 2026-11-19

**Question.** For tonight's game, how do the simulated player stats compare with the market player props?

**Game.** Prop game 30693, HOU vs IND, kickoff 2026-11-20 01:15 UTC (2026-11-19 20:15 ET).

**Simulations.** Four arms, all on the current IND at HOU snapshot (as of 2026-11-19 16:17 UTC; injuries from RotoWire statuses up to that time).

| Arm | Seeds used |
|---|---|
| pbv1-off | 1000 |
| pbv1-on | 869 (incomplete, see below) |
| v1-vfg | 1000 |
| v2-pbp-2026-11-17 | 1000 |

**Lines.** The `props` table, over side only. For each player and market, the line is the median over-line across the books that carry it. Lines were captured up to 2026-11-18 01:04 UTC, so they are about a day older than the snapshot.

**Method.** `scripts/props_sim_comparison.py` (in this folder). For each arm it reads the box-score files, takes each player's simulated value per seed for each market, and reports the mean, the share of seeds over the line (a push counts as not over), and the line. Markets the simulation does not produce are skipped: kicking points, field goals made, extra points made, sacks.

**Known gaps.**
- `pbv1-on` is short. Chunks 300201 to 300600 stopped partway: 91, 80, 54 and 44 of 100 seeds. The 131 missing seeds were not rerun.
- Passing markets cover only 2 players, so they are thin.
- Lines are about a day old.

## Results: mean of (sim mean minus line), and mean share of seeds over the line

| Market | Players | pbv1-off | pbv1-on | v1-vfg | v2-pbp |
|---|---|---|---|---|---|
| receiving_yards | 14 | -1.1 (0.34) | -1.1 (0.34) | -0.7 (0.34) | +2.2 (0.37) |
| receptions | 13 | -0.3 (0.34) | -0.3 (0.34) | -0.3 (0.34) | +0.1 (0.39) |
| targets | 11 | -0.2 (0.39) | -0.2 (0.39) | -0.2 (0.39) | +0.8 (0.46) |
| rushing_yards | 6 | -0.5 (0.43) | -0.4 (0.43) | -1.1 (0.42) | +3.8 (0.51) |
| rush_attempts | 5 | -1.7 (0.37) | -1.7 (0.37) | -1.8 (0.37) | -1.8 (0.37) |
| rushing_receiving_yards | 3 | -12.6 (0.29) | -12.5 (0.29) | -12.9 (0.28) | -11.6 (0.31) |
| total_touchdowns | 8 | -0.3 (0.19) | -0.3 (0.19) | -0.3 (0.19) | -0.2 (0.22) |
| passing_yards | 2 | +24.6 (0.63) | +25.0 (0.63) | +30.1 (0.65) | +14.5 (0.57) |
| passing_rushing_yards | 2 | +30.3 (0.66) | +30.7 (0.67) | +35.6 (0.69) | +18.6 (0.59) |
| pass_completions | 2 | +2.3 (0.67) | +2.3 (0.67) | +2.4 (0.68) | +2.2 (0.67) |
| pass_attempts | 2 | +4.3 (0.72) | +4.3 (0.72) | +4.6 (0.73) | +4.9 (0.75) |
| passing_touchdowns | 2 | +0.1 (0.57) | +0.1 (0.58) | +0.2 (0.60) | 0.0 (0.51) |
| interceptions_thrown | 2 | +0.1 (0.43) | +0.1 (0.43) | +0.2 (0.47) | +0.2 (0.44) |

Full player-level rows, with each player's sim mean and share over the line, are in `props_sim_comparison.md` and `props_sim_comparison.json`.

## Reading

- **Receiving, rushing, and targets.** The three pbv1 and v1 arms sit close to the lines. Receiving yards are about a yard under the line, and each arm puts about a third of seeds over. v2 runs about 2 to 4 yards higher on those markets.
- **Rush attempts.** Every arm is about 1.7 carries under the line. That is the same gap the lead-RB work found earlier, and the same pattern shows up here for the 5 players with a rush-attempts line.
- **Passing.** The arms put the two passers 14 to 36 yards over their passing-yard lines, depending on the arm. Two players is too few to conclude much.
- **Model differences.** pbv1-off and pbv1-on agree within a few tenths on every market. The arm-to-arm gaps are larger than the pbv1 switch.

## Next

- Rerun the missing `pbv1-on` seeds (300292 to 300600) if we want a complete pbv1-on row.
- Refresh the props from the sportsbooks before using these lines for a pick.
