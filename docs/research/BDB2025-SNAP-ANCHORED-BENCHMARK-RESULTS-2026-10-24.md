# BDB2025 snap-anchored movement benchmark — coordinated results (2026-10-24)

**Scope:** weeks 1–5 of the 2022-season Big Data Bowl mirror. Weeks 6–9 were not read by the movement or cohort work.
Preregistration: `docs/research/BDB2025-SNAP-ANCHORED-BENCHMARK-PREREG-2026-10-24.md`. The frozen 49-row tackle manifest
(SHA-256 `3c16d3814847170edfc35ba3ca098ff3c82bbc5f8b36b22c05639780d6b41353`) is unchanged.

**Not claimed:** tackle prediction or success, yards, scoring, win probability, game or drive forecasts, calibrated player
physics, or any production change. No merge was made. Results are committed and pushed to the research branches below, not to `dev` or `main`.

## Coordinator decision

1. **Movement, effect size first.** Over 9,289 eligible plays in 80 games, constant acceleration reduces the 1.0 s position
   error relative to constant velocity by **113 mm** (game-clustered 95% CI [−122, −105] mm). The existing locomotion
   controller reduces it further by **3.7 mm** (CI [−5.1, −2.7] mm) over constant acceleration. That is about 0.4% of a
   0.92 m error. At 0.5 s the controller gain over constant acceleration is 0.74 mm. Acceleration extrapolation accounts for
   about 97% of the controller arm's total gain over constant velocity.
2. **The literal preregistered rule is met.** `moreSophisticatedPolicyJustified = true` (`summary.json`), and it still holds under
   the game-clustered interval. The rule has **no materiality floor**, so a 3.7 mm gain passes it.
3. **Coordinator conclusion: no more sophisticated movement policy is justified now.** The simplest adequate kinematic
   arm (constant acceleration, identical inputs) captures almost all of the measurable movement signal. The controller's
   residual gain is statistically real at this sample size but operationally negligible. This judgement is post hoc because
   the rule lacked a threshold. It is recorded as such, and I have not altered the rule.
4. **Decision needed from Micah:** whether to accept this reading, and whether to preregister a materiality threshold (for
   example, a minimum relative reduction over constant acceleration) before the weeks 6–9 held-out check. Until then, no new
   physics, calibration or Madden work starts from this result. This follows the delivery plan's rule that existing methods
   come first and that trajectory fidelity does not block the integration gates.

## Cohort (LP tracking agent)

- Origin is the `ball_snap` frame, cross-checked against `SNAP`. Inputs are frames ≤ origin. Scoring is at origin + 5 and origin + 10 frames.
- Reconciled to `plays.csv` on both sides for each week. Every week has zero plays missing from tracking and zero tracked plays
  missing from `plays.csv`.

| Week | Plays | Excluded: blank formation | Excluded: history incomplete | Excluded: snap definition | Eligible |
| --- | ---: | ---: | ---: | ---: | ---: |
| 1 | 1,952 | 28 | 7 | 4 | 1,913 |
| 2 | 1,809 | 18 | 5 | 4 | 1,782 |
| 3 | 1,959 | 27 | 6 | 1 | 1,925 |
| 4 | 1,830 | 18 | 6 | 4 | 1,802 |
| 5 | 1,906 | 32 | 3 | 4 | 1,867 |
| **Total** | **9,456** | **123** | **27** | **17** | **9,289** |

- The 17 `snap_definition_disagreement` plays are direct snaps labelled `snap_direct` with no `ball_snap` event. They are
  excluded under the prereg, not reclassified.
- The 27 `history_incomplete` plays start tracking fewer than five frames before the snap.
- Eligible plays all have all 22 players at origin + 10. An independent raw-row spot check on three plays matched the flags.
- Cohort manifest: `docs/research/bdb2025-snap-anchored-cohort-v1.csv` (9,456 rows). Staged windows are outside Git at
  `/root/nfl-tracking-data/bdb2025/snap-anchored-v1/`. The builder is `scripts/bdb2025/snap_anchored_cohort.py`.

## Play endpoints (LP sequence agent), kept separate

- Built from published `plays.csv` fields only, for the same 9,456 plays, in
  `docs/research/bdb2025-snap-cohort-play-endpoints-v1.csv`, produced by `scripts/bdb2025/snap_cohort_endpoints.py`.
- Published per play: `yardsGained` and `expectedPointsAdded` (all plays); `passResult` (pass plays only, 57–62% of plays by week);
  `penaltyYards` (about 46–50 per week); `playNullifiedByPenalty` (flag, all plays).
- **Drive results are unavailable.** `plays.csv` has no drive identifier, so drive outcomes were not reconstructed from
  possession changes (published-first rule).
- No outcome model was built or evaluated. The movement result says nothing about yards, scoring or drives.

## Contextual inputs for a formation or play-call baseline

By field name, the pre-snap fields are `offenseFormation`, `receiverAlignment`, `down`, `yardsToGo`, `gameClock`, and the
pre-snap score and win-probability fields. Post-play fields include `passResult`, `yardsGained`, `playAction`,
`dropbackType`, `expectedPointsAdded` and the penalty fields. This classification is by column name and is not a legal
determination. The mirror publishes no pre-snap play-call label. The rights status is user-reported and not independently assessed.

## Evidence preserved

- The earlier 40-play observed-tackle results are untouched. The identical-history comparison is a new, separate folder
  (`results/identical-history-2026-10-24/`), and it reproduces the earlier origin-included numbers exactly.
- The origin-included minimum-separation metric (0.000 median for every arm) is an artefact of including the origin, which
  every arm matches by construction. The corrected origin-excluded metric replaces it. The same origin-included separation
  RMSE scales every arm by √(5/6), so the ratio between arms still holds. The 0.170 vs 0.141 m figure quoted in
  `END-TO-END-FOOTBALL-SIMULATOR-DELIVERY-PLAN-2026-10-24.md` is the origin-included RMSE and should be updated to
  the corrected basis in the plan.

## Limits

- Weeks 1–5 are used for description and for the preregistered comparison, and nothing is fitted. Weeks 6–9 remain untouched.
- Movement is evaluated without pursuit, collision, ball or teammate-interaction models. Carrier identity is not an input.
- The data is an unofficial mirror of 2022-season tracking. Rights are user-reported.
- Intervals describe variation across these 80 games only. They are not a holdout.
- Disclosure: `plays.csv` rows for weeks 6–9 were read once for column-level counts (formation values and blanks). No
  tracking files for weeks 6–9 were read, and no outcome from those weeks was used.

## Where the evidence lives

- LP branch `research/nfl-snap-anchored-benchmark-2026-10-24` (worktree `/root/lp-nfl-snap-benchmark`): prereg, this doc, cohort
  manifest, endpoints extract, builder scripts. Committed and pushed.
- Gridiron branch `research/m4d-snap-anchored-movement-2026-10-24` (worktree `/root/gridiron-physics-m4d-snap-movement`): movement
  runners, `results/identical-history-2026-10-24/` and `results/snap-anchored-movement-2026-10-24/` (`report.md`, `summary.json`,
  `per_play.csv`, `game_clustered_check.json`), `cluster_decision_check.py`. Committed and pushed to the gridiron branch.
