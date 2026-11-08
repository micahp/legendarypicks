# Pre-registration: ablation A, restore sack mass

Status: DRAFT, NOT FROZEN. The thresholds are confirmed as directional minimums. Freeze the code commit and this file together, record the freeze commit in the results, and only then run the baseline. Any later change is a deviation and must be reported as one.

## Question

Does the engine's sack rate on dropbacks explain part of the team-scoring shortfall in the low-score band? Restoring the sack rate by situation cell should move the low-score shares toward the observed values while leaving the mean team score near baseline, and without changing yardage, so that ablation C can be interpreted separately.

## Hypothesis (H_A)

Substituting sacks for a share of incomplete passes, with the substitution rate set cell by cell to the observed sack rate, raises the share of team-games scoring at most 3 points and at most 10 points, with mean team points within 0.3 of baseline.

## Measurements (definitions fixed here)

- **Observed sack rate by cell.** Sacks divided by dropbacks in `nfl_pbp`, seasons 2022–2025, regular season (weeks 1–18), quarters 1–4, `play_type = 'pass'`, grouped by `e0_single_play.pool_key(down, ydstogo, yardline_100)`. Produced by `scripts/nfl_sequence/obs_sack_cells.py` and committed as `obs_sack_cells.json` in this folder, which holds the query and the counts. Pinned sha256: `3010131cc898d1c534a1d023b7d6c31dba6fd94d2506eaf60bb952d61a2a31e8`. Pooled observed rate: 6.91% (5,267 sacks in 76,195 dropbacks). Cells with fewer than 100 dropbacks (40 of 115) take the shrunk rate `(sacks + 100 × pooled) / (dropbacks + 100)`; the rest take the raw rate.
- **Engine sack rate.** `sacks_taken / (pass_attempts + sacks_taken)` from the team box score, pooled.
- **Turnovers per team-game (engine-comparable).** 1.098, the figure used throughout the 2025 report. Gated in ablation B, not here. Reported in A as a diagnostic.
- **Team points share.** Share of team-games scoring at most 3 points, and at most 10 points, per matchup and pooled.
- **Mean team points.** Pooled over completed team-games.
- **Diagnostics (not gated).** Yards per team-game, yards per point, share of team-games with at least 200 total yards, and field-goal and touchdown counts per team-game.

## Baseline, seeds and clustering

- Snapshots: the 13 verified Sunday snapshots, pinned by sha256 in `slc-sunday-smoke-2026-11-08/snapshots/`.
- Seeds: 1–200 for each matchup. 2,600 games, 13 matchups.
- Baseline and ablation run from the same frozen code commit. The switch is the only difference.
- Clustering: the bootstrap resamples the 13 matchups with replacement, and then resamples games within each drawn matchup. Intervals are 95% percentile intervals over 2,000 resamples. Team-games are not resampled independently, because they share games.

## The change under test (ablation A)

For each dropback whose drawn outcome is `pass_incomplete`, substitute a sack with probability q(cell):

- r(cell) = the simulator's sack share for the cell, read from the cell's outcome counts at runtime.
- inc(cell) = the simulator's incomplete share for the cell, read the same way.
- q(cell) = max(0, (obs(cell) − r(cell)) / inc(cell)), where obs(cell) is the observed sack rate for that cell, with shrinkage toward the pooled observed rate for cells with fewer than 100 dropbacks, using a pseudo-count of 100.

Other outcomes are unchanged. Restricting the substitution to incomplete passes means no completed pass or run changes yardage, so the substitution does not move ablation C. The switch is `restore_sack_mass`, default off. With the switch off the code takes no extra random draw, so the baseline is unchanged.

## Decision rules

1. **Mechanism.** The engine's sack share on dropbacks moves to within 1.0 percentage point of the observed pooled rate, 6.9%.
2. **At most 3 points.** The share of team-games scoring at most 3 points rises by at least 0.3 percentage points, with a 95% interval that excludes zero.
3. **At most 10 points.** The share of team-games scoring at most 10 points rises by at least 1.0 percentage point, with a 95% interval that excludes zero.
4. **Mean points.** The absolute change in mean team points against baseline is at most 0.3.
5. **Non-sack outcomes.** The substitution is restricted to incomplete passes, so it cannot change any completion. The gate checks that it did not:
   - completions per dropback change by less than 0.5 percentage points;
   - yards per completion change by less than 1%;
   - yards per pass attempt, excluding sack yardage, change by less than 1%.

   A larger change means the substitution has reached a non-sack outcome, and the result is invalid.

6. **Yardage diagnostic (not a gate).** Yards per team-game change by no more than 4%. Converting the target share of dropbacks from incompletion to sack removes about 11 yards per team-game, roughly 2.9% of scrimmage yards, and that movement is expected. A change beyond 4% means the implementation has done something other than the substitution, and the result is invalid.

The rule 5 gate on team-game yardage (under 1%) is replaced by the non-sack gates above. Under the substitution, team-game yardage falls by about 2.9% by arithmetic, so the old gate could never pass.

The earlier target band of 2.5–3.0% for the at-most-3 share is dropped. It is tighter than the observed interval, so it isn't a useful gate.

## Outcomes

- **Pass.** Rules 1–6 hold. Ablation B runs next, under its own pre-registration.
- **Partial.** Rule 1 holds, but rule 2 or 3 does not. Sacks are not the dominant mechanism. B is not run on this basis.
- **Falsified.** Rule 1 holds, and neither the at-most-3 share nor the at-most-10 share moves by its threshold. The sack mechanism is rejected. B and C wait for the mechanism to be revisited.
- **Invalid.** Rule 1 fails, rule 5 fails, or rule 6 fails. The test says nothing about the mechanism. Fix the implementation under a new pre-registration.

## Power

With 2,600 games and 5,200 team-games, the standard error on a share near 3% is about 0.24 percentage points before clustering, and wider after it. A 0.3-point change may fall inside the interval. In that case the result is inconclusive, and it is reported as inconclusive, not as a pass or a falsification.

## Not in scope

Yardage (ablation C), giveaways (ablation B) and the pass-through re-landing (ablation D) are separate pre-registrations. Calibration to observed outcomes beyond the sack substitution is not allowed inside A.

## Open items before freeze

- Confirm the shrinkage pseudo-count of 100 and the use of the pooled observed rate as the prior.
- Confirm the 1.0-point mechanism tolerance in rule 1.
