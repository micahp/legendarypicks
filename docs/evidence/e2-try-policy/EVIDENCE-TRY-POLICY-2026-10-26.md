# Two-point decision: four-arm pinned-snapshot comparison and verdict (2026-10-26)

Research only. No production default changes. The engine's unconditional share stays the default (`ref.try_policy` is None).

## 1. Verdict

**K=1 ADOPT FOR RESEARCH, not as the default.**

- Historically better. On the three chronological folds, K=1 has the lowest Brier score and log loss, and each paired
  interval against the unconditional rate excludes zero (section 6). The 2023 fold chose K=1; the 2024 and 2025 folds were
  confirmation folds, already read, so they are not an untouched test.
- Game completion is unchanged. Valid full games are 244 of 300 under every arm. Blocked-before-regulation counts are 42 under
  every arm. Ties at regulation end are 13 under every arm. Two seeds move from valid to tied and two the other way (section 5).
- Game scores move only slightly. Paired home points, away points and totals move by 0.02 to 0.07 points. The away-points and
  home-minus-away intervals exclude zero; section 8 explains why the second is not yet a finding. Winners do not change on any
  of the 242 seeds valid in both arms.
- Opening drives improve but are not fully matched to history. The unconditional share gives 10.7% (11 of 103) and K=1 gives
  2.9% (3 of 103). The historical rate is 0.78% (4 of 510). See section 7.

Open items before any stronger claim: section 8.

## 2. Inputs and fingerprints

All four arms share one observed reference and one run snapshot. `compare_validity_arms.py` asserts this before any difference is
computed, and it passed.

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
| unconditional (post tie fix) | 244 | 0 | 13 | 42 | 1 |
| K=1 | 244 | 0 | 13 | 42 | 1 |
| K=25 | 244 | 0 | 13 | 42 | 1 |
| unconditional (pre tie fix) | 244 | 0 | 15 | 40 | 1 |

Blocked before regulation end, by named reason (post-fix, identical across the three post-fix arms): safety free kick 23;
blocked-kick outcome unresolved 17 (13 unclassified field goal, 2 period expired at an unresolved spot, 1 period expired, 1 kicking
recovery outside the field); thin kick cell 2. Every blocked seed carries a named reason. The earlier 59-seed breakdown
(unresolved 24, safety 17, overtime 11, other 7) came from a different reference and cannot be matched seed by seed. This run
accounts for all 300 seeds: 244 valid + 42 blocked + 13 tied + 1 failed.

## 4. Tie fix (`bfc32bde`)

- The pre-fix code set `tied` whenever the score was level, including blocked games. Seeds 180 and 182 were blocked before
  regulation end at a level score, so pre-fix they were labelled `tied_at_regulation_end`.
- After the fix, those seeds are `blocked_before_regulation_end`. Their status, blocker, points and every try are identical
  before and after.
- Across all 300 seeds, status, blocker, points and tries change on 0 seeds. The fix changes labels and metadata only. It does
  not change any simulated game.
- The regression test `test_a_game_blocked_on_its_first_drive_keeps_the_attempt` fails on the pre-fix code
  (`AssertionError: True is not false`) and passes on the fixed code.

## 5. Failed seed 106: a stats defect, not a policy effect

Seed 106 fails in every arm with `pregame player/team stats do not reconcile for A: {'offensive_td': (0, 1)}`. The cause is
in `game_stats.py`, not in the try policy. Team A's only touchdown was a blocked-punt return. `offensive_touchdowns` is set only
when a team has an offensive touchdown, so for A the key is absent. `team.get('offensive_touchdowns', team.get('touchdowns', 0))`
then returns A's total touchdowns (1), while the player lines correctly show 0. The defect falls back to a wrong default; it does
not refuse a real inconsistency.

The validator refused a correct game. The seed is reported as `failed`, not excluded. The fix would make the expected value 0 when
the key is absent. It would change validity counts for every arm, so it is not made here. Decision needed: fix and rerun the
four arms, or keep it as a documented failure.

## 6. Historical decision evaluation (chronological, intervals clustered by game)

