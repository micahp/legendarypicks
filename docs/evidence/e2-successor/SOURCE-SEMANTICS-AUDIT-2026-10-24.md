# E2 successor: source-semantics audit (2026-10-24)

What each field in the successor record means, which publisher field it came from, and what the record does not model.
Every count below names the instrument it was taken from. None is a property of the whole league.

## 1. Conversion results (blocker 1)

| try | publisher field | values | record field written by the engine |
|---|---|---|---|
| extra point | `extra_point_result` | `good`, `failed` | `extra_point_result`: `good` when made, `failed` when not |
| two-point | `two_point_conv_result` | `success`, `failure` | `two_point_conv_result`: `success` when made, `failure` when not |

- nflverse `success` is an EPA-positive flag, not a make result. The Gridiron guard says the same
  (`web/conversion-source-semantics.js`: "The E3 source `success` flag means EPA-positive").
- The engine writes only the publisher field (`game_state.try_record`). `validate_game` requires the field, requires its
  value to match `made`, and rejects any `success` key on an extra-point try.
- Independent checker: `legality_check.check_conversions`. On the frozen seed-1 record (`docs/fixtures/e2/e2-game-seed1.json`,
  unmodified) it reports 3 findings: all three extra-point tries lack `extra_point_result`. This is the rejection the
  Codex ingest guard reports for that record. The Codex guard's code was not read here; the finding is reproduced by LP's
  own checker only.
- Scope of the Gridiron guard: it checks the producer file hash and the source description, not each try. Per-try
  correctness is therefore established by LP's engine and checker, and not by the Gridiron guard.

Tests: `test_game_state.TryPublisherField` (4 engine tests); `test_legality.TryFieldNegatives` (3 fixtures: the frozen record,
a try whose value disagrees with `made`, an EPA `success` flag on a try).

## 2. Penalties (blocker 5)

- The E1 candidate pool excludes penalty rows by construction (`e1_drive.build_pool`, `excluded['penalty (not modelled)']`).
  The engine's penalty branch is therefore a guard, not a path the pool reaches.
- Guard: any play whose outcome carries `penalty` blocks the game as `penalty_not_modelled`
  (`game_state._drive_body`). A blocked record is never `complete_regulation`.
- Checker: `legality_check.check_unmodelled` derives penalty transitions from the plays themselves, not from the record's list.

Scope: penalties are out of scope. A complete game cannot contain a sampled penalty. A record that carries one is blocked, or
fails `legal_complete_game`.

Tests: `test_game_state.UnmodelledTransitions.test_a_sampled_penalty_blocks_the_game_and_is_not_completed` (engine);
`test_legality.UnmodelledNegatives.test_a_penalty_transition_cannot_pass_as_a_legal_complete_game` (checker).

## 3. Two-minute warning and clock lifecycle (blocker 5)

- The event marker is modelled: a scrimmage down or kickoff that crosses 2:00 in Q2 or Q4 is marked at its actual post-down/post-kick clock. The play is not rewound to 2:00. Rule 3 Section 41 places the automatic timeout at the end of the last down legally snapped or kicked before 2:00.
- The independent checker derives crossings from plays and kickoffs and verifies the marker; it also verifies no more than one warning in each half.
- The LP rules contract requires timeout, warning, clock runoff, clock-start/stop and restart as separate substates. This engine has no clock running/stopped state or explicit restart transition, so `clock_start_stop` is an unsupported rule on every record. The marker is not full clock-rule coverage and cannot support `valid_full_game=true`.
- The 300-seed evidence reports warning marker counts and affected seeds separately from event-specific guards. See `unmodelled-transitions-300.json` and its generated Markdown inventory.

## 4. Overtime (repair 5)

- `e2_reference.load(regulation_only=True)` (the successor default) draws the E1 pool and the kickoff pool from quarters 1–4.
- 1,214 overtime rows (quarter 5 or later) in the 2022–2025 `nfl_pbp` window are excluded and counted on
  `reference.pool_scope` (`overtime_rows_excluded_from_pool`, `overtime_rows_removed_before_kickoff_pool`).
- A game that is tied after regulation is blocked as `overtime_not_modelled`. It is never completed.
- The published kick table (`kick_results_2022_2025.csv`, sha256 `193f2d23…`, 9,704 rows) is **not** filtered. Its rates
  include overtime kicks. This is recorded in `pool_scope.kick_table`. It is a known limit of the kick rates, not of the
  pool.

## 5. Toss (blocker 4)

Measured by `evidence_e2/toss_sampling_check.py` on seeds 1–300 (`max_drives=1`; the toss is drawn before any play):

- Winner: A 153, B 147. Both sides sampled.
- Choice: receive 155, defer 145. Both sampled.
- Winner and choice: A-receive 83, A-defer 70, B-receive 72, B-defer 75.
- These counts are pinned in the script. The check fails if the draw order changes. Output: `toss-sampling-300.json`.

## 6. Kick measurement (kick spot and five-second runoff)

- Made field goal, runoff to the next snap: median 4 s; 98.9% ≤ 5 s over 3,682 made kicks in the published play-by-play
  2022–2025 (nflverse). The engine caps a made-kick runoff at 5 s (`KICK_DURATION_SECONDS`).
- Missed field goal, runoff to the next snap: 95.9% ≤ 5 s over 557 missed kicks.
- The kick spot is the snap yardline plus `HOLDER_OFFSET = 7`, capped at 99. The offset is authored, not measured.

## 7. Timeouts

- `play_extras_2022_2025.csv` (sha256 `3ae148f9…`, 24,554 rows; generator `build_play_extras.py`) carries `timeout`,
  `timeout_team` and `out_of_bounds`. Those columns are not in dev `nfl_pbp`, so they come from the nflverse parquet through
  the pyarrow venv.
- The engine charges timeouts on the state after the play (`_apply_timeouts`), so a timeout is a transition, not a field.

## 8. Known gaps, stated

- Two-minute crossing markers are modelled, but clock running/stopped state and explicit restart transitions are not. Penalties are not modelled. The guards above decide what a record may claim.
- Overtime is not modelled. The pool excludes it, and a tied game blocks.
- `duration_seconds` is null for all 141 plays of the successor seed-1 record; the published table has no play duration.
  LP's `shared_v1` reports this as a contract violation (7 total). The Gridiron v1 audit reports 6 and does not check duration.
- The kick table includes overtime kicks.
