# PBP-only conditional clock model, 2022 weeks 1–5

Date: 2026-10-24

Branch: `research/nfl-e3-pbp-clock-model-2026-10-24`, created at LP commit `4e18cb9f9e5b29ae9e105cbed37f90dc915c83da`.

## Scope and source

The builder reads `nfl_pbp` through SQLite read-only mode with the fixed predicate `season=2022 AND week IN (1,2,3,4,5) AND play_type IS NOT NULL`. It emits one record for each selected LP play row. It does not open tracking files, the LP tracking-coverage report, nflverse flags, or any weeks 6–9 rows. The week guard rejects weeks 6–9 before a database connection is opened.

The 13,592 selected PBP rows are distributed as:

| Week | PBP play rows |
| ---: | ---: |
| 1 | 2,765 |
| 2 | 2,666 |
| 3 | 2,726 |
| 4 | 2,714 |
| 5 | 2,721 |

The selected source columns are `game_id`, `play_id`, `season`, `week`, `qtr`, `down`, `ydstogo`, `game_seconds_remaining`, `play_type`, `complete_pass`, `touchdown`, `interception`, `fumble_lost`, `sack`, `penalty`, `two_point_attempt`, and `series_result`. The `nfl_pbp` schema has no `out_of_bounds`, `timeout`, or terminal-timestamp columns. The canonical selected-row input digest is `24896e1852edfd58f8ed8bfece0acc79ccfd4c2128f6a6c3628861b20fbac7d0`.

## Model and labels

For each play, the target is the current PBP `game_seconds_remaining` minus the next PBP play row's clock stamp in the same game and quarter. This is the PBP game-clock delta between play rows; it is not a tracking-observed snap-to-snap time. A hierarchical empirical model predicts p10, median, and p90 delta plus the probability of a positive or zero delta. The model backs off from play type × outcome × late-half × down band, to progressively broader groups, then the training-fold global distribution. Its minimum support thresholds are fixed in the builder and were not tuned on evaluation weeks.

Each play's prediction is cross-fitted by holding out its entire week. The week-5 forward holdout trains only on weeks 1–4. Weeks 1–4 cross-fit rows may use later weeks in their training fold, so their aggregate is a descriptive cross-week check, not a forward forecast. PBP outcome fields are among the inputs: this is a retrospective terminal-behavior model, not a pre-snap prediction.

Every measurement follows the E3 consumer label set `observed`, `inferred`, or `unresolvable`. Source clock stamps and explicit PBP event fields are observed. A same-quarter clock delta, runoff behavior, model quantiles, and probability estimates are inferred. An unresolvable value is null and retains its rule; no field is defaulted or filled from tracking.

- `game_clock_delta_s` / `clock_runoff_s`: inferred from the two PBP clock stamps; 13,246 resolved, 346 unresolvable.
- Source context fields (`quarter`, `down`, `distance`, `play_type`) retain their PBP value and `observed` label, or null with `unresolvable` when the source field is null. Model-derived context bands are individually labelled `inferred` or `unresolvable`.
- Unresolvable clock-delta reasons: 249 quarter boundaries (`R4u2`), 80 rows with no next PBP play row (`R4u1`), and 17 negative clock differences (`R4u3`).
- `in_play_duration_s` and `between_play_dead_time_s`: unresolvable for all 13,592 rows. PBP has no terminal timestamp, so the model cannot split total clock delta into live-play duration and dead time.
- `stoppage_context`: inferred for 2,246 rows with PBP-supported incomplete-pass, spike, or scoring context; unresolvable for 11,346. Penalties are retained as observed source evidence, but the flag does not identify enforcement or clock effect. Out-of-bounds and timeout attribution are unresolvable because those columns are absent from `nfl_pbp`.
- Terminal-event family is unresolvable for 14 rows whose PBP outcome flags are all null.

## Evaluation

The conditional estimate is compared with a fixed global-median baseline trained on the same fold. No week-5 outcomes are used to select features, support thresholds, or backoff rules.

| Evaluation | Resolved targets | Conditional median MAE | Global-median MAE | Conditional p10–p90 coverage |
| --- | ---: | ---: | ---: | ---: |
| Cross-fitted weeks 1–5 | 13,246 | 6.0488 s | 16.1095 s | 85.40% |
| Forward week-5 holdout | 2,655 | 6.1885 s | 15.9921 s | 85.35% |

For the week-5 holdout, the conditional model's MAE change versus the global baseline is −9.8036 seconds; Brier score for predicting a positive PBP clock delta is 0.072018. The baseline gap is descriptive evidence for this cohort; it does not establish generalization beyond these weeks or separate physical duration from stoppage.

## Reproduction and artifacts

Run from this worktree:

```sh
python3 -m unittest test.test_e3_pbp_conditional_clock_model -v
python3 scripts/bdb/e3_pbp_conditional_clock_model.py \
  --db /root/legendarypicks/backend/data/picks.dev.db \
  --output docs/evidence/e3/pbp-conditional-clock-model-weeks1-5-2026-10-24.json
```

Five tests pass, including rejection of weeks 6–9 before database access, exact week filtering, null labeling, cross-fitting, and week-5's weeks-1–4 training boundary.

- Builder SHA-256: `90291eea8807bbc98a210896ebd1075b128b5306e51c18e91c44746a14c27b19`
- Input-row slice SHA-256: `24896e1852edfd58f8ed8bfece0acc79ccfd4c2128f6a6c3628861b20fbac7d0`
- Per-play JSON SHA-256: `0863a38c022d01a27547f7bcc1ad624bd4f37a90a1d7a16ef684a5c67f2dcf8d`
