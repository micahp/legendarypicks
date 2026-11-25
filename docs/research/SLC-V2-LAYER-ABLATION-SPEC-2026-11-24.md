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

## Amendment 1 (2026-11-24, before the batch)

Found while building the runner; no arm had been scored.

1. **Arms are run-time overrides of the frozen pack, not rebuilt packs.** The pack is decoded once per arm and the
   arm's layers are switched off on the loaded sampler, by setting the attributes each layer's loader sets to their
   constructor defaults (`e2_reference.load`, `slc_engine.load_reference`). The per-game player chooser is rebuilt from
   those attributes for every game (`slc_engine.play`), so this is equivalent to removing the layer at build time.
   The patched sampler (`fb15dbcd`) is swapped in at run time. Runner: `/root/v2-ablation/runtime` on the fast host
   (`ablation_hook.py`, `run_arm.py`, and one inserted line in a copy of `simulate_portable_pack.py`); the live runtime
   and registry are not changed.
2. **Matched random streams.** The runner derives the RNG stream root from the reference and the layer description,
   so removing a layer first would change every stream. The hook runs after the control's plan is fixed, so every arm
   uses the control's stream root (`908a29d6...` for PIT at PHI).
3. **A06 `qb_decisions` is not run.** In V2 the QB table is also loaded by the `run_scramble_backoff` fix
   (`playcall_qb_decisions = qb_decisions or run_scramble_backoff`), so the layer cannot be removed without removing the
   fix, which would change event coverage.
4. **A07 `decision_labels`** also sets the pass label mode to `legacy`: `load_reference` refuses the conditional mode
   without decision labels.
5. **The streak lift and the streak row filter belong to `league_streak_splits`** (`streak_outcomes` is set when the
   league streak table loads), so A04 also removes them. A05 `current_streak_context` removes the streak bucket and
   both streak splits.
6. **Seeds 300001 to 300100,** the frozen V2 week 11 preflight rerun's seeds, so A00 can be checked against the saved
   frozen outputs on every game and seed.
7. **Arms run: 21.** A00, A01-A05, A07-A16, A17, A18, A19, A22, A23. A23 decodes the pack again for every game,
   because it removes the sampler for good.
8. **Reproduction gate, as run:** A00 must match the frozen outputs exactly in scores and player box scores. Before the
   batch: PIT at PHI 10/10 and TEN at DAL 10/10 seeds identical; a three-game check in one process (testing that a
   reused pack carries no state between games) is required before the batch starts. After the batch, all 1,300 A00
   seeds are compared with the frozen outputs.

## Amendment 2 (2026-11-24, before the batch): mechanisms, not flags

On Micah's instruction, arms are defined by mechanisms, not by the existing layer flags, and no arm is dropped because
the implementation couples mechanisms. Amendment 1's arm list (and its "A06 is not run") is replaced by this one.

### What changed in the code (research switches; empty set = full V2)

`PlayCallSampler.research_off` is a set of mechanism names (`slc_playcall.RESEARCH_MECHANISMS`). The sampler, the
participant chooser (`pre_event.choose`, through `chooser` and `slc_engine.play`) and the QB decision
(`qb_decisions.draw`) read it. Every decision records `research_off` and `mechanisms_applied` (which mechanisms actually
ran on that decision), plus chooser evidence: whether a formation, coverage, labels and a QB target role were drawn, the
source of the scramble probability, the participant share model, and the target-role prior and playbook use.

