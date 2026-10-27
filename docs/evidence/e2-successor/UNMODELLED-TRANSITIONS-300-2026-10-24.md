# E2 successor: unmodelled transitions, type inventory (300 seeds, 2026-10-24)

Every unmodelled transition type that the 300 seeds produce or can produce, with its count across the seeds, the printed 2026 rulebook heading it falls under, and its treatment: an implemented transition with tests, a guard, a block, or a refusal. Each treatment fails loudly. A game that contains an unmodelled transition is never described as a complete game.

Engine commit `dfef3e8e40ab9702c1f021ff726e3959d6f9d63b`. Games: seeds 1-300. Cross-check: legality_check.check_unmodelled, derived from the plays; 0 mismatches.

## Inventory

| type | count | seeds | printed rule heading | treatment | how it fails | tests |
|---|---:|---:|---|---|---|---|
| `two_minute_warning` | 599 | 300 | RULE 3 DEFINITIONS, SECTION 41 TWO-MINUTE WARNING; RULE 4 GAME TIMING, SECTIONS 3 STARTING THE GAME CLOCK, 4 STOPPING THE GAME CLOCK and 5 TIMEOUTS | guarded; crossing marker is partial, full clock lifecycle unsupported | the record and independent checker classify each crossing as unmodelled; the game is not complete | `test_game_state.UnmodelledTransitions.test_a_two_minute_crossing_is_recorded_without_rewinding_the_clock`<br>`test_game_state.UnmodelledTransitions.test_a_missing_two_minute_guard_event_is_refused`<br>`test_legality.ScopeGuard.test_clock_start_stop_lifecycle_remains_explicitly_unsupported` |
| `penalty` | 0 | 0 | RULE 14 PENALTY ENFORCEMENT; the clock stop for a foul is RULE 4 GAME TIMING, SECTION 4 STOPPING THE GAME CLOCK, items (e) "at the end of a down during which a foul occurs" and (g) | blocked | the game is blocked as penalty_not_modelled and is never complete | `test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed`<br>`test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game` |
| `timeout` | 77 | 70 | RULE 4 GAME TIMING, SECTION 5 TIMEOUTS, ARTICLE 1 CHARGED TEAM TIMEOUTS and Item 1 "Timeouts Allowed" ("three charged team timeouts during each half") | guard | the game is guarded: complete_game is false, and the checker reports check_unmodelled | `test_game_state.UnmodelledKinds.test_a_timeout_flag_is_an_unmodelled_stoppage`<br>`test_game_state.TimeoutCharges.test_flags_charge_at_most_three_per_half_and_reset_at_halftime`<br>`test_game_state.TimeoutTransition.test_the_count_is_written_once_in_state_after_and_only_for_the_charged_side`<br>`test_game_state.TimeoutStop.test_the_stop_is_explicit_with_its_counts_and_its_clock` |
| `overtime_block` | 11 | 11 | RULE 16 OVERTIME PROCEDURES, SECTION 1 ARTICLE 3 "an extra period of 10 minutes shall commence" | blocked | a tied regulation game is blocked as overtime_not_modelled; validate_game refuses it described as complete | `test_game_state.ScopedOut.test_a_tied_regulation_game_is_scoped_out_as_overtime`<br>`test_game_state.ScopeRefusals.test_a_tied_game_with_its_overtime_block_removed_is_refused` |
| `missed_field_goal_return` | 239 | 176 | RULE 11 SCORING, SECTION 4 FIELD GOAL, ARTICLE 2 MISSED FIELD GOALS, exceptions (1) and (2): receivers touch beyond the line of scrimmage | implemented with a guard | the awarded spot is implemented (Rule 11-4-2 (a) and (b)); the receivers' touch exception (1) and (2) is guarded: the game is guarded and the checker reports check_unmodelled | `test_game_state.MissedFieldGoalBoundaries.test_one_yard_inside_the_receivers_20_gives_their_20`<br>`test_game_state.MissedFieldGoalBoundaries.test_one_yard_outside_the_receivers_20_gives_the_spot_of_the_kick`<br>`test_game_state.UnmodelledKinds.test_a_missed_field_goal_is_an_unmodelled_return`<br>`test_game_state.MissedFieldGoalReturn.test_the_return_exception_is_a_named_unsupported_rule_with_a_guard` |
| `onside_kick` | 0 | 0 | RULE 6 FREE KICKS (onside kick); no onside kick is drawn in this engine | refused | validate_game refuses any kickoff kind outside the engine vocabulary | `test_game_state.UnmodelledKinds.test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled` |
| `exception_coin_toss` | 0 | 0 | RULE 4 GAME TIMING, SECTION 2 STARTING A PERIOD OR HALF, ARTICLE 2 TOSS OF COIN, the forfeited-privilege exception | refused | explicit_exception_scenario raises NotImplementedError; every game is in normal mode | `test_game_state.Ledger.test_exception_mode_is_not_implemented` |

