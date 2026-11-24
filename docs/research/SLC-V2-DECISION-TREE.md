# SLC V2 decision tree (Phase 1 of the V2 decision-tree and fallback audit)

Status: Phase 1 complete for the execution graph (2026-11-24). Measurements (Phases 2 and 3) follow in their own reports.
Machine-readable graph: `docs/research/slc-v2-audit/decision_graph.json`.

Branch `research/slc-v2-decision-tree-audit-2026-11-24`, based on `research/slc-v2-event-expansion-2026-11-24`
(`b83d580e`). Control: frozen Week 11 V2, pack `v2--season-2026-runtimefix1.slcpkg` (sha256 `97c4a01e...`),
code commit `8a1d9842`, reference sha256 `13909c65...`, training cutoff before 2026 week 10.

## The V2 configuration actually executed

From the frozen registry entry (`portable-models-2026-11-19/registry.json`, model `v2`):
build args `--slc-v2 --rng-protocol v2 --playcall-pass-label-mode conditional --playcall-decision --no-export-plays`
plus blocker fixes `run_scramble_backoff`, `long_field_goal_feasibility`, `blocked_kick_source_audit`,
`blocked_kick_geometry`, `safety_free_kick_boundaries`. `--slc-v2` requires `--slc-profile v1_full_stack`, sets the
season adapt, RNG protocol v2, the pinned v2 tables, and `long_field_goal_feasibility`.

Enabled layers (16): current_streak_context, decision_labels, decision_row_filter, defensive_coverage_outcomes,
dirichlet_player_target_carry_shares, exact_yardline_outcomes, formation_personnel_outcomes, league_streak_splits,
playbook_priors, player_conditioned_outcomes, point_splits, qb_decisions, score_clock_playcalling, target_role_priors,
team_offense_defense_outcomes, team_streak_splits. Not enabled: transition_strength.

`run_scramble_backoff` also sets `outcome_backoff_enabled`, `allow_sparse_cells` and `scramble_backoff_enabled` on the
sampler (`slc_engine.load_reference`, lines 234-238).

## Graph, in execution order

Layer kinds: D decision, C constraint, M statistical modifier, T transition, A accounting.

### Game level (`game_state._Game`)

| id | node | kind | code | notes |
|---|---|---|---|---|
| G1 | coin toss and half-start kickoffs | D | `CoinTossLedger` | seeded toss; the winner's choice; half-start kickoffs validated by `validate_half_start` |
| G2 | kickoff and safety free kick | T | `_kick`, `build_kickoff_pool`, safety kick pool | **one unconditional draw** of (spot, runoff) from the pool; no onside decision, no score or clock conditioning; the pool keeps only kickoffs after which the receiving team runs the next play, so onside recoveries, kick-return touchdowns and kickoff turnovers cannot occur; no guard for an empty pool (`random.choice` raises); halts `safety_free_kick_not_modelled` |
| G3 | drive | T | `_drive_body` -> `e1_drive.simulate` | play loop below; a halt in E1 blocks the game |
| G4 | penalty check | C | `_drive_body` line 1474 | the pool excludes penalties; a sampled penalty row blocks `penalty_not_modelled` |
| G5 | two-minute warning | T | `_two_minute_stop_plays`, `two_minute_stop` | clock stop at 2:00 in Q2 and Q4, also applied to kickoffs |
| G6 | participants for stats | A | `Reference.participants_for` | maps the sampled row's participants and the pre-snap choices to the simulated players for statistics |
| G7 | timeouts | A/C | `_apply_timeouts`, `_TimeoutSamplingGuard` | **not a decision**: a timeout happens only when the sampled row had one, charged to the mapped team; once a team has none, the guard removes timeout rows from the cell; halts `timeout_team_unresolved`, `timeout_limit_exceeded`, `timeout_sampling_guard_mismatch`, H2 |
| G8 | field goal result | D | `_drive_body` 1515-1548; `_resolve_special_teams` | make/miss from `kicks['field_goal']` by bucket unless the row carries the result; halts `thin_kick_cell`, `field_goal_outcomes_missing`, distance-model halts |
| G9 | missed field goal return | T | `_missed_field_goal_transition` | halt `missed_field_goal_return_pool_unavailable` |
| G10 | try after touchdown | D | `_try_after_touchdown`, `try_policy.p_two` | overtime uses the conditional overtime table (`conditional_try_fallback`) |
| G11 | safety and free kick | T | `_drive_body` 1580-1594 | `safety_free_kick_boundaries` fix |
| G12 | observed overtime drive | - | `_observed_overtime_drive` | **dead code**: defined, never called. The overtime drive pool only switches overtime on (`_regulation_over`, line 811) |
| G13 | overtime | T | `_begin_overtime`, then `_drive_body` with quarter 5 | Rule 16: seeded toss, observed kick-or-receive model, 10-minute period, overtime timeouts; drives are played play by play with the regulation pool and `OVERTIME_FOURTH_DOWN_KICK_SHARE` at 4th down; possession and sudden-death rules in `_overtime_possession`, `_sudden_death_touchdown` |
| G14 | drive limit and end | A | `run`, `record` | halts `drive_limit`, `unhandled_terminal:*` |

### Play level (`e1_drive.simulate`, lines 254-509)

