# SLC-CEG Phase 9 pre-registration: team strength tuned on drive points

Date: 2026-11-24. Version 2, written before any Phase 9 score. Version 1 (`7bbbb96c`) is replaced by this one on
Micah's specification; nothing was scored under it. One 30-drive smoke test of the version 1 script ran (arms C,
T1000, T10 on 2024); its numbers are not used.

One bounded follow-up experiment. It does not change any frozen artifact. The frozen week 12 E6 forecast (`ada09944`)
stays as it is. No full-game batch runs.

## Candidates

| candidate | what it is | status before Phase 9 |
|---|---|---|
| C | no team terms | baseline |
| E6 | Phase 6: dropback outcome offense ratio (k 300), targeted outcome defense ratio (k 1,000) | in the frozen week 12 forecast |
| E8 | E6 plus run yards and YAC hazard shifts, offense and defense, lambda 1,000 (Phase 8) | **failed research candidate** (Phase 8 H2: not useful at drive level); kept unchanged, evaluated again here only as a comparison arm |
| E9 | drive-tuned team strength, offense and defense tuned separately (this phase) | new |
| R | no simulator: each offense's walk-forward points per drive, shrunk (k tuned on 2024), plus the league mean by start zone | the bar |
| E-R | calibration of the simulator to cutoff-safe R (only if E9 fails) | conditional |

## Drive composition matches the runtime

Every arm runs the drive the way `ceg_game.Game.drive` runs it: the BC-selective generator (`ceg_harness.SELECTIVE`:
arm C for intent, air yards, run yards, dropback and targeted outcome, throwaway; arm B for YAC, scramble yards, sack
yards and fumbles), wrapped in `ceg_game.PenaltyProvider` (K8a pre-snap fouls, K8b live fouls, K9 type), punts from the
K4 model (`ceg_game.PuntModel`), the CEG clock (Phase 3 arm C), and `e1_drive.simulate`. A field goal attempt scores
3 x the K5 make probability at its 5-yard bin; a touchdown 7; anything else 0. Hazard shifts are fit against the base
hazard the runtime uses for that component (arm C for run yards, arm B for YAC).

The scrimmage generator, the special-teams models and the team terms' base models are fit on the seasons before the
tested season (2022-2023 for the 2024 tune, 2022-2024 for 2025 and 2026). The clock models are the Phase 3 ones
(2022-2024), shared by every arm.

## E9: the team package

Offense terms, strength lambda_O: run yards and YAC hazard shifts b_off (prior N(0, 1/lambda_O)); dropback outcome and
targeted outcome ratios (k = lambda_O). Defense terms, strength lambda_D: run yards and YAC shifts b_def; targeted
outcome ratio (k = lambda_D). Every term walk-forward: the previous season plus the tested season's weeks before the
drive's week.

## Tune on 2024 (bounded)

Every 2024 regular-season offensive drive start (first snap on first down, quarters 1 to 5, weeks 1 to 18), 2 draws
each, the same seeds for every arm.

- Step A: lambda_O in 1,000, 100, 30, 10, with lambda_D = 1,000. Choose lambda_O by the lowest corrected squared error.
- Step B: lambda_D in 100, 30, with the chosen lambda_O (lambda_D = 1,000 is from step A). Choose lambda_D the same way.

Seven arms in all, including C. No further search.

**Corrected squared error.** A drive's simulated expected points is the mean of n draws, so its squared error against
the actual points carries the Monte Carlo term var/n. Corrected error = mean over drives of (mean of draws - actual)^2
minus s^2 / n, with s^2 the drive's unbiased variance over its draws. Differences between arms use the corrected
errors of the same drives and seeds.

## Retrospective evaluation on 2025

Every 2025 regular-season drive start, 4 draws, arms C, E6, E8, E9, plus R. E9 counts if its corrected squared error
minus C's has a 95% game-bootstrap interval (1,000 resamples) below zero. Also reported: E9 minus E8, E9 minus E6, and
R minus E9.

**Realism guard (pre-registered).** E9 must not buy points with unrealistic component behaviour. E9 fails the guard if
its league mean expected points per drive differs from C's by more than 3%, or its league mean run yards per carry or
YAC per completion differs from C's by more than 2%.

## Measures reported for every arm (2025)

- Drive points: corrected squared error, raw squared error, mean expected points against actual.
- Ranking: correlation of simulated with actual points per drive over the 32 offenses, and over the 32 defenses
  (points allowed per drive).
- Between-team variance: the SD of team points per drive, simulated and actual, each with its noise removed
  (actual: minus the sampling variance of a team's mean; simulated: minus its Monte Carlo variance).
- Yardage distributions: generated yards per carry and YAC per completion (mean, 10th, 50th and 90th percentile, share
  of 10+ yard gains), against 2025 actual.
- Conversion rates: third and fourth down conversion on scrimmage plays, and red-zone touchdown rate per drive that
  reaches the 20, against 2025 actual.
- Per-play log loss on 2025 for each of E9's terms against its runtime base (walk-forward, game bootstrap).

## If E9 fails: E-R, one candidate

E-R sets each offense's run yards and YAC shift to b_T = (R_T - R_league) / s, where R_T is the offense's cutoff-safe
walk-forward points per drive (shrunk with R's pseudo-count), and s is the slope of league expected points per drive
against a common shift on every offense. s is measured once on 2024: 1,000 drives at b = -0.15 and +0.15, 2 draws each.
Defense terms as in E9's step-A defense (lambda_D 1,000). Evaluated on 2025 like E9, against C and R. No tuning beyond
the slope.

## Prospective confirmation

2026 week 12 and later games that have not been examined: once they are played, every drive start with C, E6, E8, E9
(and E-R if built) and R, scored as on 2025. This is a drive-level evaluation, not a full-game batch.

## Output

`PHASE9-TEAM-STRENGTH-REPORT.md`, and a short findings note for V2 and V1 Complete in
`docs/research/slc-ceg-2026-11-24/FINDINGS-FOR-V2-AND-V1-COMPLETE.md`.
