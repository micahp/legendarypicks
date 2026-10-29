# SLC yards replay against 2024, matched plays (2026-10-29)

Research, exploratory. `scripts/nfl_sequence/scoring_yards_2024.py --seeds 2`, output `scratchpad/cutoff/scoring/yards-2024-v2.json`.
The replay is the default SLC path on the 2024 regular-season schedule (weeks 2 to 18), with the same snapshots and cutoff as the
calibration replay. 2026 is not read.

## Matching the two sides

The first run (`yards-2024.json`) was not comparable, and it is superseded. The actual side counted sacks, interceptions and
lost fumbles, and the replay dropped touchdowns (the state after a touchdown has no spot). Both sides now use the same plays:
sacks, interceptions and lost fumbles are excluded on both sides, and touchdowns are included on both sides, with the replay gain
set to the yard line before the play. Zones are the yard line before the play.

## Result

| zone and play | actual plays | replay plays per seed | actual mean yards | replay mean yards | actual first-down share | replay first-down share |
|---|---:|---:|---:|---:|---:|---:|
| pass_1-19 | 2179 | 2066 | 3.78 | 0.52 | 0.103 | 0.167 |
| pass_20-49 | 5104 | 4747 | 7.41 | 6.25 | 0.319 | 0.355 |
| pass_50-99 | 9153 | 9034 | 8.09 | 8.04 | 0.349 | 0.369 |
| run_1-19 | 2288 | 2136 | 2.80 | 0.69 | 0.141 | 0.144 |
| run_20-49 | 4278 | 3627 | 4.82 | 4.12 | 0.271 | 0.252 |
| run_50-99 | 6795 | 6542 | 5.07 | 4.88 | 0.237 | 0.236 |

Replay plays per seed are the replay total divided by the two seeds.

- Play counts now agree within about 1 to 15 percent in every cell, the largest gaps being run 20-49 (-15 percent) and run 1-19
  (-7 percent). The earlier mismatch is gone.
- Yardage is the open problem. Red-zone passes gain 0.52 yards against 3.78 actual, and red-zone runs 0.69 against 2.80. In the
  20 to 49 zone the gap is 6.25 against 7.41 for passes and 4.12 against 4.82 for runs. Past midfield the two sides are close
  (pass 8.04 against 8.09, run 4.88 against 5.07).
- The gap is largest where the distance to the goal limits the play, which is the red-zone mechanism already recorded in
  `SLC-SCORING-REDZONE-MECHANISM-2026-10-29.md`. The exact yard-line draw closed about 30 percent of the trip gap earlier.
  It has not closed the yardage gap in this table.

## Status

Measured and recorded. The red-zone gap is not fixed: the yardage inside the 20 is still about three yards short on passes and
about two on runs. A fix needs a change to the drive geometry or the red-zone outcome draw, followed by a rerun of this table.
