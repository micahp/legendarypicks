# Red-zone touchdown deficit: the mechanism, 2026-10-29

Replay: `scoring_redzone_2024.py` (2 seeds per game, weeks 2 to 18, exploratory). Output: `SLC-SCORING-REDZONE-PLAYS-V3-2024-2026-10-29.json`.

## What matches

Inside the 20, the replay and the 2024 actuals agree on the decisions and on the per-play rate:

| Measure | Replay | Actual 2024 |
|---|---|---|
| Red-zone run and pass plays per team-game | 10.19 | 9.72 |
| Touchdown per red-zone run or pass play (sampled outcome flag) | 0.201 | 0.196 |
| Field-goal share of fourth downs inside the 20 | 0.679 | 0.684 |

## What does not match

Touchdown per red-zone trip (a drive that reaches the 20 at any scrimmage play): replay 0.485, actual 0.623. The gap is -0.14 per
trip, about -0.45 touchdowns per team-game.

## Mechanism (verified in code and in a trace; not yet quantified)

- The touchdown that ends a drive is decided by geometry: the yards the sampled row gained, applied to the state's own yard line
  (`e1_drive.py`, the reducer's position arithmetic). The row's `touchdown` flag is logged as `sampled_touchdown_flag`, and it does not
  itself end the drive.
- Cells bucket the yard line as 1 to 9 yards, 10 to 19, and so on (`e0_single_play.yardline_bucket`). A state at the 5 can draw a row
  sampled from the 9, and that row's flag can say touchdown while the gain from the 5 falls short.
- Trace evidence (Week 8 CAR-GB, seed 1, formation off): drive 14 has a completion from the 5 with a sampled touchdown flag, and the drive
  then ends in a field-goal attempt. Drive 15 has a similar pattern. The engine's touchdown terminal is correct for its geometry; the
  sampled flag is what does not match the state.
- That explains why the per-play flag rate matches actual while touchdowns per trip do not: the flags are drawn from the historical
  distribution, and the geometry then realises fewer of them.

## Not established

- How much of the -0.45 touchdowns per team-game comes from this mechanism. The replay logs about 420 more touchdown-flagged red-zone
  plays than touchdown drives in the two-seed run, which is a rough upper bound on the mismatch, not a measured share.
- Whether a finer red-zone bucket, or conditioning the gain on the exact distance, fixes it without breaking the cell counts the
  play-call layer depends on.

## Next test

A new model version: red-zone outcome draws conditioned on the exact distance to the goal (or a finer red-zone bucket), tested with the
same replay and seeds against these actuals. It is a new version and needs its own lock. The current locked model is not changed.

# Matched-seed ablation (CAR-GB, 100 seeds, paired against score-clock SLC)

Summary: `SLC-MATCHED-SEED-BASELINES-CAR-GB-2026-10-29.json`. Paired differences, home minus away margin and total points, with
standard errors (one seed is one game).

| Arm | Margin difference | Total difference | Home win share |
|---|---|---|---|
| Score-clock SLC (reference) | 0 | 0 | 0.50 |
| Team splits only | +1.97 ± 1.47 | +1.51 ± 1.46 | 0.55 |
| Formation only | +1.38 ± 1.66 | +0.96 ± 1.65 | 0.58 |
| Layered (both) | +5.27 ± 1.66 | -0.89 ± 1.66 | 0.67 |

Neither split alone is clearly different from score-clock. Together they shift the margin by 5.3 points, more than the sum of the two.
This is one snapshot, 100 seeds, and a wiring comparison. It does not establish that the layered margin is right, and no forecast claim
rests on it.