Brier score and log loss on actual regular-season tries. Each fit uses earlier seasons only. Intervals are 95% and clustered by
game (tries from one game are not independent). Differences are against the unconditional fit league rate.

| test season | role | tries (games) | model | Brier | dBrier [95% CI] | log loss | dLL [95% CI] |
| --- | --- | --- | --- | ---: | --- | ---: | --- |
| 2023 | selection | 1296 (269) | unconditional | 0.08844 | — | 0.32093 | — |
| 2023 | | | K=1 | 0.05250 | −0.03594 [−0.04528, −0.02661] | 0.21508 | −0.10585 [−0.14088, −0.07082] |
| 2023 | | | K=25 | 0.07335 | −0.01509 [−0.01909, −0.01109] | 0.25495 | −0.06598 [−0.08396, −0.04800] |
| 2024 | confirmation | 1376 (270) | unconditional | 0.08850 | — | 0.32098 | — |
| 2024 | | | K=1 | 0.04619 | −0.04231 [−0.05293, −0.03168] | 0.19020 | −0.13078 [−0.16856, −0.09300] |
| 2024 | | | K=25 | 0.06493 | −0.02356 [−0.02908, −0.01805] | 0.22863 | −0.09236 [−0.11291, −0.07181] |
| 2025 | confirmation | 1390 (271) | unconditional | 0.08362 | — | 0.30742 | — |
| 2025 | | | K=1 | 0.04256 | −0.04106 [−0.05130, −0.03081] | 0.16546 | −0.14196 [−0.17587, −0.10805] |
| 2025 | | | K=25 | 0.05786 | −0.02576 [−0.03225, −0.01927] | 0.20551 | −0.10191 [−0.12351, −0.08031] |

Sparse situations. Test tries are grouped by how many training tries fell in their finest margin × opening × period cell.
When the training count is 1–4 or 5–24, K=1 has the lower Brier score in every fold. In 2023 it is 0.097 against K=25's 0.174
for 1–4, and 0.054 against 0.070 for 5–24. The 2024 and 2025 folds agree in direction. When the training count is zero, the two
are within 0.002 Brier of each other (in 2023, K=1 is slightly worse). That group has few test tries (15 to 64 per fold), so its
estimate is weak. The finest-cell table is in
`finest-cells-2022-2025.csv`: 266 cells, 213 with fewer than 25 tries, holding 1,564 of 5,368 tries. Each row gives the count, the
smoothing parent, and the K=1 and K=25 probabilities.

The 2026 regular-season tries (weeks 1 to 7) are reserved and have not been extracted or evaluated (section 9).

## 7. Attempt distribution and the historical populations

| population | tries | two-point | rate (95% Wilson) |
| --- | ---: | ---: | --- |
| historical first touchdown (2022–2025 REG) | 1079 | 12 | 1.11% (0.64–1.93) |
| historical opening drive (2022–2025 REG) | 510 | 4 | 0.78% (0.31–2.00) |
| simulated first touchdown, unconditional | 290 | 30 | 10.34% (7.34–14.38) |
| simulated first touchdown, K=1 | 290 | 5 | 1.72% (0.74–3.97) |
| simulated opening drive, unconditional | 103 | 11 | 10.68% (6.07–18.12) |
| simulated opening drive, K=1 | 103 | 3 | 2.91% (1.00–8.22) |

Overall the K=1 arm makes 92 two-point attempts in 1,150 tries, against 111 under the unconditional share. The
unconditional share is 9.55% (509 of 5,330 published kick attempts), so the simulated 9.65% is consistent with it.

