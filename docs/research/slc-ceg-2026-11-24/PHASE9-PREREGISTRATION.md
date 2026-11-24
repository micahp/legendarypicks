# SLC-CEG Phase 9 pre-registration: team strength tuned on drive points

Date: 2026-11-24. Written before any Phase 9 fit or score. Follows Phase 8 (`PHASE8-TEAM-STRENGTH-REPORT.md`): the
team terms counted per play, but per-play tuning chose the strongest shrinkage, and the simulator did not rank offenses
(r 0.19 against 0.67 for baseline R). Phase 9 chooses the strength of the offense team terms by drive points instead.

## The team package T(lambda)

Offense terms, all with strength lambda:
- run yards and yards after the catch: the Phase 8 hazard shift b_off, prior N(0, 1/lambda);
- dropback outcome (sack, scramble, attempt) and targeted outcome (complete, incomplete, interception): the Phase 6
  ratio with pseudo-count k = lambda.

Defense terms, fixed at their Phase 6 and 8 values (defense is weak, step 0 reliability 0.24): run yards and yards after
the catch b_def (lambda 1,000), targeted outcome ratio (k 1,000).

Every term is walk-forward: the previous season plus the target season's weeks before the drive's week.

Grid: lambda in 1,000, 100, 30, 10. Arm C (no team terms) runs beside them.

## Tune: 2024 drives

Every 2024 regular-season offensive drive start in weeks 1 to 18 (first snap on first down, quarters 1 to 5), 4
generated drives each, the same seeds for every arm, through `e1_drive.simulate` with the CEG clock. The scrimmage
generator and the team terms' base model are fit on 2022-2023 only; the clock models are the Phase 3 ones
(2022-2024), shared by every arm. Expected points as in Phase 8 H2 (touchdown 7; field goal attempt 3 x the 2022-2024
league make rate by 5-yard bin; else 0).

lambda is chosen by the lowest mean squared error of drive expected points against actual drive points.

## Confirm once: 2025 drives

Every 2025 regular-season drive start in weeks 1 to 18, generator fit on 2022-2024, arms C and T(chosen lambda), 4
draws, same seeds. T counts if its squared error minus C's has a 95% game-bootstrap interval below zero (1,000
resamples). Reported beside it, not used for the decision: the offense correlation of simulated with actual points per
drive over the 32 offenses, the offense SD, and baseline R (as in Phase 8, its pseudo-count tuned on 2024).

## Reported, not used to choose

The 2026 weeks 1 to 11 drives (examined in Phase 8) with T(chosen lambda), the same seeds as Phase 8 H2.

## If T counts on 2025

A week 12 2026 forecast with SEL plus T(chosen lambda) at 200 seeds per game, committed before the first week 12
kickoff (2026-11-25 20:00 ET) if the runs finish in time, and graded beside the frozen E6 forecast (`ada09944`).
If they do not finish in time, the forecast is made for week 13 instead, before its first kickoff.

## Not in Phase 9

New components, players, defense strength tuning, and game-margin tuning. Two processes at most on this box.
