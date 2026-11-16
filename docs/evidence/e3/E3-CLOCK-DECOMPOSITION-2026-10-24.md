# E3 clock decomposition audit, 2022 weeks 1–9 (2026-10-24)

Branch `research/nfl-e3-clock-decomposition-2026-10-24`, off `origin/main` (`80f394d8`). Worktree `/root/lp-nfl-e3-clock-audit`.
Nothing on the E2 branch or in the E2 worktree was touched. The three-model clock comparison is not started; this audit is the
input to it and waits for review.

Outputs: `e3-clock-decomposition-2026-10-24.csv` (one row per play, 15,768 rows) and `e3-clock-decomposition-2026-10-24.json`
(every count below). Script: `scripts/bdb/e3_clock_decomposition.py`. Flags extract: `scripts/bdb/e3_extract_nflverse_flags.py`.

## Scope and labelled exclusions

The audit covers the plays the coverage join verified on identifiers and context (`status == verified`): **15,768 plays**.
Two groups of tracked plays are not in that set, and both are excluded and labelled here:

| excluded group | plays | reason |
| --- | ---: | --- |
| overtime (quarter 5) | **134** | not in the verified set; the clock convention for overtime is not checked |
| spot side NA | **222** | not in the verified set; the spot cannot be checked, so the play is not verified |

The verified set contains no overtime play by construction.

## Sources (pinned)

- Verified pairs: `inputs/e3-tracking-join-pairs-2026-10-24.csv`, from commit `e1f56b85` on `research/nfl-e3-tracking-coverage-2026-10-24`.
  sha256 `80d89116…`.
- Earlier 15,765-pair set, for the denominator reconciliation: `inputs/bdb2022-join-pairs-2026-10-24.csv`, from commit `73b04e89`
  on `feat/nfl-bdb2022-join-2026-10-24`. sha256 `b39701be…`.
- nflverse flags: `inputs/nflverse-2022-w1-9-flags.csv`, from `/root/nflverse-raw/play_by_play_2022.parquet`. The parquet's sha256
  (`931121d8…`) matches `/root/nflverse-raw/SHA256SUMS`, checked before reading. Read with pyarrow in the venv; manifest in
  `inputs/nflverse-2022-w1-9-flags.manifest.json`.
- BDB tracking, `plays.csv`, `games.csv`: `/root/nfl-tracking-data/bdb2025/code-data/`, all checked against `SHA256SUMS.txt` in step 1.
- LP play-by-play: the dev database, read-only, season 2022, weeks 1–9.

## Rules and labels

Every derived quantity is labelled **observed** (a source value), **inferred** (computed from observed values by a stated rule), or
**unresolvable** (the sources cannot supply it for this play). The rule that decided each label is in the CSV beside the value.

| rule | quantity | label | decided by |
| --- | --- | --- | --- |
| R1 | snap time | observed | the play's `SNAP` frame in the tracking files |
| R2 | terminal time | observed, or unresolvable (R2u: no play-ending event at or after the snap) | the earliest tracking frame at or after the snap with a play-ending event label |
| R3 | in-play duration | inferred | R2 minus R1 |
| R4 | game-clock delta (snap to next snap, game clock) | inferred, or unresolvable: R4u1 no same-quarter next row; R4u2 quarter-end marker, runoff censored at the boundary; R4u3 negative | `game_seconds_remaining` of this play minus the next same-quarter play |
| R5 | residual (clock running with no play in progress) | inferred, or unresolvable (R5u) | R4 minus R3 |
| R6 | real snap-to-next-snap | inferred, or unresolvable: R6u next play not verified, or none in the quarter | the next same-quarter play's R1 minus this play's R1, when that play is verified |
| R7 | outcome type | observed | play-by-play flags: touchdown, interception, fumble_lost, sack, play_type, complete_pass |
| R8 | offense score differential, before the snap | observed | BDB `preSnapHomeScore` and `preSnapVisitorScore`, offense-relative |
| R9 | stoppage flags | observed; a blank timeout flag would be unresolvable (R9u) | nflverse `out_of_bounds` and `timeout`; play-by-play `penalty` |
| R10 | timeouts remaining | unresolvable | no per-play remaining counts in either source |
| R11 | penalty clock stop | unresolvable | the penalty flag gives no stoppage duration and no clock-stop mechanics |
| R12 | two-minute warning event | unresolvable; the late-half state is observed | the warning is not identifiable in the play-by-play |
| R13 | quarter, down, distance, possession, quarter clock at the snap | observed | verified against BDB on all 15,768 plays |

