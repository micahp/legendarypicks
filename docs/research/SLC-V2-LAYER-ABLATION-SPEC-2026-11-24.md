# SLC V2 subtractive layer ablation: specification

Date: 2026-11-24. Written and committed before any arm runs. Branch `research/slc-v2-decision-tree-audit-2026-11-24`.
Follows Phase 1 of the V2 decision-tree audit (`SLC-V2-DECISION-TREE.md`, commit `9023a339`). Phase 2 (exhaustive
support enumeration) is deferred on Micah's instruction: support, fallback frequency and failures are captured during
these runs instead, and the unified fallback design is done later for the layers that survive.

## 1. Question

Which of V2's layers add value? Measured by game-level and player-prop forecasts, statistical realism, between-team
variance and simulation validity, against the frozen V2 control, on matched seeds.

Not in scope: new statistical models, recalibrated parameters, changed event coverage. Every arm uses the same
models, parameters, pools and rules as the control, minus the removed layers.

## 2. The frozen baseline

- Pack `v2--season-2026-runtimefix1.slcpkg`, sha256 `97c4a01e9a60c3f6e31c1701d4c954fddd5d6e9938c193bd1aba9218c7d7f5c3`,
  code commit `8a1d9842`, reference sha256 `13909c65...`, training cutoff before 2026 week 10, rules policy
  `nfl-2026-e2-successor-v2`.
- Build arguments: `--slc-v2 --rng-protocol v2 --playcall-pass-label-mode conditional --playcall-decision
  --no-export-plays` and blocker fixes `run_scramble_backoff`, `long_field_goal_feasibility`,
  `blocked_kick_source_audit`, `blocked_kick_geometry`, `safety_free_kick_boundaries`.
- The 16 enabled layers, by kind:

| layer | kind | what it does at run time |
|---|---|---|
| `score_clock_playcalling` | decision model | run/dropback probability from the score-clock logistic artifact (S2) |
| `point_splits` | decision modifier | team score-state shift on that probability (S3) |
| `team_streak_splits` | decision modifier | team win-loss streak shift (S3) |
| `league_streak_splits` | decision modifier | league streak shift (S3) |
| `current_streak_context` | context | supplies the streak bucket for the streak splits, the streak lift and the streak row filter |
| `qb_decisions` | decision model | scramble and target-role choice before the outcome (S5); also scramble-class and target-role row filters |
| `decision_labels` | decision model + multiplier | draws pre-snap labels (S5); label lifts on event weights (S8); the conditional two-stage pass draw (S10) |
| `decision_row_filter` | row filter | keeps source rows matching the drawn labels (S13) |
| `playbook_priors` | decision prior | team playbook prior on the labels; needs `decision_labels` |
| `formation_personnel_outcomes` | multiplier + row filter | formation lift (S8) and formation row filter (S13) |
| `defensive_coverage_outcomes` | multiplier + row filter | coverage lift (S8) and coverage row filter (S13) |
| `exact_yardline_outcomes` | row filter | rows at the exact yard line inside the 20 (S13) |
| `team_offense_defense_outcomes` | multiplier | team event weights within the intent (S8, S9) |
| `player_conditioned_outcomes` | multiplier | player event weights (S8, S9) and player row weights (S14) |
| `dirichlet_player_target_carry_shares` | player allocation | who gets targets and carries |
| `target_role_priors` | player allocation prior | target-role prior for the QB decision |

## 3. Code changes before any run (applied to every arm, the control included)

1. **Zero-weight draw guard.** In `slc_playcall.PlayCallSampler.sample`, the final transition and row draws (S14)
   get the same rule the event draw already has: if every weight is 0, draw uniformly from the same candidates and
   record `row_weight_fallback = 'all_row_weights_zero'` in the decision record. It changes nothing on a draw that does
   not have all-zero weights, so the control reproduces the frozen pack exactly on every other draw.
2. **Instrumentation only, no RNG change:** each decision record gains the sampling path (`exact_cell` or
   `sparse_backoff` with its level), the candidate count before and after each row filter, the backoff effective sample
   size, and every named fallback. The existing `outcome_probability_trace` is switched on for the recorded subset
   (section 6).
