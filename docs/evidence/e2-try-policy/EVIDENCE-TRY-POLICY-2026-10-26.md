# Two-point decision: four-arm pinned-snapshot comparison and verdict (2026-10-26)

Research only. No production default changes. The engine's unconditional share stays the default (`ref.try_policy` is None).

## 1. Verdict

**K=1 ADOPT FOR RESEARCH, not as the default.** The verdict is unchanged after the rerun described in section 5.

- Historically better. On the three chronological folds, K=1 has the lowest Brier score and log loss, and each paired
  interval against the unconditional rate excludes zero (section 6). The 2023 fold chose K=1; the 2024 and 2025 folds were
  confirmation folds, already read, so they are not an untouched test.
- Game completion is unchanged apart from the seed-106 fix. Valid full games are 245 of 300 under every arm. Blocked-before-regulation
  counts are 42 under every arm. Ties at regulation end are 13 under every arm. Two seeds move from valid to tied and two the other
  way (section 8).
- Game scores move only slightly. Paired home points, away points and totals move by 0.01 to 0.07 points. The away-points and
  home-minus-away intervals exclude zero; section 8 explains why the second is not yet a finding. Winners do not change on any of
  the 243 seeds valid in both arms.
- Opening drives improve but are not fully matched to history. The unconditional share gives 10.7% (11 of 103) and K=1 gives
  2.9% (3 of 103). The historical rate is 0.78% (4 of 510). See section 7.

Open items before any stronger claim: section 10.

## 2. Inputs and fingerprints

All four arms share one observed reference and one run snapshot. `compare_validity_arms.py` asserts this before any difference is
computed, and it passed on the rerun.

| | value |
| --- | --- |
| observed reference sha256 (all arms) | `0e4fb1b302f7…` |
| run snapshot sha256 (all arms) | `44a19b2d0925…` |
| pinned snapshot sha256 (input file) | `53f5aafb9ce5…` |

The pinned file embeds reference `5d0bf76f…`, which is stale. The difference is confined to the participants table, where
timeout club codes changed (`LA`/`WAS` → `LAR`/`WSH`, commit `3a78a41a`). At commit `428fbef0`, the same database reproduces
`5d0bf76f…` exactly, which confirms the cause. The runner writes the current reference into the snapshot before resealing, so
the random streams differ from the pinned file's. The earlier 241/300 run has no per-seed output on disk, so it cannot be
compared seed by seed with these arms.

`pregame_snapshot.build()` cannot rebuild this snapshot from the live database. The schedule row for `2026_07_KC_SEA` was
re-ingested at 10:00 UTC on 2026-10-26, after the as-of time, and the as-of guard refuses it. The ingest overwrote the original
`ingested_at`. This is a reproducibility defect for historical snapshots. It is not fixed here.

## 3. Outcomes by arm (300 seeds, exclusive)

| arm | valid | regulation end, not valid | tied at regulation end | blocked before regulation end | failed |
| --- | ---: | ---: | ---: | ---: | ---: |
| unconditional (post tie fix) | 245 | 0 | 13 | 42 | 0 |
| K=1 | 245 | 0 | 13 | 42 | 0 |
| K=25 | 245 | 0 | 13 | 42 | 0 |
| unconditional (pre tie fix) | 245 | 0 | 15 | 40 | 0 |

Blocked before regulation end, by named reason (post-fix, identical across the three post-fix arms): safety free kick 23;
blocked-kick outcome unresolved 17 (13 unclassified field goal, 2 period expired at an unresolved spot, 1 period expired, 1 kicking
recovery outside the field); thin kick cell 2. Every blocked seed carries a named reason. The earlier 59-seed breakdown
(unresolved 24, safety 17, overtime 11, other 7) came from a different reference and cannot be matched seed by seed. This run
accounts for all 300 seeds: 245 valid + 42 blocked + 13 tied + 0 failed.

## 4. Tie fix (`bfc32bde`)

- The pre-fix code set `tied` whenever the score was level, including blocked games. Seeds 180 and 182 were blocked before
  regulation end at a level score, so pre-fix they were labelled `tied_at_regulation_end`.
- After the fix, those seeds are `blocked_before_regulation_end`. Their status, blocker, points and every try are identical
  before and after.
- Across all 300 seeds, status, blocker, points and tries change on 0 seeds. The fix changes labels and metadata only. It does
  not change any simulated game.
- The regression test `test_a_game_blocked_on_its_first_drive_keeps_the_attempt` fails on the pre-fix code
  (`AssertionError: True is not false`) and passes on the fixed code.
- The pre-fix arm for the rerun is the current HEAD with only the tie line restored, so the stats fix in section 5 is in both
  arms and the tie comparison isolates the tie line.

## 5. Seed 106: resolved in `ec150c2f`