`lineups` is a labelling guard, not a transition: participants are labelled sampled_observed_play.

## Partial event representation

These event markers are detected and independently checked, but their complete rules-required state transitions are not represented.

| transition | printed rule heading | tests |
|---|---|---|
| `two_minute_warning` | RULE 3 DEFINITIONS, SECTION 41; RULE 4 GAME TIMING, SECTION 3 STARTING THE GAME CLOCK, ARTICLE 2; SECTION 4 item (h) | `test_game_state.TwoMinuteWarning.test_a_play_ending_at_2_01_does_not_stop_the_clock`<br>`test_game_state.TwoMinuteWarning.test_a_play_ending_at_2_00_warns_at_2_00`<br>`test_game_state.TwoMinuteWarning.test_a_crossing_keeps_the_actual_post_down_clock`<br>`test_game_state.TwoMinuteWarning.test_a_kickoff_warning_keeps_the_observed_post_kick_clock`<br>`test_game_state.TwoMinuteWarning.test_a_period_expiry_does_not_trigger_a_warning`<br>`test_game_state.TwoMinuteWarning.test_a_second_dead_ball_in_the_same_half_does_not_stop_again`<br>`test_game_state.TwoMinuteWarning.test_the_warning_resets_at_halftime_so_the_fourth_quarter_warns_too`<br>`test_legality.UnmodelledNegatives.test_a_crossing_without_a_warning_marker_cannot_pass_as_legal`<br>`test_legality.ScopeGuard.test_a_kickoff_crossing_is_independently_derived_and_requires_a_marker`<br>`test_legality.UnmodelledNegatives.test_a_second_stop_in_the_same_half_cannot_pass_as_legal` |

## Counts by quarter

Two-minute warning markers by quarter (clock lifecycle unsupported): Q2: 300, Q4: 299.
Seeds with at least one unmodelled transition: 300 of 300.

## Notes per type

- `two_minute_warning`: The crossing marker and actual post-down clock are checked. The running/stopped state and explicit restart transition required by the LP rules contract are not represented; each occurrence maps to the clock_start_stop guard.
- `penalty`: The E1 pool excludes penalty rows by construction, so a penalty is drawn only if a row carries one.
- `timeout`: The count is implemented: a timeout is charged to a side that has one left, and each stop is recorded explicitly (timeout_stop: the counts before and after, the clock at the stop, the restart). Its stoppage time is inside the observed runoff, so the clock effect is guarded.
- `overtime_block`: Overtime rows are excluded from the sampling pool (see overtime-rows-evaluation.json).
- `missed_field_goal_return`: The table records makes and misses, not touches, so the exception cannot be decided from the data.
- `onside_kick`: Every kickoff is drawn from the observed kickoff pool, so no onside kick can be drawn.
- `exception_coin_toss`: The forfeited-privilege exception (Rule 4, Section 2, Article 2) is not drawn.
- `two_minute_warning` (partial): Rule 3 Section 41 places the automatic timeout at the end of the last down snapped or kicked before 2:00. The marker keeps that down's actual end value and the independent checker derives crossings from scrimmage downs and kickoffs. The explicit running/stopped state and restart transition required by the LP rules contract are not represented; see the two_minute_warning event guard and clock_start_stop unsupported-rule entry.