| mechanism | what switching it off does |
|---|---|
| `score_clock_playcalling` | run/dropback probability from the historical cell rate |
| `point_split_shift`, `team_streak_shift`, `league_streak_shift` | that log-odds shift is not applied |
| `qb_scramble_probability` | the scramble probability is the cell's historical scramble share of dropbacks at its support level (`qb_decisions.scramble_backoff_rate`), not the QB's or team's. Scrambles still happen, as scrambles, with the same legal-bounds, support ladder and QB attribution |
| `qb_target_role_selection` | no target role is drawn by the QB model; the receiver's role comes from the label path (label A from the decision and target-role priors) or the team target-role model |
| `qb_target_role_row_filter` | source rows are not filtered by the target role |
| `label_generation` | no decision labels are drawn (A to N), so no label lift, label filter, conditional pass model or playbook; the QB target role still steers the receiver |
| `label_outcome_lift` | the non-pass label lifts on event weights are not applied |
| `label_conditional_pass_model` | the conditional two-stage pass draw is not used; the event is drawn from the remaining weights. The legacy label mode is **not** restored |
| `label_row_filter` | rows are not filtered by labels |
| `label_participant_allocation` | labels A and B (and so the QB role) do not restrict the receiver's or carrier's position |
| `playbook_label_priors` | the playbook does not override labels D, E and C |
| `target_role_priors` | no target-role prior table (label A comes from the decision table alone) |
| `formation_choice`, `formation_outcome_lift`, `formation_row_filter` | the formation is not drawn / not used as a lift / not used as a filter |
| `coverage_choice`, `coverage_outcome_lift`, `coverage_row_filter` | the same for coverage |
| `streak_outcome_lift`, `streak_row_filter` | the streak lift / filter; independent of the play-calling shifts and of the streak table being loaded |
| `team_event_weights` | no team event weights (exact and backoff paths) |
| `player_event_weights`, `player_row_weights` | no player event weights / no player row weights |
| `dirichlet_player_shares` | **alternative path:** participants by position usage (`pre_event._by_usage`, the receiver's role still applied where the code applies it); statistically, every eligible player at a position is drawn at the position's historical share instead of from the game's Dirichlet draw |
| `exact_yardline_row_filter` | rows are not filtered to the exact yard line inside the 20 |

Layers without a switch use attribute overrides at run time: streak context (`current_streak = {}`), the
participation lineup (`participation_field = None`; personnel then comes from the formation layer), the kicker
field-goal table (`fg_kicker = None`; the kick share is the cell's and the ordinary feasibility rule applies).

### Coupling audit of the other layers

- **Season adaptation** blends the team, player and share tables with the current season at build time. It cannot be
  undone at run time. **Not dropped:** it needs a rebuilt pack with `--playcall-season-adapt` off; recorded as a
  pending arm (Y1) to run once that pack is built.
- **Snap-count update** is applied to the participation field, so S1 removes both. A separate arm needs the field
  without the update, which also needs a rebuild; recorded as pending (Y2).
- The kick decision with the kicker table (S2) and the participation lineup (S1) are independent of the 16 listed
  layers.

### Arms (39 run, 2 pending a rebuild)

A00 control. Play-calling: P1 score clock, P2 point split, P3 team streak shift, P4 league streak shift. QB: Q1 scramble
probability, Q2 target-role selection, Q3 target-role row filter, Q4 the whole QB decision model (Q1-Q3). Labels: L1
generation (full removal), L2 outcome lift, L3 conditional pass model, L4 row filter, L5 participant allocation, L6 all
label outcome modifiers (L2+L3), L7 playbook priors. Streak: K1 outcome lift, K2 row filter, K3 no streak context.
Formation: F1 choice, F2 lift, F3 filter. Coverage: C1 choice, C2 lift, C3 filter. T1 team event weights. Player: U1
event weights, U2 row weights, U3 both (player outcome strength off, allocation kept). D1 Dirichlet shares
(position-usage path). R1 target-role priors. X1 exact-yard-line filter. Groups: G1 all multipliers off, G2 all optional
filters off, G3 both, G4 league-wide outcomes (G3 plus the team and player tables removed, as a consistency check of
G3). S1 participation lineup, S2 kicker field goals. Z1 minimal situational sampling (no SLC sampler). Pending: Y1
season adaptation, Y2 snap-count update.

Seeds: 50 matched seeds per game per arm (300001-300050), not 100: 39 arms x 13 games x 100 seeds would take about
26 hours on the fast host. Thirteen games limit the game-level comparisons more than the seed count does.

### Verification required before the batch

1. **Replay parity:** with `research_off` empty, the refactored engine must reproduce the frozen V2 exactly (scores and
   player box scores) on 3 games x 10 seeds, and the sampler must match the previous code on 500 of 500 synthetic draws.
2. **Every arm, through the instrumentation** (1 game x 2 seeds each): its intended mechanisms show zero applications,
   and the unrelated mechanisms run as often as in the control.