## Label counts (15,768 plays)

| quantity | observed | inferred | unresolvable |
| --- | ---: | ---: | ---: |
| snap time (R1) | 15,768 | — | 0 |
| in-play duration (R3) | — | 15,706 | 62 (R2u) |
| game-clock delta (R4) | — | 15,377 | 391: R4u2 374, R4u3 11, R4u1 6 |
| residual (R5) | — | 15,315 | 453 (R5u: 391 from R4 and 62 from R2) |
| real snap-to-next-snap (R6) | — | 11,181 | 4,587: 4,207 next play not verified, 380 none in quarter |
| outcome type (R7) | 15,768 | — | 0 |
| stoppage context (R9) | 15,768 | — | 0 |
| timeouts remaining (R10) | — | — | 15,768 |
| penalty clock stop (R11) | — | — | 15,768 |
| two-minute warning event (R12) | — | — | 15,768 |

The 62 unresolvable in-play durations are the same 62 plays the earlier weeks 1–9 audit had with no terminal event. That is
a cross-check: the two audits share their in-play failures.

## Stoppage context (observed, R9)

First matching flag, in this order: penalty, timeout, out of bounds, incomplete pass, touchdown, turnover, sack, otherwise none.

| context | plays |
| --- | ---: |
| none observed | 9,757 |
| incomplete pass | 2,794 |
| out of bounds | 1,614 |
| touchdown | 599 |
| sack | 523 |
| turnover | 234 |
| penalty | 211 |
| timeout | 36 |

Late half (second or fourth quarter, quarter clock at or below 120 s, observed from the play-by-play): **1,961** plays. Otherwise 13,807.

## Durations by outcome (seconds, observed or inferred as labelled)

| outcome | in-play (R3) median (n) | game-clock delta (R4) median (n) | residual (R5) median (n) | real snap-to-next-snap (R6) median (n) |
| --- | ---: | ---: | ---: | ---: |
| run | 4.4 (6,205) | 38.0 (6,059) | 33.6 (6,049) | 40.3 (4,966) |
| pass complete | 5.4 (5,117) | 36.0 (5,009) | 30.7 (5,009) | 40.2 (3,948) |
| pass incomplete | 4.4 (2,782) | 5.0 (2,821) | 0.2 (2,771) | 42.5 (1,761) |
| sack | 4.3 (545) | 40.0 (528) | 35.3 (526) | 43.7 (248) |
| interception | 4.7 (168) | 8.0 (165) | 2.8 (165) | 88.7 (136) |
| fumble | 4.95 (100) | 8.0 (98) | 3.1 (98) | 104.7 (82) |
| touchdown | 4.5 (609) | 5.0 (607) | 0.6 (607) | — (0 plays: the next play is a kickoff, which BDB does not track) |
| other (kneels, spikes, no-plays and similar) | 0.7 (180) | 22.0 (90) | 21.4 (90) | 37.8 (40) |

These medians match the earlier weeks 1–9 audit for every outcome. The counts differ only where this audit resolves the 62 plays
the earlier audit could not place on a snap.

## Real gap against the game clock, on plays where both are inferred

The unpaired medians above are over different samples. The paired difference is the stoppage signature (R6 minus R4, per play):

