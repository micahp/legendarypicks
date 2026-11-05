# Blocked seeds: 2026_09_JAX_BAL, V1, V1.5 and V2

Status: exploratory. The snapshot is the 21:00 UTC preview, which is unverified, so no arm has a valid game. No final score
exists yet, so nothing is scored. Nothing here is a forecast, and no run output or model was changed.

Inputs: `out/<arm>/game.json`, `game.seeds.jsonl` and `game.boxscores.jsonl` on the fast host. Analysis:
`scripts/nfl_sequence/blocked_seed_analysis.py`. Output: `2026_09_JAX_BAL/blocked_seed_analysis.json`.

## Counts

| Arm | Complete | Blocked | rng scheme |
|---|---:|---:|---|
| V1 | 933 | 67 | v1 |
| V1.5 | 934 | 66 | v1 |
| V2 | 924 | 76 | v2 |

The blocker counts from the seed rows match `game.json` in all three arms.

## Is V2's excess real?

V2 has 10 more blocked seeds than V1.5: 76 against 66, z = 0.87. That is not distinguishable from zero. V1 is 67, one more
than V1.5.

The arms are not seed-paired. V1 and V1.5 share an rng scheme and stream key, but their status agrees on 782 of 1,000
seeds, and only one seed is blocked in both (with a different reason). V2 uses rng scheme v2 with its own stream root, so
seed N in V2 is not the same draw as seed N in V1.5. V2 can only be compared with V1.5 in aggregate.

| Blocker family | V1 | V1.5 | V2 | V2 minus V1.5 | z |
|---|---:|---:|---:|---:|---:|
| `qb_scramble_source_rows_missing` | 30 | 51 | 50 | -1 | -0.10 |
| `non_scramble_run_source_rows_missing` | 13 | 5 | 12 | +7 | 1.71 |
| `playcall_no_run_outcomes_in_cell` | 10 | 4 | 5 | +1 | 0.33 |
| `blocked_kick_outcome_unresolved` (field goal, guarded) | 4 | 1 | 4 | +3 | 1.34 |
| `blocked_kick_outcome_unresolved` (punt, guarded) | 1 | 2 | 0 | -2 | -1.41 |
| `safety_free_kick_not_modelled` | 3 | 1 | 4 | +3 | 1.34 |
| `blocked_kick_receiving_return_outside_field` | 2 | 2 | 1 | -1 | -0.58 |
| `blocked_kick_kicking_recovery_outside_field` | 2 | 0 | 0 | 0 | |
| `thin_kick_cell:field_goal:50+` | 2 | 0 | 0 | 0 | |

No family differs at 95% (nine unadjusted tests). The largest V2 increases are non-scramble runs (+7), guarded field goals
(+3) and free kicks after a safety (+3, a modelled gap that the engine refuses). Punts (-2) and receiving returns (-1) go
the other way.

## Where the blocks happen

The recorded plays stop at the last completed drive. The blocked drive's own plays are not exported, so the exact blocking
play is not in the data. The blocker string gives its cell (down, distance, yardline). `yardline_100` counts yards to the
opponent's end zone, so `80-99` is the offense's own 1 to 20, and `10-19` is the opponent's 10 to 19 (red zone).

Non-scramble run blocks per 1,000 recorded run exposures:

| Yardline bucket | V1 | V1.5 | V2 |
|---|---:|---:|---:|
| 10-19 (red zone) | 1.13 | 0.98 | 1.20 |
| 80-99 (own 1 to 20) | 0.38 | 0.00 | 0.71 |
| all other buckets | 0.00 to 0.16 | 0.00 | 0.00 to 0.05 |

The V2 excess in own territory is 4 blocks against 0 in V1.5, which is too few to call.

## Selection

**Drive before the block.** Pooled across the three arms: 194 blocked seeds with a drive index, and the drive before each
block ended as below. The complete-seed column is every drive ending in the 2,791 complete seeds (55,625 endings).

| Drive ending | Before a block | Complete seeds | z |
|---|---:|---:|---:|
| punt | 49.0% (95) | 32.0% | 5.07 |
| field goal attempt | 11.3% (22) | 20.9% | -3.27 |
| run | 9.3% (18) | 16.6% | -2.74 |
| pass incomplete | 9.8% (19) | 5.5% | 2.58 |
| interception | 8.8% (17) | 5.9% | 1.67 |

The blocked drives follow punts more often than other drive endings. Why is not measured: the blocked drive's own plays
are not exported, so I cannot say whether those drives start in the offense's own territory. The kick-family blocks (8
seeds) have no drive index and are not in this table.

**Score before the block.** Pooled across arms: blocked seeds' points at the start of the drive before the block, against
complete seeds at that same drive index, give -0.91 points (95% interval -2.04 to +0.23), and margin -0.28 (interval
-1.00 to +0.45). By arm, V1.5 is the only one whose interval excludes zero (-1.97, interval -3.85 to -0.09). Across three
arms that is not a finding on its own.

**Quarter.** Pooled: the quarter of the drive ending before the block is Q1 28.9% (56) against 22.2% for complete seeds (z
about 2.2, not corrected), Q2 24.7% against 29.9%, Q3 22.7% against 22.9%, Q4 23.7% against 24.9%. There is no late-game
concentration.

## What this means for the comparison

About 7% of seeds per arm are blocked, and they are not a random sample. They are concentrated in drives that start after
a punt, and in run exposures in the red zone and in own territory. A seed that reaches one of those cells has no recorded
continuation, so the complete-game means exclude it. The score before the block does not look different, but the points
the blocked seeds would have scored afterwards are unknown. That selection has to be carried into the full comparison,
not treated as noise.

## Caveats

- The recorded plays stop at the last completed drive, so the blocked play is located by its cell, not by a play index.
- Eight kick-family blocks have no drive index. Three V1 seeds, one V1.5 seed and three V2 seeds have no recorded plays.
- The preview snapshot is unverified. The whole set is exploratory, and no arm has a valid game.
- Counts per family are small (0 to 51). The z values are unadjusted.

## Not done

- The full comparison (winners, points, drives, halves, run and pass shares, workload) waits for a final score.
- V2's play-calling and workload model are unchanged.
