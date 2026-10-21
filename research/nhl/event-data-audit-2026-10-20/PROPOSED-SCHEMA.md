# Proposed NHL event-data research schema

This is a research-layer design only. It does not create production tables or
replace the frozen official outcome artifacts. Store source observations as
published; represent missingness and contradictions explicitly. Join games and
players by canonical `game_id` and numeric NHL `player_id`, never by display name.

## `event_game_source`

One row per canonical game and source response.

| Field | Type | Meaning |
|---|---|---|
| `game_id` | text | Canonical NHL game ID; primary identity |
| `source_name` | enum | `nhl_gamecenter_pbp` or `nhl_shiftcharts` |
| `source_url` | text | Exact request URL |
| `retrieved_at_utc` | timestamp | Response retrieval time |
| `http_status` | integer | HTTP status; non-success is not an empty response |
| `raw_artifact_uri` | text | Durable external path/object URI for original body |
| `raw_sha256` | hex text | SHA256 of uncompressed response bytes |
| `compressed_sha256` | hex text, nullable | SHA256 of stored compressed body |
| `schema_version` | text | Normalizer version that produced derived rows |
| `parse_status` | enum | `PARSED`, `PARTIAL`, `FAILED` |
| `issue_count` | integer | Count of linked source/parse issues |

Unique key: (`game_id`, `source_name`, `raw_sha256`). Retain superseded source
responses as distinct evidence; never overwrite a body in place.

## `game_event`

One row per PBP event. Preserve source fields alongside normalized values.

| Field | Type | Meaning |
|---|---|---|
| `game_id` | text | Canonical game ID |
| `source_event_id` | integer/text | GameCenter event ID, scoped to game |
| `event_type` | text | Published `typeDescKey` |
| `period_number` | integer, nullable | Published period number |
| `period_type` | enum, nullable | `REG`, `OT`, `SO`, or `UNKNOWN` |
| `time_in_period` | text, nullable | Original `MM:SS` clock string |
| `elapsed_seconds` | integer, nullable | Parsed elapsed seconds, preserving the original string |
| `situation_code` | text, nullable | Original four-character source code |
| `away_goalie_present` | boolean, nullable | Decoded situation code; null if invalid/missing |
| `away_skaters` | integer, nullable | Decoded situation code |
| `home_skaters` | integer, nullable | Decoded situation code |
| `home_goalie_present` | boolean, nullable | Decoded situation code |
| `event_owner_team_id` | integer, nullable | Numeric NHL team ID from source |
| `x_coord`, `y_coord` | number, nullable | Original rink coordinates; never impute |
| `zone_code` | text, nullable | Published zone value |
| `shot_type` | text, nullable | Published shot type; absent blocked-shot types remain null |
| `goalie_in_net_id` | integer, nullable | Numeric NHL ID when published |
| `source_payload_sha256` | hex text | Links event to immutable PBP response |
| `event_quality_status` | enum | `VERIFIED`, `PARTIAL`, `QUARANTINED`, `NOT_APPLICABLE` |

Primary key: (`game_id`, `source_event_id`). Do not treat source event IDs as
shift-chart event numbers; align using game, period, and clock interval, with
boundary uncertainty recorded.

## `event_player_role`

One row per event-player role, allowing multiple scorers, assists, penalties,
goalies, shooters, blockers, hitters, and other source roles without lossy
columns.

| Field | Type | Meaning |
|---|---|---|
| `game_id`, `source_event_id` | text/integer | Foreign key to `game_event` |
| `player_id` | integer | Numeric NHL player ID |
| `role` | enum/text | `SHOOTER`, `GOAL_SCORER`, `GOALIE_IN_NET`, `ASSIST_1`, `ASSIST_2`, `BLOCKER`, etc. |
| `source_field` | text | Exact source field used for this role |
| `identity_status` | enum | `MATCHED`, `MISSING`, `CONFLICTING` |

Unique key: (`game_id`, `source_event_id`, `player_id`, `role`). A goal scorer
may be used as the SOG credited player for that goal event, while retaining the
fact that the raw `shootingPlayerId` field was absent.

## `player_shift`

One row per player shift interval from the shift chart.