## Negative fixtures

Each row is a test that fails if the guard, or the modelled rule, stops refusing the claim. Test names are checked to resolve on every build.

| guard family | what the fixture proves | test |
|---|---|---|
| clock (no clamp) | a negative clock is refused, so no clamp can hide one | `test_game_state.KickoffClock.test_a_negative_clock_is_refused_so_no_clamp_can_hide_one` |
| clock (no clamp) | a kickoff longer than the clock expires the quarter; the overrun is recorded, not clamped | `test_game_state.KickoffClock.test_a_kickoff_longer_than_the_clock_expires_the_quarter_and_records_the_overrun` |
| clock | a clock that rises inside a quarter is refused by the checker | `test_legality.NegativeFixtures.test_a_clock_that_rises_inside_a_quarter` |
| clock | a quarter that falls is refused by the checker | `test_legality.NegativeFixtures.test_a_quarter_that_falls` |
| clock | a complete game that does not end at zero is refused by the checker | `test_legality.NegativeFixtures.test_a_complete_game_that_does_not_end_at_zero` |
| clock | a clock that rises inside a quarter fails the rules matrix | `test_game_state.RulesMatrix.test_a_clock_that_rises_inside_a_quarter_is_a_failure` |
| two-minute warning (modelled) | a crossing without its warning marker cannot pass as legal (checker) | `test_legality.UnmodelledNegatives.test_a_crossing_without_a_warning_marker_cannot_pass_as_legal` |
| two-minute warning (modelled) | a second stop in the same half cannot pass as legal (checker) | `test_legality.UnmodelledNegatives.test_a_second_stop_in_the_same_half_cannot_pass_as_legal` |
| two-minute warning (modelled) | a play ending at 2:01 is not stopped | `test_game_state.TwoMinuteWarning.test_a_play_ending_at_2_01_does_not_stop_the_clock` |
| two-minute warning (modelled) | the seed-1 record is not a legal complete game (its guarded transitions) | `test_legality.ScopeGuard.test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_its_guarded_transitions` |
| guarded game (any guard) | a guarded game relabelled complete_regulation is refused by validate_game | `test_game_state.UnmodelledKinds.test_a_guarded_game_described_as_complete_is_refused` |
| guarded game (any guard) | a guarded game with its complete flag set is refused by validate_game | `test_game_state.UnmodelledKinds.test_a_guarded_game_with_its_complete_flag_set_is_refused` |
| penalty | a sampled penalty blocks the game and it is never complete | `test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed` |
| penalty | a penalty transition cannot pass as a legal complete game (checker) | `test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game` |
| timeout | a timeout stoppage cannot pass as a legal complete game (checker) | `test_legality.UnmodelledKindNegatives.test_a_timeout_stoppage_cannot_pass_as_a_legal_complete_game` |
| missed field goal return | a missed-field-goal return cannot pass as a legal complete game (checker) | `test_legality.UnmodelledKindNegatives.test_a_missed_field_goal_return_cannot_pass_as_a_legal_complete_game` |
| onside kick | an onside kickoff kind is refused by validate_game | `test_game_state.UnmodelledKinds.test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled` |

## Shared-v1 residuals

Nine residuals are guarded: `shared-v1-residuals.json` lists each with its guard test. Seven come from the LP check (`V-mode`, `V-unresolved-game_id`, `V-unresolved-scheduled_kickoff_utc`, `V-unresolved-as_of_utc`, `V-unresolved-snapshot_hash`, `V-unresolved-roster_snapshot_id`, `V-duration-seconds`). Two come from Gridiron only (`V-teams-unresolved`, `V-valid-full-game`). Gridiron's combined as-of and kickoff line maps onto the two LP time IDs, so it is not counted twice.


## Survey outcome

Seeds 300. Validated by validate_game: 300. Blocked: 12, with a named reason each. Regulation end under the simulation: 288, of which guarded: 288. Complete games: 0. Guarded seeds described as complete: 0. Blocked seeds described as complete: 0. Legal complete games: 0.

The claim the survey supports is consistency under the modelled rules. It is not a claim that any sampled game is a complete legal game.
