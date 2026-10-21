# Proposed NHL full-frame event schema

This schema preserves publisher values and audit results as separate layers. It
does not turn every game into one all-or-nothing usability flag. Team outcomes,
individual events, player identity, goalie identity, spatial fields, and shift
intervals have independent dispositions.

## 1. `game_source`

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id` | string | Direct | NHL game ID; canonical join key. |
| `season_start_year` | integer | Direct from pinned frame | Season convention is NHL label start year. |
| `game_date` | date | Direct from pinned frame | Keep source date unchanged. |
| `home_team`, `away_team` | string | Direct from pinned frame | Compare to PBP abbreviations and official outcome sides. |
| `pbp_home_team_id`, `pbp_away_team_id` | integer | Direct from PBP | Compare abbreviations and event owner IDs to the frame. |
| `pbp_source_url`, `shift_source_url` | string | Direct provenance | Exact request URLs. |
| `pbp_sha256_raw`, `pbp_sha256_gzip` | hex string | Computed provenance | Both bodies must verify before use. |
| `shift_sha256_raw`, `shift_sha256_gzip` | hex string | Computed provenance | Both bodies must verify before use. |
| `prior_manifest_sha256`, `prior_manifest_disposition` | hex string, enum | Derived provenance | Reconcile each hardened manifest row to the earlier full-frame manifest; any mismatch quarantines that source row. |
| `evidence_origin` | string | Direct from cache sidecar/import manifest | Distinguishes sample-cache reuse, an existing unclassified cache body, and a new network response. |
| `sample_event_manifest_sha256`, `sample_source_commit` | hex string, commit | Direct from copied sample sidecar | Present for the 300 sample bodies; ties them to the original audit manifest and pinned source commit. |
| `request_duration_seconds`, `request_elapsed_with_pacing_seconds` | number | Measured provenance | The latter includes the configured pre-request pause; unavailable for older cached rows that did not record it. |
| `frame_sha256`, `source_list_sha256` | hex string | Computed provenance | Bind rows to the pinned canonical population. |
| `team_score_disposition`, `team_sog_disposition` | enum | Derived | `ACCEPT`, `QUARANTINE`, or `REJECT`, with reason codes. Independent of shift eligibility. |

Raw response bodies remain immutable and outside Git. Normalized rows retain
the source hashes and the importer/auditor version that produced them.

The audit emits `game_source_provenance.csv.gz` with one row per game and
source. It binds source URL, response identity, body hashes and sizes, payload
row count, retrieval timing/origin, verification disposition, frame hash, and
audit version. Event, target, and shift ledgers join to this provenance by
`game_id`; `source_kind` distinguishes PBP from shift-chart evidence.

## 2. `game_event`

One row per PBP play, including events outside the shot family.

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id`, `source_event_id` | string | Direct | Composite source key. Missing or duplicate IDs are explicit issues. |
| `event_type` | string | Direct | NHL `typeDescKey`; preserve unknown values. |
| `period_number`, `period_type` | integer, enum | Direct | `REG`, `OT`, `SO` when published and valid. |
| `time_in_period` | `MM:SS` string | Direct | Event clock, not continuous elapsed wall time. |
| `event_owner_team_id` | integer, nullable | Direct | Must resolve to one of the two PBP team IDs. |
| `situation_code` | four-character string, nullable | Direct | Retain raw digits in published order: away goalie, away skaters, home skaters, home goalie. |
| `strength_state` | enum, nullable | Derived | Parse from the raw situation code for regulation/overtime; shootout events are `NOT_APPLICABLE`. Preserve the raw code alongside it. |
| `event_disposition` | enum | Derived | Source event/time integrity only. Feature dispositions remain separate. |
| `situation_deployment_disposition` | enum | Derived from raw situation and accepted shifts | A match supports only the recorded event-time deployment comparison. |
| `quality_reason_codes` | array of strings | Derived | Append-only issue references; never silently repair source values. |

The source provides discrete events. It does not provide continuous puck
position, player movement, possession, or a complete latent game state.

## 3. `shot_event`

One row for every `shot-on-goal`, `goal`, `missed-shot`, and `blocked-shot`.

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id`, `source_event_id` | string | Direct | Foreign key to `game_event`. |
| `outcome_type` | enum | Direct | Keep goal, on-target non-goal, miss, and block distinct. |
| `period_number`, `period_type`, `time_in_period` | mixed | Direct | Use the game-event timeline. |
| `shooting_player_id` | integer, nullable | Direct | NHL `shootingPlayerId`; cross-check official player ID and team. |
| `credited_sog_player_id` | integer, nullable | Derived with documented rule | Use goal scorer ID only when a goal lacks direct `shootingPlayerId`; record the fallback. |
| `event_owner_team_id` | integer, nullable | Direct | Compare with the two PBP team IDs and shooter’s official team. |
| `x_coord`, `y_coord` | number, nullable | Direct | Preserve nulls and raw rink orientation. No imputation. |
| `zone_code`, `shot_type`, `miss_reason` | string, nullable | Direct | Missing blocked-shot types are expected in the source; do not infer them. |
| `goalie_in_net_id` | integer, nullable | Direct when present | Verify against official goalie appearance and defending team. Never fill from shift charts. |
| `ordinary_shot_eligible` | boolean | Derived | False for every shootout shot. |
| `spatial_disposition`, `shot_type_disposition`, `shooter_disposition`, `goalie_disposition` | enum | Derived | Separate component gates; a missing coordinate does not erase a valid team shot count. |
| `shooter_shift_status`, `shooter_on_ice_disposition` | enum | Derived from event clock and accepted shifts | Only `ACCEPT` supports an event-to-shooter deployment join. |
| `goalie_shift_status`, `goalie_shift_comparison_disposition` | enum | Derived diagnostic | Checks direct PBP goalie ID against shifts; does not assign goalie identity or statistics. |

Official team SOG reconciliation counts goals and `shot-on-goal` events outside
shootouts. Shootout attempts are excluded from ordinary SOG and goals. For
official final score comparison, add one goal to the official shootout winner
after comparing regulation/overtime PBP goals; do not count shootout goal
events as ordinary scoring.

## 4. `penalty_event`

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id`, `source_event_id`, period and clock | mixed | Direct | Keep the source event key and timeline. |
| `event_owner_team_id` | integer, nullable | Direct | Validate against the game’s two teams. |
| `committed_by_player_id`, `drawn_by_player_id` | integer, nullable | Direct | Validate stable IDs against official game appearances when present. |
| `duration_minutes` | number, nullable | Direct | NHL PBP duration is stored in minutes; do not reinterpret it as `MM:SS`. |
| `penalty_type`, `penalty_reason` | string, nullable | Direct | Preserve publisher strings/codes. |
| `timing_disposition`, `duration_disposition`, `identity_disposition` | enum | Derived | Independent gates for timing, power-play derivation, and player attribution. |