| outcome | n | median real minus clock (s) | share where real gap exceeds the clock by over 5 s | share where the clock exceeds the real gap by over 5 s |
| --- | ---: | ---: | ---: | ---: |
| run | 4,965 | 0.2 | 15.6% | 0.0% |
| pass complete | 3,947 | 0.4 | 25.1% | 0.0% |
| sack | 248 | 0.2 | 20.6% | 0.0% |
| pass incomplete | 1,761 | 37.8 | 100.0% | 0.0% |
| interception | 136 | 77.8 | 100.0% | 0.0% |
| fumble | 82 | 93.2 | 100.0% | 0.0% |
| other | 40 | 0.5 | 27.5% | 0.0% |

On clock-running plays the game-clock delta and the real gap agree to within a second. Plays that stop the clock show the gap:
an incomplete pass leaves about 38 s of real time between snaps that the clock does not count, and a turnover leaves 78–93 s.
The clock never runs more than 5 s ahead of the real gap on any play, which is the consistency check for this pair.

## Consistency checks

- The SNAP frame and the `ball_snap` label give the same time on all **15,706** plays that have both (largest difference 0.00 s).
- 62 plays have a SNAP frame and no `ball_snap` label. They are a different set from the 62 R2u plays (no overlap). All 62 have
  an in-play duration through the SNAP frame, so the snap definition does not drop them.
- Quarter and game clock agree with BDB on all 15,768 plays (they were verified in the join).

## Denominator: the 3,091 is explained, and the earlier figures are superseded

The earlier coverage report stated that 3,091 "does not reproduce from the same LP rows". That statement is wrong and is superseded
by this section. The coverage branch is not edited.

- **3,091 = 2,955 real drives + 136 null-drive groups.** LP `(game_id, drive)` groups over weeks 1–9 include a group with a null
  drive in every game. Those rows are mostly administrative rows with no play type (213 rows), extra points (29), no-plays (19), and three runs or passes. Grouping on `(game_id, drive)` with
  nulls included counts each game's null group as a drive.
- **2,849 classified = 2,846 real drives + 3 null groups.** The earlier criterion ("at least one run, pass, punt or field goal") picks
  up 2,846 real drives and three null groups, each of which holds a run or a pass.
- **The earlier counts reproduce exactly.** With the earlier 15,765 pairs and the null groups included, the classification is
  **789 complete, 2,014 partial, 46 none**, the earlier report's figures. Without the null groups, the same pairs give
  789 / 2,014 / 43, and the three null groups all fall in "none".
- **The 25.5% was computed on the wrong denominator.** 789 divided by 3,091 mixes in 242 groups that have no eligible play: 133
  null groups and 109 real drives.

Correct figures, on real drives only:

| | drives |
| --- | ---: |
| real drives (drive not null) | 2,955 |
| with at least one run, pass, punt or field goal | 2,846 |
| complete, earlier pairs (15,765) | 789 (27.7%) |
| complete, verified set (15,768) | 790 (27.8%); partial 2,013; none 43 |

The difference between the two rows is one drive: PHI–DET drive 8 moves from partial to complete when play 1634 is verified. The
other two newly verified plays (2806 and 3698) change no drive's class. The denominator 3,091 is retired.

## Limits

- Penalty clock stops and timeouts remaining are not in the sources. They are labelled unresolvable (R10, R11), not estimated.
- The two-minute warning is not identifiable in the play-by-play. The late-half state is observed (R12); whether observed runoffs
  carry a warning stoppage is not checked.
- The "other" outcome class mixes kneels, spikes and no-play rows. It is reported as one class and should not be modelled as one.
- Real snap-to-next-snap exists only when the next same-quarter play is in the verified set. 4,207 plays lack it for that reason.
  The next play is a no-play row (1,668), a punt (889), an extra point (512), a field goal (385), a run (315) or pass (396) outside
  the verified set, a kneel (30) or a kickoff (7). R6 is therefore a subset, and it is biased toward plays that are not followed by
  a special-teams play.
- Observed and inferred labels describe the play's own timestamps. They do not show what the simulator should draw; that is the
  three-model comparison, which is not started.

## Reproduce

```
/root/.venvs/nfl-parquet/bin/python scripts/bdb/e3_extract_nflverse_flags.py
python3 scripts/bdb/e3_clock_decomposition.py --out-dir docs/evidence/e3
```
