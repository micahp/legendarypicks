# Pre-registration: ablation A, restore sack mass

Status: DRAFT. Not frozen. Freeze the code commit and this file together before any ablation run, and record the freeze commit in the results file. Any change to a threshold after the baseline run is a deviation and must be reported as one.

## Question

Does the engine's sack rate explain part of the team-scoring shortfall in the 0–10 band? The engine produces too few sacks, and a sack is a drive-killer. Restoring sack mass should move the 0–3 and 0–10 point shares toward the observed values, with the mean points held near baseline.

## Hypothesis (H_A)

Restoring the sack rate on dropbacks to the observed rate raises the share of team-games scoring at most 3 points, and at most 10 points, without moving the mean team score by more than 0.3 points.

## Measurements (all definitions fixed here)

- **Sack rate on dropbacks.** Sacks divided by pass-type plays in `nfl_pbp`, seasons 2022–2025, regular season (week 1–18), quarters 1–4, `play_type = 'pass'`. Observed: **5267 / 76552 = 6.88%**. Engine: `sacks_taken / (pass_attempts + sacks_taken)` from the team box score.
- **Turnovers per team-game.** Interceptions plus fumbles lost, for the team that lost the ball. Observed: **2578 / 2174 = 1.19**. Engine: the `turnovers` stat per team-game. This definition differs from the 1.10 cited in the review; the spec uses the definition above.
- **Team points share.** Share of team-games scoring at most 3 points, and at most 10 points. Reported per matchup and pooled over the slate.
- **Mean team points.** Pooled over all completed team-games.
- **Diagnostics (reported, not gated).** Share of team-games with 200 or more passing and rushing yards. Yards per point. Field goals and touchdowns per team-game.

## Baseline and seeds

- Snapshots: the 13 verified Sunday snapshots in `docs/research/slc-sunday-smoke-2026-11-08/snapshots/`, pinned by sha256.
- Seeds: 1–200 for each matchup. 2,600 games, 5,200 team-games.
- Baseline: the current engine on the same snapshots and seeds, run from the same frozen code commit as the ablation. Do not reuse an earlier pass unless its commit, configuration and snapshot hashes match exactly.
- The executed code today is `9667cbc1` plus an uncommitted patch. That patch must be committed or reverted before the freeze.

## The change under test (A)

Restore the sack probability on a dropback to the observed rate of 6.88%, conditioned on the same down, distance and field-zone cells the sampler already uses. Leave every other event probability unchanged. Implement it as a single explicit switch in the event sampler, default off, so the baseline and ablation differ only in that switch. The exact code location is to be recorded in the freeze commit.

## Decision rules

Each rule is stated before the run.

1. **Mechanism check.** Sack rate on dropbacks moves to 6.0–7.5%.
2. **Points, at most 3.** Share of team-games at most 3 points rises by at least 0.3 percentage points, and lands in 2.5–3.0% by the end of the ablation.
3. **Points, at most 10.** Share of team-games at most 10 points rises by at least 1.0 percentage points. This closes at least a quarter of the 3.98-point gap in the review.
4. **Mean points.** Absolute change in mean team points is at most 0.3 against the baseline.
5. **Uncertainty.** Each change in rules 2 and 3 is reported with a 95% interval from a team-game bootstrap. A change counts as moved only if its interval excludes zero.

## Outcomes

- **Pass.** Rules 1–5 hold. Run ablation B next, under its own pre-registration.
- **Partial.** Rule 1 holds, but rules 2 or 3 do not. Report that sacks are not the dominant mechanism. Do not run B on this basis.
- **Falsified.** Rule 1 holds, and the 0–3 share and the 0–10 share both move by less than the thresholds in rules 2 and 3. The sack mechanism is rejected. Do not run B or C until the mechanism is revisited.
- **Invalid.** Rule 1 fails. The change did not reach the target, so the test says nothing about the mechanism. Fix the implementation under a new pre-registration.

## Power

With 5,200 team-games the standard error on a share near 3% is about 0.24 percentage points. A 0.3-point change is near the detection limit, so the interval in rule 5 matters. If the interval is wider than the change, report the result as inconclusive, not as a pass or a falsification.

## Not in scope

Yardage (ablation C), giveaways (ablation B) and the pass-through re-landing (ablation D) are separate pre-registrations, run only after A is decided. Calibration to observed outcomes is not allowed inside A.

## Open items to confirm before freeze

- The thresholds in rules 2 and 3 come from the review. Confirm them, or replace them, before the baseline run.
- The turnover definition above differs from the review's 1.10. Confirm which definition the review intends.