Power-play intervals are derived from penalty timing and manpower events. They
must retain links to the source penalties and situation codes used to derive
them.

## 5. `player_shift_interval`

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id`, `source_shift_id` | string | Direct | Preserve source row ID. |
| `player_id`, `team_id`, `team_abbrev` | mixed | Direct | Validate against PBP roster and official player/team appearance rows. |
| `period_number`, `start_time`, `end_time`, `duration` | mixed | Direct | Period-local shift-chart interval and publisher duration. |
| `official_boxscore_toi_seconds` | integer, nullable | Direct from official outcome artifact | Authoritative game TOI, including goalie duration. |
| `toi_delta_seconds` | integer, nullable | Derived | Shift interval totals compared to official TOI; never replace official duration. |
| `disposition`, `reason_codes` | enum, array | Derived | Duplicate, overlap, identity, malformed interval, and TOI gates. |

An observed interval is a feed's recorded deployment, not tracking. The interval
is accepted only after player identity, team, overlap, and official TOI checks.
Game-level duplicated charts (median shift/official TOI ratio near 2x) are
rejected in full. Event-on-ice rows are separately quarantined when the event
falls off a shift, on an untrusted shift, or at an ambiguous boundary.

Shift charts describe recorded deployment intervals. They do not show actual
player movement, puck possession, or the exact continuous on-ice state between
events. Goalie shifts are never used to assign saves or shots faced; goalie
event identity is checked from PBP `goalieInNetId` separately.

## 6. `official_player_target`

| Field | Type | Source/status | Notes |
|---|---|---|---|
| `game_id`, `player_id`, `statistic` | mixed | Direct from approved label artifact | Stable ID joins only. |
| `official_value`, `accepted_value`, `quality_status`, `reason_code` | mixed | Direct from approved label artifact | Preserve adjudication and quarantine state. |
| `eligible_training`, `eligible_evaluation`, `eligible_grading` | boolean | Direct, enforced by approved reader | A quarantined row is never a target. |
| `pbp_event_count`, `event_count_match` | mixed | Derived | Goalie event totals use direct PBP attribution only. |
| `official_boxscore_toi_seconds` | integer, nullable | Direct from official outcome artifact | Authoritative goalie duration where applicable. |
| `target_disposition` | enum | Derived | A trusted label remains ineligible for this event-derived target if PBP attribution does not reconcile. |

## 7. `event_quality` and provenance

Store component-level disposition and evidence, not a single game flag:

- `ACCEPT`: source identity, payload shape, required field identities, and that
  component’s reconciliation rule pass.
- `REJECT`: impossible identity, duplicate source event/interval, malformed
  source row, or a source ID outside the pinned frame.
- `QUARANTINE`: unresolved disagreement or a required value is missing for the
  target component. Preserve the row and reason.
- `NOT_APPLICABLE`: the component does not apply, such as ordinary shot counts
  for shootout attempts or shot type on blocked shots.

Every normalized row carries `game_id`, source keys, source hashes, frame hash,
audit version, and reason references. Corrections require new adjudication
evidence and a new derived artifact; no raw outcome or missing value is
overwritten.

## 8. Field availability and trust

- **Directly observed:** PBP event ID/type/period/clock, event-owner team ID,
  raw situation code, shot outcome, published coordinates/type, player IDs,
  goalie-in-net ID, penalty fields, and shift-chart intervals. Official final
  scores, SOG, player statistics, identities, and boxscore TOI come directly
  from the pinned official outcome artifact.
- **Derived:** strength class, credited shooter fallback for goals, team and
  player event counts, shootout-adjusted official-score comparison, shift/TOI
  deltas, event-to-shift alignment, eligibility, and reason codes. Each is
  stored alongside its source fields and disposition.
- **Unavailable when absent:** missing event coordinates or shot type, missing
  direct goalie IDs, and omitted penalty/player fields remain null. Actual
  player movement, puck coordinates between events, possession, and continuous
  on-ice state are not supplied by these feeds.
- **Unreliable unless individually accepted:** shift deployment is quarantined
  by player/game when identity, TOI, overlap, duplicate-chart, or event-time
  checks fail. Goalie shift intervals are especially unreliable for assigning
  saves or shots faced; use direct event goalie IDs plus approved official
  labels, and official boxscore TOI for goalie duration.