The decision-sampling check (simulated decisions against the policy's own recorded probabilities) is separate from the historical
evaluation. All 1,150 recorded probabilities reproduce exactly from their situation fields. Expected against observed two-point
attempts for the K=1 arm: all tries 92.18 against 92 (P 0.52); first touchdown 3.48 against 5 (P 0.27); opening drive 0.56
against 3 (P 0.020). The opening-drive count is the only borderline one, and with three subgroups tested it is not conclusive.
The historical opening-drive rate of 0.78% is itself a subgroup check. K=1 predicts 0.55% for the simulated opening-drive
situations, so the excess sits in the simulator's sampling, not in the policy's predictions.

## 8. Paired game-level effects (identical seeds, 300)

Differences are first minus second, with 95% intervals from per-seed paired differences. Each seed is one game, so
seed-level intervals are already game-level.

| comparison | valid in both | home points | away points | total | home minus away | winner changes |
| --- | ---: | --- | --- | --- | --- | ---: |
| K=1 − unconditional | 242 | −0.054 [−0.111, +0.004] | +0.070 [+0.006, +0.134] | +0.017 [−0.071, +0.104] | −0.124 [−0.208, −0.040] | 0 of 242 |
| K=25 − unconditional | 242 | −0.029 [−0.075, +0.018] | +0.050 [−0.003, +0.102] | +0.021 [−0.051, +0.092] | −0.079 [−0.147, −0.010] | 0 of 242 |
| K=1 − K=25 | 244 | −0.025 [−0.062, +0.013] | +0.020 [−0.020, +0.061] | −0.004 [−0.060, +0.052] | −0.045 [−0.099, +0.009] | 0 of 244 |

Validity flips (McNemar exact p = 1.000 in each comparison): K=1 gains seeds 150 and 278 and loses seeds 59 and 117. All four are
regulation ties in one arm and valid in the other. Two-point tries per game: K=1 −0.050 [−0.143, +0.043]; two-point made
−0.012 [−0.069, +0.044]. The attempt change is not significant.

The home-minus-away shift for K=1 (−0.12 points, interval excluding zero) is unexplained. The policy depends only on margin,
period, opening drive and first touchdown, and none of these is team-specific. K=25 shows a similar shift, and the K=1 minus
K=25 difference is not significant. With several contrasts in this table, one interval at 95% is weak evidence. Open item 2
asks for a home–away null control.

## 9. Untouched cohort

Reserved, not extracted or evaluated: regular-season tries from 2026 weeks 1 to 7, the games with final scores through 2026-10-25
(about 106 games). Nothing in the fitting, selection or evaluation above reads this window. The pinned KC–SEA snapshot is a 2026
week 7 game, but only its pregame inputs are used, and the simulator's reference is built from 2022–2025 only. Build the cohort
with a fixed game-date cutoff of 2026-10-25, then score K=1, K=25 and the unconditional share once, after the default question is
settled.

## 10. Open items

1. **Seed 106 reconciliation defect** (section 5). Fix and rerun all four arms, or keep it documented. Decision needed.
2. **Home–away shift** (section 8). Run a null control: swap the home and away roles of the same seeds and check that the shift
   reverses sign and disappears. Until then, do not describe the shift as a finding.
3. **Opening-drive sampling count** (section 7). One subgroup at P 0.020. Confirm with more seeds, or check the draw, before
   relying on the subgroup.
4. **Historical snapshot reproducibility.** Preserve both `first_observed` and `last_refreshed` for schedule rows, and keep prior
   versions of changed fields. Until then, `build()` cannot reproduce a snapshot once its schedule row is re-ingested.
5. **2026 cohort.** Evaluate once, after the default question is settled.

## 11. Reproduce

```
python3 scripts/nfl_sequence/run_pinned_validity.py --policy unconditional --out docs/evidence/e2-try-policy/validity-300-unconditional.csv --summary docs/evidence/e2-try-policy/validity-300-unconditional.json
python3 scripts/nfl_sequence/run_pinned_validity.py --policy K=1 --out docs/evidence/e2-try-policy/validity-300-k1.csv --summary docs/evidence/e2-try-policy/validity-300-k1.json
python3 scripts/nfl_sequence/run_pinned_validity.py --policy K=25 --out docs/evidence/e2-try-policy/validity-300-k25.csv --summary docs/evidence/e2-try-policy/validity-300-k25.json
python3 scripts/nfl_sequence/evaluate_try_policy.py --cells docs/evidence/e2-try-policy/finest-cells-2022-2025.csv
python3 scripts/nfl_sequence/compare_validity_arms.py
```

The pre-fix arm is `run_pinned_validity.py --policy unconditional` on a clean export of commit `80576ba6`, with the runner copied in.
Its outputs are `validity-300-unconditional-pre-tie-fix.csv` and `.json`.
