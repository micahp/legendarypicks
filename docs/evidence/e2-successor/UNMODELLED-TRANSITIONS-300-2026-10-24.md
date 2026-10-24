# E2 successor: unmodelled transitions, type inventory (300 seeds, 2026-10-24)

Every unmodelled transition type that the 300 seeds produce or can produce, with its count across the seeds, the printed 2026 rulebook heading it falls under, and its treatment: an implemented transition with tests, a guard, a block, or a refusal. Each treatment fails loudly. A game that contains an unmodelled transition is never described as a complete game.

Engine commit `75962ffe5fca9eddee9b49ff377031c5075e2c16`. Games: seeds 1-300. Cross-check: legality_check.check_unmodelled, derived from the plays; 0 mismatches.

## Inventory

| type | count | seeds | printed rule heading | treatment | how it fails | tests |
|---|---:|---:|---|---|---|---|
| `two_minute_warning` | 598 | 300 | RULE 3 DEFINITIONS, SECTION 41 TWO-MINUTE WARNING ("an automatic timeout that occurs at the conclusion of the last down ... prior to two minutes remaining ... in the second and fourth periods"); RULE 4 GAME TIMING, SECTION 4 STOPPING THE GAME CLOCK, item (h) "when the Referee signals the two-minute warning for a half" | guard | the game is status regulation_end_guarded, complete_game is false, and validate_game refuses a complete claim; the checker reports check_unmodelled | `test_game_state.UnmodelledKinds.test_a_guarded_game_described_as_complete_is_refused`<br>`test_game_state.UnmodelledTransitions.test_a_two_minute_crossing_is_listed_in_the_record`<br>`test_legality.UnmodelledNegatives.test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list` |
| `penalty` | 0 | 0 | RULE 14 PENALTY ENFORCEMENT; the clock stop for a foul is RULE 4 GAME TIMING, SECTION 4 STOPPING THE GAME CLOCK, items (e) "at the end of a down during which a foul occurs" and (g) | blocked | the game is blocked as penalty_not_modelled and is never complete | `test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed`<br>`test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game` |
| `timeout` | 77 | 70 | RULE 4 GAME TIMING, SECTION 5 TIMEOUTS, ARTICLE 1 CHARGED TEAM TIMEOUTS and Item 1 "Timeouts Allowed" ("three charged team timeouts during each half") | guard | the game is guarded: complete_game is false, and the checker reports check_unmodelled | `test_game_state.UnmodelledKinds.test_a_timeout_flag_is_an_unmodelled_stoppage`<br>`test_game_state.TimeoutCharges.test_flags_charge_at_most_three_per_half_and_reset_at_halftime`<br>`test_game_state.TimeoutTransition.test_the_count_is_written_once_in_state_after_and_only_for_the_charged_side` |
| `overtime_block` | 11 | 11 | RULE 16 OVERTIME PROCEDURES, SECTION 1 ARTICLE 3 "an extra period of 10 minutes shall commence" | blocked | a tied regulation game is blocked as overtime_not_modelled; validate_game refuses it described as complete | `test_game_state.ScopedOut.test_a_tied_regulation_game_is_scoped_out_as_overtime`<br>`test_game_state.ScopeRefusals.test_a_tied_game_with_its_overtime_block_removed_is_refused` |
| `missed_field_goal_return` | 239 | 176 | RULE 11 SCORING, SECTION 4 FIELD GOAL, ARTICLE 2 MISSED FIELD GOALS, exceptions (1) and (2): receivers touch beyond the line of scrimmage | implemented with a guard | the awarded spot is implemented (Rule 11-4-2 (a) and (b)); the receivers' touch exception (1) and (2) is guarded: the game is guarded and the checker reports check_unmodelled | `test_game_state.MissedFieldGoalBoundaries.test_one_yard_inside_the_receivers_20_gives_their_20`<br>`test_game_state.MissedFieldGoalBoundaries.test_one_yard_outside_the_receivers_20_gives_the_spot_of_the_kick`<br>`test_game_state.UnmodelledKinds.test_a_missed_field_goal_is_an_unmodelled_return`<br>`test_game_state.MissedFieldGoalReturn.test_the_return_exception_is_a_named_unsupported_rule_with_a_guard` |
| `onside_kick` | 0 | 0 | RULE 6 FREE KICKS (onside kick); no onside kick is drawn in this engine | refused | validate_game refuses any kickoff kind outside the engine vocabulary | `test_game_state.UnmodelledKinds.test_an_onside_kickoff_kind_is_refused_because_it_is_not_modelled` |
| `exception_coin_toss` | 0 | 0 | RULE 4 GAME TIMING, SECTION 2 STARTING A PERIOD OR HALF, ARTICLE 2 TOSS OF COIN, the forfeited-privilege exception | refused | explicit_exception_scenario raises NotImplementedError; every game is in normal mode | `test_game_state.Ledger.test_exception_mode_is_not_implemented` |

