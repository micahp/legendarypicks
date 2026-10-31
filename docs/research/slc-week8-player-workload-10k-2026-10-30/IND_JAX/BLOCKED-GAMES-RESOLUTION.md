# IND–JAX blocked-game resolution

**Updated:** 2026-10-31

**Scope:** the two blocked outcomes in the frozen IND–JAX Week 8 SLC 10K run.

## Result

The blocker came from projecting a classified blocked kick to a next snap at the goal line while retaining an impossible 10-yard distance. The reducer now sets the next-snap distance to the smaller of the source distance and the yards available to the goal line. The game-state and E2 legality validators check the projected possession, spot, down, and distance together.

The original 10K files remain unchanged: **9,998 valid games, 2 blocked games, 0 simulation errors**. The fix is in research code for future runs; it does not rewrite either frozen seed result.

| Original seed | Kick and source play | Before kick | Classified next snap | Corrected distance |
|---:|---|---|---|---:|
| 4382 | Punt, `2024_05_MIA_NE` play 1249 | 4th-and-11 at yardline 86 | Receiving team, 1st down at yardline 6 | 6 yards |
| 5650 | Field goal, `2025_10_NO_CAR` play 2504 | 4th-and-1 at yardline 1 | Kicking team retains possession, 1st down at yardline 1 | 1 yard |

Both are goal-to-go states. The old projected distance of 10 was longer than the remaining field distance. The corrected transition preserves the source classification and makes the next snap legal.

## Regression coverage

The deterministic regression uses the two audited source rows and passes each through blocked-kick sampling, the shared reducer, and the state transition checks. Positive cases cover receiving-team possession and kicking-team retention. Negative cases reject a mismatched next-snap distance. The full-game rules matrix and E2 legality checker now accept a correctly projected `classified_next_snap` and verify its team, spot, down, and distance.

Verification on the research branch:

```text
Ran 22 tests in 0.032s
OK
git diff --check: passed
```

The code and tests were pushed in commit [`9bdded91`](https://github.com/micahp/legendarypicks/commit/9bdded913af2b4c3c39299c19db2e2fe4e09bc4d).

## Full-stack seed probe

Seed 4382 was also run once with the patched source and the archived full-stack playcall layers enabled. It completed as a valid game, JAX 26–IND 22, with box-score reconciliation passed. The game did **not** sample a blocked kick: its blocked-kick geometry categories and source-audit transitions were both zero. It is therefore a general runtime and box-score check, not a replay of the original blocker.

The regenerated profile reference hash (`f4bfbc0c…`) and profile snapshot hash (`662e9ee4…`) differ from the frozen run (`c7925753…` and `daf6bb0c…`). The replay is not seed-for-seed equivalent to the archived run, so its completed outcome does not change the original blocked-game count.

Replay files and their checksum manifest are in [`blocker-replays/original-source-plus-fix-full-stack-serial`](blocker-replays/original-source-plus-fix-full-stack-serial/). The artifacts were pushed in commit `a78b669e`.

## Player workload bumpers in the probe

The single completed probe had 36 player records. Its largest individual values were 22 carries and 113 rushing yards (Jonathan Taylor), 13 targets (Josh Downs), and 8 receptions (Alec Pierce). Those are below the historical alert boundaries of 45 carries, 296 rushing yards, 28 targets, and 21 receptions. This one-game check does not estimate tail rates or establish workload calibration.

## Status

The two original blocked outcomes are diagnosed and covered by deterministic tests against their audited source rows. The immutable 10K still records both as blocked; rerunning the full batch with the patched research code is a separate run and is not represented by this fix report.