Seed 106 failed in every arm before the fix, with `pregame player/team stats do not reconcile for A: {'offensive_td': (0, 1)}`.
Team A's only touchdown was a blocked-punt return. `offensive_touchdowns` is set only when a team has an offensive touchdown, so
for A the key was absent. The reconciliation fell back to A's total touchdowns (1), while the player lines correctly showed 0. The
expected value now defaults to zero when the key is absent. The gate still refuses an offensive touchdown with no player line, and
a test covers both cases.

**Rerun.** All four arms were rerun on the fixed code, and every seed was diffed against the previous outputs. In all four arms the
only changed seed is 106, which moved from `failed` to `valid`. The other 299 seeds are identical in every field. Seed 106 ends
13 to 14 under the unconditional share, and 12 to 14 under K=1, which took one two-point try. The reference and snapshot fingerprints
are unchanged.

## 6. Historical decision evaluation (chronological, intervals clustered by game)

Brier score and log loss on actual regular-season tries. Each fit uses earlier seasons only. Intervals are 95% and clustered by
game (tries from one game are not independent). Differences are against the unconditional fit league rate. The evaluation does not
use the simulator, so the rerun does not change this section.

| test season | role | tries (games) | model | Brier | dBrier [95% CI] | log loss | dLL [95% CI] |
| --- | --- | --- | --- | ---: | --- | ---: | --- |
| 2023 | selection | 1296 (269) | unconditional | 0.08844 | n/a | 0.32093 | n/a |
| 2023 | | | K=1 | 0.05250 | −0.03594 [−0.04528, −0.02661] | 0.21508 | −0.10585 [−0.14088, −0.07082] |
| 2023 | | | K=25 | 0.07335 | −0.01509 [−0.01909, −0.01109] | 0.25495 | −0.06598 [−0.08396, −0.04800] |
| 2024 | confirmation | 1376 (270) | unconditional | 0.08850 | n/a | 0.32098 | n/a |
| 2024 | | | K=1 | 0.04619 | −0.04231 [−0.05293, −0.03168] | 0.19020 | −0.13078 [−0.16856, −0.09300] |
| 2024 | | | K=25 | 0.06493 | −0.02356 [−0.02908, −0.01805] | 0.22863 | −0.09236 [−0.11291, −0.07181] |
| 2025 | confirmation | 1390 (271) | unconditional | 0.08362 | n/a | 0.30742 | n/a |
| 2025 | | | K=1 | 0.04256 | −0.04106 [−0.05130, −0.03081] | 0.16546 | −0.14196 [−0.17587, −0.10805] |
| 2025 | | | K=25 | 0.05786 | −0.02576 [−0.03225, −0.01927] | 0.20551 | −0.10191 [−0.12351, −0.08031] |

Sparse situations. Test tries are grouped by how many training tries fell in their finest margin × opening × period cell.
When the training count is 1–4 or 5–24, K=1 has the lower Brier score in every fold. In 2023 it is 0.097 against K=25's 0.174
for 1–4, and 0.054 against 0.070 for 5–24. The 2024 and 2025 folds agree in direction. When the training count is zero, the two
are within 0.002 Brier of each other (in 2023, K=1 is slightly worse). That group has few test tries (15 to 64 per fold), so its
estimate is weak. The finest-cell table is in `finest-cells-2022-2025.csv`: 266 cells, 213 with fewer than 25 tries, holding 1,564
of 5,368 tries. Each row gives the count, the smoothing parent, and the K=1 and K=25 probabilities.

The 2026 regular-season tries (weeks 1 to 7) are reserved and have not been extracted or evaluated (section 9).

## 7. Attempt distribution and the historical populations

| population | tries | two-point | rate (95% Wilson) |
| --- | ---: | ---: | --- |
| historical first touchdown (2022–2025 REG) | 1079 | 12 | 1.11% (0.64–1.93) |
| historical opening drive (2022–2025 REG) | 510 | 4 | 0.78% (0.31–2.00) |
| simulated first touchdown, unconditional | 291 | 30 | 10.31% (7.32–14.34) |
| simulated first touchdown, K=1 | 291 | 5 | 1.72% (0.74–3.96) |
| simulated opening drive, unconditional | 103 | 11 | 10.68% (6.07–18.12) |
| simulated opening drive, K=1 | 103 | 3 | 2.91% (1.00–8.22) |

Overall the K=1 arm makes 93 two-point attempts in 1,153 tries, against 111 under the unconditional share. The unconditional
share is 9.55% (509 of 5,330 published kick attempts), so the simulated 9.63% is consistent with it. The K=1 arm's mean predicted
probability is 0.0808 and its realized rate is 0.0807.