| Field | Type | Meaning |
|---|---|---|
| `game_id` | text | Canonical NHL game ID |
| `player_id` | integer | Numeric NHL player ID |
| `team_id` | integer | Numeric NHL team ID |
| `period_number` | integer | Shift period |
| `start_clock`, `end_clock` | text | Original source clocks |
| `start_elapsed_seconds`, `end_elapsed_seconds` | integer, nullable | Parsed elapsed bounds |
| `duration_seconds` | integer, nullable | Published duration, retained separately from computed bounds |
| `shift_type_code` | integer | Source type code |
| `source_row_number` | integer | Row position for auditability |
| `source_payload_sha256` | hex text | Links row to immutable shift-chart response |
| `interval_status` | enum | `VALID`, `BOUNDARY_CONFLICT`, `DUPLICATE`, `INVALID` |

Primary key: (`game_id`, `source_payload_sha256`, `source_row_number`). Preserve
duplicate source rows as evidence, but do not count them twice in a reconstructed
on-ice set.

## `event_lineup_check`

Derived audit result for each event/role or event situation check, not a raw
source fact.

| Field | Type | Meaning |
|---|---|---|
| `game_id`, `source_event_id` | text/integer | Event identity |
| `check_type` | enum | `SHOOTER_ON_ICE`, `GOALIE_ON_ICE`, `SITUATION_COUNTS`, `GOALIE_SUBSTITUTION` |
| `player_id` | integer, nullable | Player being checked, when applicable |
| `expected_value` | text/JSON, nullable | PBP role or decoded situation |
| `observed_value` | text/JSON, nullable | Shift intervals active at event clock |
| `status` | enum | `MATCH`, `MISMATCH`, `BOUNDARY_AMBIGUOUS`, `NO_EVIDENCE` |
| `boundary_tolerance_seconds` | integer | Audit tolerance; default 1 in this sample study |
| `normalizer_version` | text | Reproducible implementation version |

## `research_outcome_quality`

Read-only crosswalk to the approved label-quality reader. This table identifies
which target may be used; it does not rewrite the source label.

| Field | Type | Meaning |
|---|---|---|
| `game_id` | text | Canonical game ID |
| `player_id` | integer | Numeric NHL player ID |
| `statistic` | enum | `SOG`, `SAVES`, `SHOTS_AGAINST`, `GOALS_AGAINST` |
| `official_value` | integer, nullable | Original official value from approved artifact |
| `accepted_value` | integer, nullable | Approved accepted label; null for untrusted rows |
| `quality_status` | enum | Approved `VERIFIED`, `ADJUDICATED`, `QUARANTINED`, `NOT_APPLICABLE` |
| `eligible_training`, `eligible_evaluation`, `eligible_grading` | boolean | Purpose-specific eligibility flags |
| `reason_code` | text | Approved quality reason |
| `label_id`, `source_issue_id` | text | Provenance links to quality artifact and issue ledger |

Only `VERIFIED`/`ADJUDICATED` rows whose purpose-specific eligibility flag is
true may supply a target. `NOT_APPLICABLE` zero-TOI goalie slots never become
zero-save outcomes. Quarantined values remain visible to audits but unavailable
as targets or derived features.

## `event_data_issue`

Append-only issue ledger keyed to affected source/game/event/player/statistic.
Include issue type, source hashes, raw values, comparison values, detection rule,
first-seen time, status, reviewer decision, and links to the report/test that
establishes the disposition. Do not overwrite an unresolved issue when a later
source or correction arrives.

## Import contract

1. Persist raw PBP and shift responses outside ordinary Git history, with URL,
   retrieval time, status, byte count, and hashes in a manifest.
2. Normalize idempotently into versioned derived artifacts; never update the
   frozen 4,876-game population or approved outcomes.
3. Use source game IDs and numeric player IDs for joins. Missing joins become
   explicit issue rows.
4. Keep source event time and shift clocks in period-relative elapsed seconds;
   don't infer event order from unrelated source sequence numbers.
5. Preserve shootouts as a distinct period type. Exclude them from regulation
   SOG/goalie-stat totals, while retaining official shootout winner scoring as a
   separate final-score convention.
6. Keep all unobserved values null. No coordinate, shot type, event shooter,
   goalie, shift, or outcome imputation is part of ingestion.