3. **Two research switches, needed because four layers are both a multiplier and a filter:**
   `research_disable_event_multipliers` (skips the formation, coverage, streak and label lifts, the team event weights,
   and the player event and row weights) and `research_disable_row_filters` (skips the formation, coverage, streak,
   label, target-role and exact-yard-line row filters). Neither touches the scramble-class filter, because that one
   defines the selected intent. Both default off.

**Reproduction gate.** The rebuilt control pack (the patched code, frozen build arguments) must reproduce the frozen
pack's game outputs exactly on 2 games x 10 seeds, apart from draws recorded as `all_row_weights_zero`. If it does
not, nothing else runs.

## 4. Arms

Each arm is a pack compiled with `compile_portable_pack.py` from the audit branch, the frozen build arguments, and
the arm's `--slc-disable-layer` flags or research switch. The live model registry is not changed.

| arm | spec item | removed | notes |
|---|---|---|---|
| A00 | 1 | nothing | the control |
| A01-A16 | 2 | one layer each, in the table order above | where `slc_config` requires it, the dependent layers go with it, and the arm is labelled combined: `decision_labels` takes `decision_row_filter` and `playbook_priors`; `current_streak_context` takes the two streak splits; `qb_decisions` takes nothing else (QB run-role style is off already) |
| A17 | 3 | all optional probability multipliers; filters kept | `research_disable_event_multipliers` |
| A18 | 4 | all optional row filters; multipliers kept | `research_disable_row_filters` |
| A19 | 5 | both | both switches |
| A20 | 6 | all team outcome-strength adjustments | in V2 this is exactly `team_offense_defense_outcomes` (transition strength is off; the point and streak splits are play-calling, not outcome strength), so A20 is A13 and is not run twice |
| A21 | 7 | player outcome strength, allocation kept | exactly `player_conditioned_outcomes`, so A21 is A14 |
| A22 | 8 | league-wide outcomes; team play-calling and player allocation kept | outcomes conditioned only on the situation cell and the selected intent: A19 plus `team_offense_defense_outcomes` and `player_conditioned_outcomes` removed as layers. A19 already removes their effect, so A22 checks that the switch and the layer removal agree |
| A23 | 9 | minimal situational historical sampling | profile `s0`: situation-cell sampling with no SLC layer. No player allocation, so props are not graded for A23 |

## 5. Slate, seeds and size

- The 13 week 11 2026 games, from the same roster-preflight snapshots as `rerun-100-seed-preflight-2026-11-23`
  (current rosters; the preflight checks box scores present, roster date current, QB1 = the market QB).
- 100 matched seeds per game per arm (seeds 1 to 100), RNG protocol v2, so every arm sees the same random streams.
- 22 arms to run (A20 and A21 are not run twice) x 13 games x 100 seeds = 28,600 games. About 4 s per game on one
  core, so about 32 core-hours: about 6.5 hours on 5 cores of the fast host.
- **One-seed smoke test first:** A00 and one combined arm on 1 game x 1 seed, then the reproduction gate, before
  the batch.

## 6. What is recorded

- Every game: the game output with the player box scores (props are graded from them).
- 20 of the 100 seeds per game per arm: the full decision records with the instrumentation of section 3.
- Per arm: completions, halts by reason, `all_row_weights_zero` and `all_conditioned_weights_zero` counts,
  exact-cell versus backoff share, and the backoff level mix.

## 7. Evaluation

Against week 11 actual results, the market lines and the frozen grading (`week11-rerun-preflight-2026-11-23/grading.json`
on the roster-preflight branch, same grader):

1. **Game level:** home-win, cover and over Brier scores and log loss; points CRPS.
2. **Player props:** Brier score and log loss over every graded prop, and by stat type.
3. **Statistical realism:** team points, yards, plays, sacks, turnovers, penalties and punts per team-game against
   the 2025 regular season, and the week 11 actuals.
4. **Between-team variance:** the SD of team points and yards across the 26 team-games, simulated (noise removed) and
   actual.
5. **Simulation validity:** completion rate, halts, check failures, the zero-weight fallbacks.

Every arm is compared with A00 on the same games and seeds, with a game-bootstrap interval. Thirteen games is a small
sample: a result with an interval that includes zero is reported as "no detected effect", not as "no effect".

## 8. After the ablation

The surviving layers are the ones whose removal makes the forecasts or the realism worse. The historical-support audit
and the unified fallback design are then done for those layers only.