| id | node | kind | inputs | existing fallback | halt |
|---|---|---|---|---|---|
| P1 | pool cell | D | `e0.pool_key(down, togo, yl)` (down, distance bucket, field bucket) | none | |
| P2 | timeout guard filter | C | cell, state | none | H2 `sampling_guard.unavailable_reason()` when it empties a non-empty cell |
| P3 | thin-cell floor (`MIN_POOL` 50) | C | cell size | skipped when `allow_sparse_cells` (true in V2) | H3 `thin pool cell ... no fallback` (not reachable in V2) |
| P4 | field-goal feasibility | C | yl | `long_field_goal_feasibility` | H8 attempt beyond ceiling |
| P5 | overtime 4th-down kick share | D | quarter 5, down 4 | none | H4 when the restricted cell is empty |
| P6 | event shares | C | cell | none | H5 no eligible action |
| P7 | sampling policy | D | see S nodes | see S nodes | H6 `SamplingUnavailable(...)` |
| P8 | guard rejection of the drawn row | C | row | none | H7 |
| P9 | special teams resolution | T | punt, field goal | see G8 | H9 blocker from the resolver |
| P10 | yardage credit at the field boundary | C | sampled yards, yl | `_credit_field_boundary_yards` | |
| P11 | reducer | T | state, event, yards, spot | none | H10 `UnmodelledOutcome`; H11 raises `FootballAssertionError` |
| P12 | clock | T | V2 runs no research clock: the runoff is the sampled row's observed runoff | none | H12 (research clock only) |
| P13 | period expiry | T | clock | | H13 blocked kick that ends Q1/Q3 |

RNG streams (protocol v2): `e1_event_selection`, `e1_source_row`, `e1_playcall`, `e1_special_teams`, keyed by
(drive index, play index); clock streams `clock_quarter_end_hazard`, `clock_runoff`.

### Sampling policy (`slc_playcall.PlayCallSampler.sample`, lines 421-860)

| id | node | kind | conditioning | support / fallback |
|---|---|---|---|---|
| S1 | kick share | D | the cell's kick share (or yard-line kernel with the kicker flag); FG feasibility | `long_field_goal_feasibility` removes infeasible FG keys |
| S2 | dropback probability | D | score-clock logistic artifact (down, togo, yl, score, quarter, clock, team) + season-team-down adjust | |
| S3 | point split, team streak, league streak | M | log-odds shifts | named `split_fallbacks` when a bucket or context is missing |
| S4 | intent draw | D | S1-S3 | kick first, then dropback vs run |
| S5 | pre-snap participants | D | `pre_event.choose`: participation-field lineup and personnel, formation prior, coverage prior, QB decision (`qb_decisions.draw`: scramble with its own support ladder exact 10 / down-field 25 / down-distance 25 / field-zone 50 / league; target role shrunk to a prior; QB run-role style, min support 20), decision labels, Dirichlet player shares | roster and lineup failures raise `ValueError` (snapshot validity); `cell_fallback_from` in the participation field; `playbook_fallback` |
| S6 | exact outcome rows | C | intent, scramble class, legal scramble bounds | |
| S7 | outcome backoff | C | exact_cell(10) -> down_field(25) -> down_distance(25) -> field_zone -> league_intent | `run_scramble_backoff`; preserves intent and scramble class |
| S8 | event weights, exact path | M | base counts x formation lift x coverage lift x streak lift x label lift (geometric mean) x team event weight x player event weight | all-zero -> baseline counts (`all_conditioned_weights_zero_within_selected_intent`) |
| S9 | event weights, backoff path | M | base counts x team event weight x player event weight; formation, coverage, streak and label lifts are **not** applied | all-zero -> counts |
| S10 | two-stage pass draw | D | `pass_label_mode` conditional, dropback, not scramble | |
| S11 | restore sack mass | M | `restore_sack_mass` fix only, exact path only | not in V2 |
| S12 | scramble / non-scramble row filter | C | qb decision | exact path: halts `qb_scramble_source_rows_missing`, `non_scramble_run_source_rows_missing` |
| S13 | sequential row filters | C | formation, coverage, streak, labels (in category order), QB target role, exact yard line (yl <= 20) | each filter is skipped with a named fallback when it would empty the candidates |
| S14 | final row draw | D | player row weights (and transition groups when enabled) | **no zero-weight protection** |

## First findings (Phase 3 material, to be measured)

1. **Final row draw has no zero-weight guard (S14).** `rng.choices(candidates, weights=row_weights)` raises Python
   `ValueError` if every row weight is 0; no fallback catches it.
2. **Exact and backoff paths condition differently (S8 vs S9).** On the backoff path, formation, coverage, streak and
   label lifts are not applied to the event weights, but the row filters (S13) still run on the backoff candidates.
3. **Transition strength replaces earlier weights on the backoff path** (lines 539-541) and multiplies them on the
   exact path (line 620). Latent in V2 (transition strength off; `load_reference` refuses it with team outcomes).
4. **Sequential row filters can change the effective conditioning order.** Each filter narrows the candidates of the
   already-drawn event in a fixed order and is skipped only when it empties them, so a later filter's evidence depends
   on whether an earlier one matched.
5. **Corrected:** overtime is played play by play (G13). `_observed_overtime_drive` is dead code and should be removed
   or documented as retired.
7. **Kickoffs cannot produce onside recoveries, return touchdowns or turnovers (G2)**, and do not condition on the
   score or clock. A trailing team late in a game never attempts an onside kick on purpose.
8. **Timeouts are not decisions (G7).** Their use is a side effect of which rows are sampled.
9. **Two support ladders for one decision.** The QB layer decides a scramble from its own support table; the outcome
   sampler then looks for scramble rows with its own index and a state-dependent legal-yardage filter. When none
   survive at any level, the play halts `no_supported_outcome_for_intent`. To be measured in Phase 3.
6. **Outcomes the pool cannot represent** (rows excluded in `e1_drive.classify`): penalties, two-point attempts,
   turnovers returned for touchdowns, punts and turnovers without a clean next snap, rows without a same-quarter next
   snap or with negative runoff. These are legal football outcomes with no V2 execution path.