The decision-sampling check (simulated decisions against the policy's own recorded probabilities) is separate from the historical
evaluation. All 1,153 recorded probabilities reproduce exactly from their situation fields. Expected against observed two-point
attempts for the K=1 arm: all tries 93.17 against 93 (P 0.52); first touchdown 3.48 against 5 (P 0.27); opening drive 0.56
against 3 (P 0.020). The opening-drive count is the only borderline one, and with three subgroups tested it is not conclusive.
The historical opening-drive rate of 0.78% is itself a subgroup check. K=1 predicts 0.55% for the simulated opening-drive
situations, so the excess sits in the simulator's sampling, not in the policy's predictions.

## 8. Paired game-level effects (identical seeds, 300)

Differences are first minus second, with 95% intervals from per-seed paired differences. Each seed is one game, so
seed-level intervals are already game-level.

| comparison | valid in both | home points | away points | total | home minus away | winner changes |
| --- | ---: | --- | --- | --- | --- | ---: |
| K=1 − unconditional | 243 | −0.058 [−0.115, +0.000] | +0.070 [+0.006, +0.134] | +0.012 [−0.075, +0.100] | −0.128 [−0.212, −0.043] | 0 of 243 |
| K=25 − unconditional | 243 | −0.029 [−0.075, +0.017] | +0.049 [−0.003, +0.101] | +0.021 [−0.050, +0.091] | −0.078 [−0.147, −0.010] | 0 of 243 |
| K=1 − K=25 | 245 | −0.029 [−0.067, +0.010] | +0.020 [−0.020, +0.060] | −0.008 [−0.065, +0.049] | −0.049 [−0.103, +0.005] | 0 of 245 |

Validity flips (McNemar exact p = 1.000 in each comparison): K=1 gains seeds 150 and 278 and loses seeds 59 and 117. All four are
regulation ties in one arm and valid in the other. Two-point tries per game, valid in both: K=1 −0.045 [−0.138, +0.048]; two-point
made −0.012 [−0.069, +0.044]. The attempt change is not significant.

The home-minus-away shift for K=1 (−0.13 points, interval excluding zero) is unexplained. The policy depends only on margin,
period, opening drive and first touchdown, and none of these is team-specific. K=25 shows a similar shift, and the K=1 minus
K=25 difference is not significant. With several contrasts in this table, one interval at 95% is weak evidence. Open item 2
asks for a home-away null control.

## 9. Untouched cohort

Reserved, not extracted or evaluated: regular-season tries from 2026 weeks 1 to 7, the games with final scores through 2026-10-25
(about 106 games). Nothing in the fitting, selection or evaluation above reads this window. The pinned KC-SEA snapshot is a 2026
week 7 game, but only its pregame inputs are used, and the simulator's reference is built from 2022–2025 only. Build the cohort
with a fixed game-date cutoff of 2026-10-25, then score K=1, K=25 and the unconditional share once, after the default question is
settled.

## 10. Open items

1. **Home-away shift** (section 8). Run a null control inside the simulation: reverse the team roles of the same seeds, keeping the
   random-number setup comparable, and check that the shift reverses sign and disappears. Relabelling the output would reverse the
   sign trivially, so it is not a valid control. Also verify that the model is team-symmetric. Until then, do not describe the shift
   as a finding.
2. **Opening-drive sampling count** (section 7). One subgroup at P 0.020. Confirm with a larger independent replication, not with a
   probability adjustment on these seeds.
3. **Historical snapshot reproducibility.** Preserve both `first_observed` and `last_refreshed` for schedule rows, and keep prior
   versions of changed fields. Until then, `build()` cannot reproduce a snapshot once its schedule row is re-ingested. The
   pinned file's stale reference is the same class of problem.
4. **2026 cohort.** Evaluate once, after the default question is settled.

## 11. Reproduce

```
python3 scripts/nfl_sequence/run_pinned_validity.py --policy unconditional --out docs/evidence/e2-try-policy/validity-300-unconditional.csv --summary docs/evidence/e2-try-policy/validity-300-unconditional.json
python3 scripts/nfl_sequence/run_pinned_validity.py --policy K=1 --out docs/evidence/e2-try-policy/validity-300-k1.csv --summary docs/evidence/e2-try-policy/validity-300-k1.json
python3 scripts/nfl_sequence/run_pinned_validity.py --policy K=25 --out docs/evidence/e2-try-policy/validity-300-k25.csv --summary docs/evidence/e2-try-policy/validity-300-k25.json
python3 scripts/nfl_sequence/evaluate_try_policy.py --cells docs/evidence/e2-try-policy/finest-cells-2022-2025.csv
python3 scripts/nfl_sequence/compare_validity_arms.py
```

The pre-fix arm is `run_pinned_validity.py --policy unconditional` on a clean export of HEAD in which the two tie lines in
`game_state.py` are replaced by the parent's single line, `tied = self.points['A'] == self.points['B']`. Its outputs are
`validity-300-unconditional-pre-tie-fix.csv` and `.json`.
