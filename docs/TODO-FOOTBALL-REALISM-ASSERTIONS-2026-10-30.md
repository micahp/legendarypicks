# Football realism assertions TODO

Scope: first P0 assertion pass for the SLC simulator. This is an assertion-only change; predictive parameters and locked outputs stay unchanged.

## Implemented in this branch

- [x] Check that an explicit QB scramble resolves to a QB rush and does not become a pass.
- [x] Keep sacks outside pass attempts and reconcile scramble, sack, completion, interception, target, and team totals.
- [x] Reconcile every valid full SLC seed before it contributes to batch aggregates, even when box-score export is disabled.
- [x] Add mutation fixtures for impossible player/team accounting and invalid per-seed reconciliation.

## Remaining hard football invariants

- [ ] Pass semantics: spike, incomplete pass, sack, scramble, designed QB run, interception attribution, fumble recovery, touchdown scorer, and safety conditions.
- [ ] Field and down transitions: legal bounds, first down, fourth-down failure, touchdown yard cap, both directions, forward progress, out-of-bounds spot, and terminal dead-ball behavior.
- [ ] Special teams: field-goal feasibility and distance-aware sampling, punt geometry, blocked-kick recovery, safety free-kick procedure, and explicit unresolved outcomes.
- [ ] Game state: quarter transitions, halftime possession, timeout supply, stoppages, two-minute warning, regulation ending, and the supported overtime procedure.
- [ ] Pregame eligibility and one-outcome-one-credit rules for all player-level statistics.
- [ ] Make every fixture report `ILLEGAL_STATE`, `NONCAUSAL_INFORMATION`, `STAT_ACCOUNTING`, or `UNSUPPORTED_RULE` with seed, game, play index, before/decision/outcome/after state, and artifact hashes.

## Statistical warnings, not per-play failures

- [ ] Add pinned, cutoff-eligible distribution reports for play volume, scoring, situational play calls, QB outcomes, player opportunity, and fourth-down choices.
- [ ] Check joint consistency and variation across the 10K batch without requiring a seed to match historical averages.
- [ ] Add paired-seed ablations that preserve the pregame snapshot and unrelated random draws.

## Current verification

- [x] Focused SLC invariant and box-score suite: 14 tests passed.
- [x] Full-game SLC integration: 7 tests passed on the frozen Week 8 test fixture.
- [ ] Football Realism Assertion Suite v1 sections A through G are complete.

Never drop a failed seed, silently repair its result, or count it as a valid complete game.