`lineups` is a labelling guard, not a transition: participants are labelled sampled_observed_play.

## Counts by quarter

Two-minute crossings by quarter: Q2: 299, Q4: 299.
Seeds with at least one unmodelled transition: 300 of 300.

## Notes per type

- `two_minute_warning`: The clock is not stopped at 2:00; the sampled runoff is used as recorded.
- `penalty`: The E1 pool excludes penalty rows by construction, so a penalty is drawn only if a row carries one.
- `timeout`: The count is implemented: a timeout is charged to a side that has one left. Its stoppage time is inside the observed runoff, so the clock effect is guarded.
- `overtime_block`: Overtime rows are excluded from the sampling pool (see overtime-rows-evaluation.json).
- `missed_field_goal_return`: The table records makes and misses, not touches, so the exception cannot be decided from the data.
- `onside_kick`: Every kickoff is drawn from the observed kickoff pool, so no onside kick can be drawn.
- `exception_coin_toss`: The forfeited-privilege exception (Rule 4, Section 2, Article 2) is not drawn.

## Negative fixtures for the guards

Each row is a test that fails if the guard stops refusing the claim. Test names are checked to resolve on every build.

| guard family | what the fixture proves | test |
|---|---|---|
| clock (no clamp) | a negative clock is refused, so no clamp can hide one | `test_game_state.KickoffClock.test_a_negative_clock_is_refused_so_no_clamp_can_hide_one` |
| clock (no clamp) | a kickoff longer than the clock expires the quarter; the overrun is recorded, not clamped | `test_game_state.KickoffClock.test_a_kickoff_longer_than_the_clock_expires_the_quarter_and_records_the_overrun` |
| clock | a clock that rises inside a quarter is refused by the checker | `test_legality.NegativeFixtures.test_a_clock_that_rises_inside_a_quarter` |
| clock | a quarter that falls is refused by the checker | `test_legality.NegativeFixtures.test_a_quarter_that_falls` |
| clock | a complete game that does not end at zero is refused by the checker | `test_legality.NegativeFixtures.test_a_complete_game_that_does_not_end_at_zero` |
| clock | a clock that rises inside a quarter fails the rules matrix | `test_game_state.RulesMatrix.test_a_clock_that_rises_inside_a_quarter_is_a_failure` |
| two-minute warning | a crossing removed from the record is still derived from the plays and refuses the complete claim | `test_legality.UnmodelledNegatives.test_the_two_minute_crossing_is_derived_from_the_plays_not_the_records_own_list` |
| two-minute warning | the seed-1 record is not a legal complete game because of its two-minute crossing | `test_legality.ScopeGuard.test_the_successor_seed_one_is_not_a_legal_complete_game_because_of_the_two_minute_crossing` |
| two-minute warning | a guarded game relabelled complete_regulation is refused by validate_game | `test_game_state.UnmodelledKinds.test_a_guarded_game_described_as_complete_is_refused` |
| two-minute warning | a guarded game with its complete flag set is refused by validate_game | `test_game_state.UnmodelledKinds.test_a_guarded_game_with_its_complete_flag_set_is_refused` |
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
